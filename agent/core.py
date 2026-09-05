import asyncio
import logging
from typing import Any, Dict, List, Optional
from openai import AsyncOpenAI
from config import config
from agent.db import Database
from agent.memory import SqliteMemoryStore
from agent.cooldown_store import SqliteCooldownStore
from agent.rate_limiter import DomainRateLimiter
from agent.cognitive_memory import CognitiveMemoryStore
from agent.reflection import ReflectionEngine
from agent.hybrid_search import HybridEpisodicRetriever
from agent.memory_tools import build_memory_tools, build_search_tools
from agent.schemas import UpdateCoreMemoryArgs, SearchMemoryArgs
from agent.tools import registry
from agent.executor import execute_single_tool_call
from agent.events import broker

logger = logging.getLogger("ContinuousAgent")

class ContinuousAgent:
    def __init__(self, db: Database):
        self.client = AsyncOpenAI(api_key=config.API_KEY) if config.API_KEY else None
        self.db = db
        self.memory = SqliteMemoryStore(db)
        self.cooldown_store = SqliteCooldownStore(db)
        self.rate_limiter = DomainRateLimiter(self.cooldown_store)
        self.cognitive_memory = CognitiveMemoryStore(db_path=db.db_path)
        self.reflector = ReflectionEngine(self.cognitive_memory)
        self.retriever = HybridEpisodicRetriever(db_path=db.db_path)
        self.registry = registry

        # Register cognitive memory tools
        self.registry.register(
            "update_core_memory",
            UpdateCoreMemoryArgs,
            build_memory_tools(self.cognitive_memory)
        )
        self.registry.register(
            "search_memory",
            SearchMemoryArgs,
            build_search_tools(self.retriever)
        )

        self.semaphore = asyncio.Semaphore(config.MAX_CONCURRENT_TOOL_CALLS)
        self.is_running = False
        self.is_paused = False
        self._pause_event = asyncio.Event()
        self._pause_event.set()
        self._trigger_event = asyncio.Event()
        self._step_lock = asyncio.Lock()
        self.failure_streak = 0
        self.max_tool_iterations = 5

    async def pause(self):
        self.is_paused = True
        self._pause_event.clear()
        logger.info("Agent execution paused.")
        await broker.publish("status", {"status": "PAUSED"})

    async def resume(self):
        self.is_paused = False
        self._pause_event.set()
        logger.info("Agent execution resumed.")
        await broker.publish("status", {"status": "RUNNING"})

    async def trigger_cycle(self) -> bool:
        if self._step_lock.locked():
            return False

        if self.is_paused:
            asyncio.create_task(self._run_isolated_step())
        else:
            self._trigger_event.set()
        return True

    async def _run_isolated_step(self):
        async with self._step_lock:
            try:
                await self.step()
            except Exception as e:
                logger.error(f"Manual step error: {e}")

    async def step(self):
        current_iteration = await self.memory.increment_iteration()
        status_label = "PAUSED" if self.is_paused else "RUNNING"

        await broker.publish("heartbeat", {
            "iteration": current_iteration,
            "status": status_label
        })

        cognitive_ctx = await self.cognitive_memory.get_prompt_context()
        rules_text = "\n".join([f"- [{h['condition']}]: {h['actionable_lesson']}" for h in cognitive_ctx["learned_rules"]])

        system_instruction = (
            "You are an autonomous discovery and monitoring agent with continuous neuro-symbolic learning.\n"
            "=== CORE SCRATCHPAD MEMORY ===\n"
            f"{cognitive_ctx['core_memory']}\n\n"
            "=== COMPACTED HISTORICAL CONTEXT ===\n"
            f"{cognitive_ctx['historical_macro_context']}\n\n"
            "=== LEARNED RULES & PAST HEURISTICS ===\n"
            f"{rules_text or 'No learned rules recorded yet.'}\n\n"
            "Evaluate pending goals, invoke tools as necessary, and record durable findings using update_core_memory."
        )

        messages = [
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": f"Cycle #{current_iteration}. Recent cycles: {cognitive_ctx['recent_immediate_cycles']}. Evaluate targets."}
        ]

        executed_actions = []

        if self.client:
            for turn in range(self.max_tool_iterations):
                response = await self.client.chat.completions.create(
                    model=config.MODEL_NAME,
                    messages=messages,
                    tools=self.registry.schemas,
                    tool_choice="auto",
                    max_tokens=600
                )
                response_message = response.choices[0].message
                messages.append(response_message)

                if not response_message.tool_calls:
                    break

                for tc in response_message.tool_calls:
                    executed_actions.append({
                        "tool": tc.function.name,
                        "arguments": tc.function.arguments
                    })

                tasks = [
                    execute_single_tool_call(tc, self.registry, self.semaphore, self.rate_limiter)
                    for tc in response_message.tool_calls
                ]
                tool_results = await asyncio.gather(*tasks)
                messages.extend(tool_results)

            final_summary = messages[-1].content or "Completed actions."
        else:
            final_summary = "Simulation heartbeat cycle executed (LLM API key offline)."

        await self.memory.record_cycle(
            iteration=current_iteration,
            summary=final_summary,
            tool_calls_count=len(executed_actions)
        )

        await broker.publish("log", {
            "iteration": current_iteration,
            "summary": final_summary,
            "tool_calls_count": len(executed_actions),
            "created_at": "Just now"
        })

        await self.reflector.evaluate_and_learn(
            context=cognitive_ctx,
            actions_taken=executed_actions,
            cycle_result=final_summary
        )

        await self.cognitive_memory.maybe_compact()

    async def run(self):
        self.is_running = True
        logger.info("Continuous agent heartbeat loop armed.")
        while self.is_running:
            await self._pause_event.wait()
            if not self.is_running:
                break

            try:
                async with self._step_lock:
                    await self.step()
                self.failure_streak = 0
            except Exception as e:
                self.failure_streak += 1
                logger.error(f"Error encountered (Streak {self.failure_streak}): {e}")
                if self.failure_streak >= config.MAX_CONSECUTIVE_FAILURES:
                    logger.critical("Circuit breaker tripped: pausing agent execution.")
                    await self.pause()
                    break

            try:
                await asyncio.wait_for(
                    self._trigger_event.wait(),
                    timeout=config.HEARTBEAT_INTERVAL_SECONDS
                )
                self._trigger_event.clear()
            except asyncio.TimeoutError:
                pass

    def stop(self):
        self.is_running = False
        self._pause_event.set()
        logger.info("Continuous agent stopped.")
