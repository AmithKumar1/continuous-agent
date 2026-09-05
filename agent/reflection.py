import json
import logging
from typing import Any, Dict, List
from openai import AsyncOpenAI
from config import config
from agent.cognitive_memory import CognitiveMemoryStore

logger = logging.getLogger("ReflectionEngine")

class ReflectionEngine:
    def __init__(self, memory: CognitiveMemoryStore):
        self.client = AsyncOpenAI(api_key=config.API_KEY) if config.API_KEY else None
        self.memory = memory

    async def evaluate_and_learn(
        self,
        context: Dict[str, Any],
        actions_taken: List[Dict[str, Any]],
        cycle_result: str
    ):
        if not actions_taken or not self.client:
            return

        reflection_prompt = f"""
Analyze the outcome of this execution cycle:
Context provided: {context}
Tool actions executed: {actions_taken}
Final summary: {cycle_result}

Critique the execution:
1. Did any tool call return errors, 403s, 429s, or empty/malformed results?
2. Did the agent take redundant or inefficient steps?
3. What general rule should be recorded to avoid this in the future?

Respond ONLY with valid JSON matching this schema:
{{
  "critique": "Brief assessment of execution quality",
  "has_new_lesson": true,
  "category": "TOOL_ERROR",
  "condition": "Specific trigger condition",
  "actionable_lesson": "Imperative rule to follow"
}}
"""
        try:
            response = await self.client.chat.completions.create(
                model="gpt-4o-mini",
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": "You are a self-critique engine. Identify mistakes and formulate permanent heuristic rules."},
                    {"role": "user", "content": reflection_prompt}
                ],
                max_tokens=300,
                temperature=0.1
            )

            data = json.loads(response.choices[0].message.content)
            if data.get("has_new_lesson") and data.get("actionable_lesson"):
                logger.warning(f"Self-Learning event triggered: {data['actionable_lesson']}")
                await self.memory.record_heuristic(
                    category=data.get("category", "STRATEGY"),
                    condition=data.get("condition", "General"),
                    actionable_lesson=data["actionable_lesson"]
                )
        except Exception as e:
            logger.error(f"Reflection step failed: {e}")
