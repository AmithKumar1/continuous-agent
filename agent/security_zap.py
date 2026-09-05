import asyncio
import logging
from typing import Any, Dict, List
from urllib.parse import urlparse
import httpx
from config import config
from agent.security_tools import is_target_allowed

logger = logging.getLogger("SecurityZAP")

class ZapClient:
    def __init__(self, base_url: str = "http://localhost:8080", api_key: str = ""):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def _headers(self) -> Dict[str, str]:
        return {"X-ZAP-API-Key": self.api_key} if self.api_key else {}

    async def spider_and_scan(self, target_url: str) -> Dict[str, Any]:
        host = urlparse(target_url).netloc
        if not is_target_allowed(host):
            return {"error": f"Target host {host} outside authorized scope."}

        async with httpx.AsyncClient(timeout=30.0, headers=self._headers()) as client:
            try:
                # Trigger Spider
                res = await client.get(f"{self.base_url}/JSON/spider/action/scan/", params={"url": target_url})
                if res.status_code != 200:
                    return {"status": "UNAVAILABLE", "detail": "OWASP ZAP daemon not accessible"}

                scan_id = res.json().get("scan", "0")
                for _ in range(10):
                    await asyncio.sleep(2)
                    st_res = await client.get(f"{self.base_url}/JSON/spider/view/status/", params={"scanId": scan_id})
                    if st_res.json().get("status") == "100":
                        break

                # Fetch Alerts
                alerts_res = await client.get(f"{self.base_url}/JSON/core/view/alerts/", params={"baseurl": target_url})
                alerts = alerts_res.json().get("alerts", [])

                categorized = {}
                for a in alerts:
                    risk = a.get("risk", "Low")
                    categorized.setdefault(risk, []).append({
                        "alert": a.get("alert"),
                        "url": a.get("url"),
                        "confidence": a.get("confidence")
                    })

                return {
                    "status": "COMPLETED",
                    "target": target_url,
                    "total_alerts": len(alerts),
                    "risks": categorized
                }
            except Exception as e:
                logger.warning(f"ZAP audit bypassed: {e}")
                return {"status": "BYPASSED", "detail": str(e)}

zap_client = ZapClient(base_url=config.ZAP_BASE_URL, api_key=config.ZAP_API_KEY)

async def run_zap_scan_tool(arguments: Dict[str, Any]) -> str:
    target = arguments.get("target_url", "").strip()
    res = await zap_client.spider_and_scan(target)
    return str(res)
