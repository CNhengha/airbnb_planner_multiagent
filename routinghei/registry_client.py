import httpx
from .registry_models import RegistryListReq, RegistryListResp


class RegistryClient:
    """子系统2 -> Registry 的 HTTP 客户端：我们写请求体，解析响应体。"""

    def __init__(self, base_url: str, timeout: float = 8.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def list_agents(self, keyword: str, req: RegistryListReq) -> RegistryListResp:
        """
        调用 API 1：POST /api/v1/{keyword}/list

        Args:
            keyword: 关键词家族（如 "weather"）
            req:     RegistryListReq（request_id / task / top_k）

        Returns:
            RegistryListResp
        """
        url = f"{self.base_url}/api/v1/{keyword}/list"
        async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as cli:
            r = await cli.post(url, json=req.model_dump())
            r.raise_for_status()
            return RegistryListResp.model_validate(r.json())
#发请求的部分