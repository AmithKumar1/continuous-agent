import asyncio
import json
import logging
from typing import Any, Dict
from agent.rate_limiter import DomainRateLimiter

logger = logging.getLogger("ToolExecutor")

# Global locks to ensure deadlock-free ordered execution across resources
domain_locks: Dict[str, asyncio.Lock] = {}
locks_mutex = asyncio.Lock()

async def get_domain_lock(domain: str) -> asyncio.Lock:
    async with locks_mutex:
        if domain not in domain_locks:
            domain_locks[domain] = asyncio.Lock()
        return domain_locks[domain]

async def execute_single_tool_call(
    tool_call: Any,
    registry: Any,
    semaphore: asyncio.Semaphore,
    rate_limiter: DomainRateLimiter
) -> Dict[str, Any]:
    fn_name = tool_call.function.name
    raw_args = tool_call.function.arguments

    try:
        args = json.loads(raw_args)
    except json.JSONDecodeError:
        args = {}

    target_domain = "global"
    if "url" in args:
        target_domain = rate_limiter.extract_domain(args["url"])
    elif "host" in args:
        target_domain = rate_limiter.extract_domain(args["host"])

    async with semaphore:
        await rate_limiter.acquire(target_domain)
        d_lock = await get_domain_lock(target_domain)

        async with d_lock:
            handler = registry.get_handler(fn_name)
            if not handler:
                result_content = f"Error: Tool '{fn_name}' is not registered."
            else:
                try:
                    result_content = await handler(args)
                except Exception as e:
                    result_content = f"Tool execution error in '{fn_name}': {str(e)}"

    return {
        "role": "tool",
        "tool_call_id": tool_call.id,
        "content": str(result_content)
    }
