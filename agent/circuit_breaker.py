import asyncio
import logging

logger = logging.getLogger("CircuitBreaker")

class APICircuitBreaker:
    def __init__(self, max_retries: int = 4, base_delay: float = 2.0, hourly_token_cap: int = 250_000):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.hourly_token_cap = hourly_token_cap
        self.tokens_used_this_hour = 0
        self._lock = asyncio.Lock()

    async def call_with_retry(self, api_func, *args, **kwargs):
        async with self._lock:
            if self.tokens_used_this_hour >= self.hourly_token_cap:
                raise RuntimeError(f"Hourly token budget exceeded ({self.tokens_used_this_hour} tokens). Throttling execution.")

        delay = self.base_delay
        for attempt in range(1, self.max_retries + 1):
            try:
                result = await api_func(*args, **kwargs)
                async with self._lock:
                    self.tokens_used_this_hour += kwargs.get("max_tokens", 400) + 300
                return result
            except Exception as e:
                err_str = str(e).lower()
                if ("429" in err_str or "rate_limit" in err_str) and attempt < self.max_retries:
                    logger.warning(f"Rate limited (attempt {attempt}/{self.max_retries}). Backing off {delay:.1f}s...")
                    await asyncio.sleep(delay)
                    delay *= 2.0
                else:
                    raise e
