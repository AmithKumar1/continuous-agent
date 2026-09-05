import os
from typing import Any, Dict, List, Optional
import httpx
from openai import AsyncOpenAI
from config import config

class FrontierModelRouter:
    def __init__(self):
        self.openai_client = AsyncOpenAI(api_key=config.API_KEY) if config.API_KEY else None
        self.anthropic_key = config.ANTHROPIC_API_KEY
        self.gemini_key = config.GEMINI_API_KEY

    async def generate(
        self,
        prompt: str,
        system_instruction: str = "You are an autonomous algorithmic discovery system.",
        model_preference: str = "openai",
        temperature: float = 0.7,
        max_tokens: int = 1200
    ) -> str:
        if model_preference == "anthropic" and self.anthropic_key:
            try:
                return await self._call_anthropic(prompt, system_instruction, temperature, max_tokens)
            except Exception:
                pass

        if model_preference == "gemini" and self.gemini_key:
            try:
                return await self._call_gemini(prompt, system_instruction, temperature, max_tokens)
            except Exception:
                pass

        return await self._call_openai(prompt, system_instruction, temperature, max_tokens)

    async def _call_openai(self, prompt: str, system: str, temp: float, max_tokens: int) -> str:
        if not self.openai_client:
            return "def priority(item, bin_capacity):\n    return bin_capacity - item"
        resp = await self.openai_client.chat.completions.create(
            model=config.MODEL_NAME,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt}
            ],
            temperature=temp,
            max_tokens=max_tokens
        )
        return resp.choices[0].message.content or ""

    async def _call_anthropic(self, prompt: str, system: str, temp: float, max_tokens: int) -> str:
        headers = {
            "x-api-key": self.anthropic_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }
        payload = {
            "model": "claude-3-5-sonnet-20241022",
            "max_tokens": max_tokens,
            "temperature": temp,
            "system": system,
            "messages": [{"role": "user", "content": prompt}]
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            res = await client.post("https://api.anthropic.com/v1/messages", json=payload, headers=headers)
            res.raise_for_status()
            data = res.json()
            return data["content"][0]["text"]

    async def _call_gemini(self, prompt: str, system: str, temp: float, max_tokens: int) -> str:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-pro:generateContent?key={self.gemini_key}"
        payload = {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": temp, "maxOutputTokens": max_tokens}
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            res = await client.post(url, json=payload)
            res.raise_for_status()
            data = res.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]

frontier_router = FrontierModelRouter()
