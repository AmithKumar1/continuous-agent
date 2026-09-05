import asyncio
import socket
from typing import Any, Dict, List
from urllib.parse import urlparse
import httpx
from config import config

def is_target_allowed(host: str) -> bool:
    clean_host = host.lower().split(":")[0]
    return any(clean_host == allowed.lower() for allowed in config.SECURITY_SCAN_ALLOWED_HOSTS)

async def scan_single_port(host: str, port: int, timeout: float = 1.0) -> Dict[str, Any]:
    loop = asyncio.get_running_loop()
    def check():
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        try:
            res = s.connect_ex((host, port))
            return res == 0
        except Exception:
            return False
        finally:
            s.close()

    is_open = await loop.run_in_executor(None, check)
    return {"port": port, "is_open": is_open}

async def scan_ports(arguments: Dict[str, Any]) -> str:
    host = arguments.get("host", "").strip()
    ports = arguments.get("ports") or [80, 443, 8080, 8443, 3000, 5000]

    if not is_target_allowed(host):
        return f"Access Denied: Target host '{host}' is outside allowed scope ({config.SECURITY_SCAN_ALLOWED_HOSTS})."

    tasks = [scan_single_port(host, p) for p in ports]
    results = await asyncio.gather(*tasks)
    open_ports = [r["port"] for r in results if r["is_open"]]

    return f"Port Scan Report for {host}:\nOpen Ports: {open_ports or 'None detected'}"

async def check_http_security_headers(arguments: Dict[str, Any]) -> str:
    url = arguments.get("url", "").strip()
    parsed = urlparse(url)
    host = parsed.netloc

    if not is_target_allowed(host):
        return f"Access Denied: Target URL '{url}' host '{host}' is outside allowed scope."

    recommended_headers = [
        "Strict-Transport-Security",
        "Content-Security-Policy",
        "X-Frame-Options",
        "X-Content-Type-Options",
        "Referrer-Policy"
    ]

    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(url)
            headers = resp.headers

        present = {h: headers.get(h) for h in recommended_headers if h in headers}
        missing = [h for h in recommended_headers if h not in headers]

        return (
            f"Security Headers Audit for {url}:\n"
            f"Present: {list(present.keys())}\n"
            f"Missing / At-Risk: {missing}"
        )
    except Exception as e:
        return f"Failed to check security headers for {url}: {str(e)}"
