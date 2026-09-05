import secrets
from typing import Optional
from fastapi import Depends, HTTPException, Query, Security, WebSocket, status
from fastapi.security.api_key import APIKeyHeader
from fastapi.security.http import HTTPBearer, HTTPAuthorizationCredentials
from config import config

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
bearer_auth = HTTPBearer(auto_error=False)

def verify_api_key(
    api_key: Optional[str] = Security(api_key_header),
    credentials: Optional[HTTPAuthorizationCredentials] = Security(bearer_auth)
) -> str:
    token = api_key or (credentials.credentials if credentials else None)
    expected = config.DASHBOARD_API_KEY
    if not token or not secrets.compare_digest(token, expected):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Invalid or missing API key / Bearer token"
        )
    return token

async def verify_websocket_auth(
    websocket: WebSocket,
    api_key: Optional[str] = Query(None)
) -> bool:
    if not api_key or not secrets.compare_digest(api_key, config.DASHBOARD_API_KEY):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return False
    return True
