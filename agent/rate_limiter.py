import asyncio
import email.utils
import logging
import time
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple
from urllib.parse import urlparse
from agent.cooldown_store import SqliteCooldownStore

logger = logging.getLogger("RateLimiter")

def parse_retry_after(header_val: Optional[str], default_backoff: float = 30.0) -> float:
    if not header_val:
        return default_backoff
    val = header_val.strip()
    try:
        return max(1.0, float(val))
    except ValueError:
        pass
    try:
        target_dt = email.utils.parsedate_to_datetime(val)
        delta = (target_dt - datetime.now(timezone.utc)).total_seconds()
        return max(1.0, delta)
    except Exception:
        return default_backoff


class AsyncTokenBucket:
    def __init__(
        self,
        rate: float,
        capacity: float,
        tokens: Optional[float] = None,
        paused_until_epoch: float = 0.0,
        last_refill_epoch: Optional[float] = None
    ):
        self.rate = rate
        self.capacity = capacity
        now_mono = time.monotonic()
        now_epoch = time.time()

        if paused_until_epoch > now_epoch:
            remaining_pause = paused_until_epoch - now_epoch
            self.paused_until = now_mono + remaining_pause
            self.tokens = 0.0
            self.last_refill = self.paused_until
        else:
            self.paused_until = 0.0
            if last_refill_epoch:
                elapsed_offline = max(0.0, now_epoch - last_refill_epoch)
                initial_tokens = (tokens or 0.0) + (elapsed_offline * rate)
                self.tokens = min(capacity, initial_tokens)
            else:
                self.tokens = capacity if tokens is None else tokens
            self.last_refill = now_mono

        self._lock = asyncio.Lock()

    def pause(self, seconds: float) -> Tuple[float, float, float]:
        now_mono = time.monotonic()
        now_epoch = time.time()
        self.paused_until = max(self.paused_until, now_mono + seconds)
        self.tokens = 0.0
        self.last_refill = self.paused_until
        paused_until_epoch = now_epoch + seconds
        return paused_until_epoch, self.tokens, paused_until_epoch

    async def acquire(self):
        while True:
            async with self._lock:
                now = time.monotonic()
                if now < self.paused_until:
                    wait_time = self.paused_until - now
                else:
                    elapsed = now - self.last_refill
                    self.last_refill = now
                    self.tokens = min(self.capacity, self.tokens + (elapsed * self.rate))

                    if self.tokens >= 1.0:
                        self.tokens -= 1.0
                        return
                    wait_time = (1.0 - self.tokens) / self.rate

            await asyncio.sleep(wait_time)


class DomainRateLimiter:
    def __init__(
        self,
        db_store: SqliteCooldownStore,
        default_rate: float = 2.0,
        default_capacity: float = 4.0,
        domain_rules: Optional[Dict[str, Tuple[float, float]]] = None
    ):
        self.db = db_store
        self.default_rate = default_rate
        self.default_capacity = default_capacity
        self.domain_rules = domain_rules or {}
        self.buckets: Dict[str, AsyncTokenBucket] = {}
        self._registry_lock = asyncio.Lock()

    def extract_domain(self, url: str) -> str:
        try:
            netloc = urlparse(url).netloc.lower()
            return netloc.split(":")[0] if netloc else "global"
        except Exception:
            return "global"

    async def get_bucket(self, domain: str) -> AsyncTokenBucket:
        async with self._registry_lock:
            if domain in self.buckets:
                return self.buckets[domain]

            saved = await self.db.get_cooldown(domain)
            default_r, default_c = self.domain_rules.get(
                domain, (self.default_rate, self.default_capacity)
            )

            if saved:
                bucket = AsyncTokenBucket(
                    rate=saved["rate"],
                    capacity=saved["capacity"],
                    tokens=saved["tokens"],
                    paused_until_epoch=saved["paused_until"],
                    last_refill_epoch=saved["last_refill"]
                )
            else:
                bucket = AsyncTokenBucket(rate=default_r, capacity=default_c)

            self.buckets[domain] = bucket
            return bucket

    async def acquire(self, domain: str):
        bucket = await self.get_bucket(domain)
        await bucket.acquire()

    async def pause_domain(self, domain: str, retry_after_header: Optional[str] = None):
        backoff_sec = parse_retry_after(retry_after_header)
        bucket = await self.get_bucket(domain)
        paused_epoch, tokens, refill_epoch = bucket.pause(backoff_sec)

        await self.db.save_cooldown(
            domain=domain,
            paused_until=paused_epoch,
            tokens=tokens,
            last_refill=refill_epoch,
            rate=bucket.rate,
            capacity=bucket.capacity
        )
        logger.warning(
            f"Domain '{domain}' throttled (429). Cooldown persisted until epoch {paused_epoch:.1f} ({backoff_sec:.1f}s)."
        )
