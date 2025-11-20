
# pylint: disable=logging-fstring-interpolation
import os
import uuid
from typing import Any, Optional, List, Tuple

from dotenv import load_dotenv

from a2a.types import (
    MessageSendParams,
    SendMessageRequest,
    SendMessageResponse,
    SendMessageSuccessResponse,
    Task,
)
from google.adk.tools.tool_context import ToolContext

from routing_remote_agent_connection import RemoteAgentConnections
from registry_client import RegistryClient
from registry_models import RegistryListReq, RegistryListResp


load_dotenv()


class RoutingAgent:
    """
    子系统2（语义路由调度层）：
    1) 调用 Registry（/api/v1/{keyword}/list）获取候选代理列表（我们负责写请求体）
    2) 选取候选（按 score）
    3) 用返回的 url 直接调用目标 Agent 的 /messages（A2A 兼容），并解析响应为 Task
    """

    def __init__(self, registry_base_url: Optional[str] = None) -> None:
        self.registry = RegistryClient(
            registry_base_url or os.getenv("REGISTRY_BASE_URL", "http://localhost:8000")
        )
        # 可选：缓存已构造的直连连接（按逻辑名）
        self._connections: dict[str, RemoteAgentConnections] = {}

    # -------- 路由：调 Registry 并构造直连连接 --------
    async def resolve_client(
        self, keyword: str, task: str, top_k: int
    ) -> Tuple[List[Tuple[str, str]], List[dict]]:
        """
        调用 Registry，按 score 降序选取前 k 个候选，
        返回:
            results: [(agent_name, url)]
            agents_clean: 去掉 score / agent_id 的完整 agent 信息
        """
        # === 构造请求（纯字典） ===
        req = {
            "request_id": f"req-{uuid.uuid4()}",
            "task": task,
            "top_k": top_k,
        }

        resp = None
        resp: RegistryListResp = await self.registry.list_agents(keyword, req)
        # === 验证响应 ===
        if resp.status != "success" or not resp.agents:
            raise LookupError(
                f"No agent candidates for keyword='{keyword}', task='{task[:80]}...'"
            )

        # === 按分数降序排序 ===
        # resp.agents 是 List[RegistryAgentItem]（Pydantic 模型）
        agents_sorted = sorted(resp.agents, key=lambda a: a.score, reverse=True)

        # === 限制 top_k ===
        count = len(agents_sorted)
        k = min(top_k, count) if count > 0 else 0
        if k == 0:
            raise LookupError("No valid candidates after sorting.")

        # === 构造 results [(name, url)] ===
        results: List[Tuple[str, str]] = []
        for item in agents_sorted[:k]:
            results.append((item.name, item.url))
            self._connections[item.name] = item.url

        # === 构造 agents_clean（去掉 score 和 agent_id），但保留其他字段 ===
        agents_clean: List[dict] = []
        for agent in agents_sorted[:k]:
            clean = agent.model_dump(exclude={"score", "agent_id"})
            agents_clean.append(clean)

        return results, agents_clean


    # -------- 入口：路由 + 发送消息 + 解析 --------
    async def send_message_to_agent(
            self,
            keyword: str,
            task: str,
            tool_context: ToolContext,
            top_k: int = 3,
    ) -> Optional[Task]:
        """
        先路由（取 Top-k），再按得分从高到低依次直连 /messages。
        返回第一个成功的 Task；若都失败，返回 None（并在异常中提供聚合信息也可选）。
        """
        state = tool_context.state

        # 1) 路由：拿前 k 个候选
        candidates = await self.resolve_client(keyword=keyword, task=task, top_k=top_k)

        # 2) 固定一次 context_id（多次重试保持同一会话）
        context_id = state.get("context_id") or str(uuid.uuid4())
        state["context_id"] = context_id

        input_meta = state.get("input_message_metadata") or {}

        # 3) 逐个候选尝试发送
        errors: list[str] = []
        for agent_name, connection in candidates:
            state["active_agent"] = agent_name
            message_id = input_meta.get("message_id") or uuid.uuid4().hex

            payload: dict[str, Any] = {
                "message": {
                    "role": "user",
                    "parts": [{"type": "text", "text": task}],
                    "messageId": message_id,
                    "contextId": context_id,
                    # "metadata": input_meta,  # 远端支持时再打开
                }
            }

            message_request = SendMessageRequest(
                id=message_id, params=MessageSendParams.model_validate(payload)
            )

            try:
                send_response: SendMessageResponse = await connection.send_message(message_request)
            except Exception as e:
                errors.append(f"{agent_name}: request failed ({e})")
                continue

            # 校验 A2A 响应
            if not isinstance(send_response.root, SendMessageSuccessResponse):
                errors.append(f"{agent_name}: non-success response")
                continue
            if not isinstance(send_response.root.result, Task):
                errors.append(f"{agent_name}: success wrapper but no Task")
                continue

            #  首个成功即返回
            return send_response.root.result

        # 所有候选都失败
        # print 或 log 一下便于排查
        if errors:
            print("All candidates failed:\n" + "\n".join(errors))
        return None

