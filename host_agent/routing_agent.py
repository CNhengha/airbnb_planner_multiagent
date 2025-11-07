# pylint: disable=logging-fstring-interpolation
import asyncio
import json
import os
import sys
import uuid
from google.genai import types
from typing import Any
from google.adk.runners import Runner
import httpx
from types import SimpleNamespace
from a2a.client import A2ACardResolver
from a2a.types import (
    AgentCard,
    MessageSendParams,
    Part,
    SendMessageRequest,
    SendMessageResponse,
    SendMessageSuccessResponse,
    Task,
)
from dotenv import load_dotenv
from google.adk import Agent
from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.tools.tool_context import ToolContext
from remote_agent_connection import (
    RemoteAgentConnections,
    TaskUpdateCallback,
)
from a2a.types import Task, Message, Part, TextPart
load_dotenv()
from google import genai
try:
    from airbnb_planner_multiagent.routing.routing_agent import RoutingAgent as routing
except ImportError:
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    from routing.routing_agent import RoutingAgent as routing

def convert_part(part: Part, tool_context: ToolContext):
    """Convert a part to text. Only text parts are supported."""
    if part.type == 'text':
        return part.text

    return f'Unknown type: {part.type}'


def convert_parts(parts: list[Part], tool_context: ToolContext):
    """Convert parts to text."""
    rval = []
    for p in parts:
        rval.append(convert_part(p, tool_context))
    return rval


def create_send_message_payload(
    text: str, task_id: str | None = None, context_id: str | None = None
) -> dict[str, Any]:
    """Helper function to create the payload for sending a task."""
    payload: dict[str, Any] = {
        'message': {
            'role': 'user',
            'parts': [{'type': 'text', 'text': text}],
            'messageId': uuid.uuid4().hex,
        },
    }

    if task_id:
        payload['message']['taskId'] = task_id

    if context_id:
        payload['message']['contextId'] = context_id
    return payload
class RoutingAgent:
    """The Routing agent.

    This is the agent responsible for choosing which remote seller agents to send
    tasks to and coordinate their work.
    """

    def __init__(
        self,
        task_callback: TaskUpdateCallback | None = None,
    ):
        self.task_callback = task_callback
        self.remote_agent_connections: dict[str, RemoteAgentConnections] = {}
        self.cards: dict[str, AgentCard] = {}
        self.agents: str = ''

    async def _async_init_components(
        self,
        remote_agent_addresses: list[str],
        agent_names: list[str],
    ) -> None:
        """Initialize connections to remote agents (no card fetching, use agent names)."""
        for agent_name, address in zip(agent_names, remote_agent_addresses):
            if agent_name in self.remote_agent_connections:
                continue
            try:
                # 创建 RemoteAgentConnections 实例（不读取 agent card）
                remote_connection = RemoteAgentConnections(
                    agent_card=None,  # 不加载
                    agent_url=address
                )

                # 用 agent_name 作为 key（替代原来的 URL）
                self.remote_agent_connections[agent_name] = remote_connection

                print(f"[RoutingAgent] 🔗 Connected (no-card) to {agent_name} @ {address}")

            except Exception as e:
                print(f"[RoutingAgent] ❌ Failed to connect to {agent_name} @ {address}: {e}")

        # 记录连接信息（仅作调试用途）
        self.agents = "\n".join(
            [f"{{'name': '{name}', 'url': '{url}'}}" for name, url in zip(agent_names, remote_agent_addresses)]
        )


    @classmethod
    async def create(
        cls,
        remote_agent_addresses: list[str],
        task_callback: TaskUpdateCallback | None = None,
    ) -> 'RoutingAgent':
        """Create and asynchronously initialize an instance of the RoutingAgent."""
        instance = cls(task_callback)
        instance.remote_agent_connections = {}
        instance.cards = {}
        return instance

    def create_agent(self) -> Agent:
        """Create an instance of the RoutingAgent."""
        return Agent(
            model='gemini-2.5-flash',
            name='Routing_agent',
            instruction=self.root_instruction,
            before_model_callback=self.before_model_callback,
            description=(
                'This Routing agent orchestrates the decomposition of the user asking for weather forecast, airbnb accommodation, or tripadvisor searches'
            ),
            tools=[
                self.send_message,
            ],
        )

    def root_instruction(self, context: ReadonlyContext) -> str:
        """Generate the root instruction for the RoutingAgent."""
        current_agent = self.check_active_agent(context)
        return f"""
        **Role:** You are an expert Routing Delegator. Your primary function is to accurately delegate user inquiries regarding Weather, Accommodations,TripAdvisor,Location or Transport searches to the appropriate specialized remote agents.

        **Core Directives:**

        * **Task Delegation:** Utilize the `send_message` function to assign actionable tasks to remote agents.
        * **Contextual Awareness for Remote Agents:** If a remote agent repeatedly requests user confirmation, assume it lacks access to the         full conversation history. In such cases, enrich the task description with all necessary contextual information relevant to that         specific agent.
        * **Autonomous Agent Engagement:** Never seek user permission before engaging with remote agents. If multiple agents are required to         fulfill a request, connect with them directly without requesting user preference or confirmation.
        * **Transparent Communication:** Always present the complete and detailed response from the remote agent to the user.
        * **User Confirmation Relay:** If a remote agent asks for confirmation, and the user has not already provided it, relay this         confirmation request to the user.
        * **Focused Information Sharing:** Provide remote agents with only relevant contextual information. Avoid extraneous details.
        * **No Redundant Confirmations:** Do not ask remote agents for confirmation of information or actions.
        * **Tool Reliance:** Strictly rely on available tools to address user requests. Do not generate responses based on assumptions. If         information is insufficient, request clarification from the user.
        * **Prioritize Recent Interaction:** Focus primarily on the most recent parts of the conversation when processing requests.
        * **Active Agent Prioritization:** If an active agent is already engaged, route subsequent related requests to that agent using the         appropriate task update tool.
        * **Keyword Selection:** 
          Instead of specifying an agent name, you MUST include a `keyword` argument in your function call.
          The keyword MUST be selected from the following list:  
          - `"Weather"` → for any question related to climate, temperature, or forecasts  
          - `"Accommodations"` → for accommodation, rooms, stays, or booking requests  
          - `"TripAdvisor"` → for reviews, sightseeing, attractions, or travel planning
          - `"Location"` → for questions involving specific places, addresses, or geographic information 
          - `"Transport"` → for inquiries about transportation options, routes, schedules, or travel methods
        **Agent Roster:**

        **Keyword Set:** ["Weather"," Accommodations"," TripAdvisor","Location","Transport"]
        * Currently Active Seller Agent: `{current_agent['active_agent']}`
                """

    def check_active_agent(self, context: ReadonlyContext):
        state = context.state
        if (
            'session_id' in state
            and 'session_active' in state
            and state['session_active']
            and 'active_agent' in state
        ):
            return {'active_agent': f'{state["active_agent"]}'}
        return {'active_agent': 'None'}

    def before_model_callback(
        self, callback_context: CallbackContext, llm_request
    ):
        state = callback_context.state
        if 'session_active' not in state or not state['session_active']:
            if 'session_id' not in state:
                state['session_id'] = str(uuid.uuid4())
            state['session_active'] = True

    def list_remote_agents(self):
        """List the available remote agents you can use to delegate the task."""
        if not self.cards:
            return []

        remote_agent_info = []
        for card in self.cards.values():
            print(f'Found agent card: {card.model_dump(exclude_none=True)}')
            print('=' * 100)
            remote_agent_info.append(
                {'name': card.name, 'description': card.description}
            )
        return remote_agent_info
    
    async def _connect_to_registry_(self, keyword: str, task: str, topk: int):
        router = routing()  # ✅ 创建 RoutingAgent 实例
        topk_list = await router.resolve_client(keyword, task, topk)

        # 2️⃣ 解包成两个列表
        agent_names = [a[0] for a in topk_list]
        agent_urls = [a[1] for a in topk_list]

        # 3️⃣ 打印信息
        print(f"[Registry] Keyword='{keyword}' → Found {len(topk_list)} agents:")
        for name, url in topk_list:
            print(f"  - {name} @ {url}")

    # ✅ 返回 (全部agent名, 全部URL, 完整列表)
        return agent_names, agent_urls, topk_list

    async def send_message(
        self, keyword: str, task:str, tool_context: ToolContext
    ):
        topk=3
        """Send a task to dynamically discovered agents.

        Dynamically connects to agents returned by the registry,
        and sends the user's request to them concurrently.
        """
        state = tool_context.state

        # 1️⃣ 向注册中心请求 agent 列表
        agent_names, agent_urls, topk_list = await self._connect_to_registry_(keyword,task,topk)
        state["active_agent"] = agent_names
        state["registry_candidates"] = topk_list

        # 2️⃣ 懒连接：仅连接尚未建立的 URL
        for url in agent_urls:
            await self._async_init_components(agent_urls,agent_names)

        # 3️⃣ 构造消息 payload
        context_id = state.get("context_id", str(uuid.uuid4()))
        input_metadata = state.get("input_message_metadata", {})
        message_id = input_metadata.get("message_id", str(uuid.uuid4()))

        payload = {
            "message": {
                "role": "user",
                "parts": [{"type": "text", "text": task}],
                "messageId": message_id,
                "contextId": context_id,
            }
        }
        pretty_payload = json.dumps(payload, indent=4, ensure_ascii=False)
        print("\n==============================")
        print(f"[RoutingAgent] 📤 Sending payload to child agents ({keyword}):")
        print(pretty_payload)
        print("==============================\n")
        message_request = SendMessageRequest(
            id=message_id, params=MessageSendParams.model_validate(payload)
        )

        # 4️⃣ 定义子任务：并发访问每个 agent
        async def query_agent(agent_name: str):
            from a2a.types import SendMessageSuccessResponse, Task, SendMessageResponse

            client = self.remote_agent_connections.get(agent_name)
            if not client:
                return agent_name, {"error": f"No active connection for {agent_name}"}

            try:
                send_response = await client.send_message(message_request=message_request)

                # --- 三层兼容结构 ---
                if isinstance(send_response, Task):
                    return agent_name, send_response

                elif isinstance(send_response, SendMessageResponse):
                    if hasattr(send_response, "root") and isinstance(
                        send_response.root, SendMessageSuccessResponse
                    ):
                        if isinstance(send_response.root.result, Task):
                            return agent_name, send_response.root.result
                        else:
                            return agent_name, {
                                "error": "SendMessageSuccessResponse has no Task result"
                            }
                    else:
                        return agent_name, {
                            "error": f"Unexpected SendMessageResponse root type: {type(getattr(send_response, 'root', None))}"
                        }

                elif isinstance(send_response, dict):
                    return agent_name, send_response

                else:
                    return agent_name, {"error": f"Unknown response type: {type(send_response)}"}

            except Exception as e:
                print(f"[RoutingAgent] ❌ Error calling {agent_name}: {e}")
                return agent_name, {"error": str(e)}

        # 5️⃣ 并发执行所有子请求
        results = await asyncio.gather(*(query_agent(name) for name in agent_names))

        # 6️⃣ 聚合结果
        responses = {}
        for name, result in results:
            if isinstance(result, Task):
                text = None

                # ✅ 优先从 artifacts 提取
                if result.artifacts and len(result.artifacts) > 0:
                    art = result.artifacts[0]
                    if art.parts and len(art.parts) > 0:
                        text = art.parts[0].root.text

                # ✅ 若 artifacts 为空，再尝试从 history 提取
                if not text and result.history:
                    agent_msgs = [
                        m for m in result.history if getattr(m, "role", None) == "agent"
                    ]
                    if agent_msgs and agent_msgs[-1].parts:
                        text = agent_msgs[-1].parts[0].root.text

                responses[name] = text or "(no text)"
                print(
                    f"[RoutingAgent] ✅ {name} responded successfully: {responses[name][:100]}..."
                )
                continue  # 🔹防止执行下面的 else

            else:
                responses[name] = result
                print(f"[RoutingAgent] ⚠️ {name} returned non-task result: {result}")

        # 7️⃣ （可选）过滤掉空文本的 agent
        responses = {k: v for k, v in responses.items() if v and v != "(no text)"}
        print(f"[RoutingAgent] ✅ Final aggregated Markdown output:\n{responses}")
        combined_output = []
        for text in responses.values():
            if isinstance(text, str):
                combined_output.append(text.strip())
            elif isinstance(text, dict):
                combined_output.append(str(text))  # 防止 strip 报错
            else:
                combined_output.append(repr(text))  # 兜底

        final_text = "\n\n---\n\n".join(combined_output)
        print(f"[RoutingAgent] 🧩 Combined text output:\n{final_text}")
        return final_text


def _get_initialized_routing_agent_sync() -> Agent:
    """Synchronously creates and initializes the RoutingAgent."""

    async def _async_main() -> Agent:
        routing_agent_instance = await RoutingAgent.create(
            remote_agent_addresses=[
            ]
        )
        return routing_agent_instance.create_agent()

    try:
        return asyncio.run(_async_main())
    except RuntimeError as e:
        if 'asyncio.run() cannot be called from a running event loop' in str(e):
            print(
                f'Warning: Could not initialize RoutingAgent with asyncio.run(): {e}. '
                'This can happen if an event loop is already running (e.g., in Jupyter). '
                'Consider initializing RoutingAgent within an async function in your application.'
            )
        raise


root_agent = _get_initialized_routing_agent_sync()