'''
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
'''
import os
import httpx
from registry_models import RegistryListReq, RegistryListResp


class RegistryClient:
    """子系统2 -> Registry 的 HTTP 客户端：我们写请求体，解析响应体。"""

    def __init__(self, base_url: str, timeout: float = 8.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

        # 从环境变量读取 API KEY（如果没设置就用默认 dev-admin-api-key）
        self.api_key = os.getenv("API_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJhMmEtcmVnaXN0cnkiLCJhdWQiOiJhMmEtcmVnaXN0cnkiLCJzdWIiOiJhM2IxZWZhYS05MDM5LTQzZGQtOTIzZC0zMTRkN2RiMjcwNzEiLCJpYXQiOjE3NjMwOTczMTcsIm5iZiI6MTc2MzA5NzMxNywiZXhwIjoxNzY1Njg5MzE3LCJ1c2VyX2lkIjoiYTNiMWVmYWEtOTAzOS00M2RkLTkyM2QtMzE0ZDdkYjI3MDcxIiwidXNlcm5hbWUiOiJ1c2VyMSIsImVtYWlsIjoidXNlcjFAZXhhbXBsZS5jb20iLCJjbGllbnRfaWQiOiJhM2IxZWZhYS05MDM5LTQzZGQtOTIzZC0zMTRkN2RiMjcwNzEiLCJyb2xlcyI6WyJVc2VyIl0sInRlbmFudCI6ImRlZmF1bHQifQ.KK8MyI711efKineVNtDqH0x-XPerfk1qFA_5VfZgah0")

        # 每次请求都要带 Authorization 头
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def list_agents(self, keyword: str, req: RegistryListReq) -> RegistryListResp:
        """
        调用 API 1：POST /api/v1/{keyword}/list
        """
        url = f"{self.base_url}/api/v1/{keyword}/list"

        async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as cli:
            r = await cli.post(url, json=req, headers=self.headers)

            # 401/403 等会在这里抛出
            try:
                r.raise_for_status()
            except httpx.HTTPStatusError:
                print("\n❌ Registry returned error:", r.text)
                print("Request JSON:", req.model_dump())
                raise


            return RegistryListResp.model_validate(r.json())
