from __future__ import annotations
import ast
import asyncio
import logging
import re
from typing import Any, Dict, List, Optional
from openai import AsyncOpenAI
from config import config
from agent.prompt_strategies import PromptStrategy

logger = logging.getLogger("ExpressionMutator")

FUNCTION_HEADER = "def priority(item: float, bin_capacity: float) -> float:\n    return "

class ExpressionMutator:
    """
    Two-tier model router and expression-only AST diff mutator.
    Offloads 90% of routine mutations to local SLM (e.g. Ollama/vLLM)
    and prompts strictly for the mathematical return expression, cutting token burn by ~80%.
    """

    def __init__(self):
        # Tier 1: Local SLM for routine mutations
        self.local_client = AsyncOpenAI(
            base_url=config.LOCAL_MUTATION_BASE_URL,
            api_key="local-token"
        )
        self.local_model = config.LOCAL_MUTATION_MODEL

        # Tier 2: Frontier LLM for supervisor / restarts
        self.frontier_client = AsyncOpenAI(api_key=config.API_KEY) if config.API_KEY else None
        self.frontier_model = config.FRONTIER_SUPERVISOR_MODEL

    def extract_return_expr(self, full_code: str) -> str:
        """Extracts the return expression from a priority function."""
        try:
            tree = ast.parse(full_code)
            for node in ast.walk(tree):
                if isinstance(node, ast.Return) and node.value:
                    return ast.unparse(node.value)
        except Exception:
            pass
        # Fallback to regex
        match = re.search(r"return\s+(.+)", full_code)
        if match:
            return match.group(1).strip()
        return "100.0 / ((bin_capacity - item) + 0.001)"

    def build_prompt(
        self,
        current_code: str,
        strategy: Optional[PromptStrategy] = None,
        exemplars: Optional[List[Dict[str, Any]]] = None
    ) -> str:
        expr = self.extract_return_expr(current_code)
        directive = strategy.directive if strategy else "Mutate this return expression to improve packing efficiency."
        exemplar_lines = []
        if exemplars:
            for ex in exemplars[:2]:
                ex_code = ex.get("code", "")
                ex_fit = ex.get("fitness", 0.0)
                exemplar_lines.append(f"# Score {ex_fit:.4f}: return {self.extract_return_expr(ex_code)}")
        exemplar_block = ("\n" + "\n".join(exemplar_lines)) if exemplar_lines else ""
        return (
            f"# Candidate heuristic for online bin packing priority(item, bin_capacity):"
            f"{exemplar_block}\n"
            f"# Current: return {expr}\n"
            f"# Strategy: {directive}\n"
            f"# Output ONLY the single return expression on one line:\n"
            f"return "
        )

    def assemble_code(self, raw_expression: str) -> str:
        """Wraps an arithmetic expression into a formal priority function."""
        clean = raw_expression.strip()
        # Remove markdown code fences if present
        clean = re.sub(r"^```python\s*", "", clean)
        clean = re.sub(r"^```\s*", "", clean)
        clean = re.sub(r"```$", "", clean).strip()

        # If model returned a full function anyway, return it
        if "def priority" in clean:
            return clean

        # Strip leading 'return '
        if clean.startswith("return "):
            clean = clean[len("return "):].strip()

        # Take only the first non-empty line
        lines = [line.strip() for line in clean.splitlines() if line.strip()]
        expr_line = lines[0] if lines else "1.0"
        return f"{FUNCTION_HEADER}{expr_line}"

    async def mutate_expression(
        self,
        parent_code: str,
        strategy: Optional[PromptStrategy] = None,
        use_frontier: bool = False,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        exemplars: Optional[List[Dict[str, Any]]] = None,
        model_override: Optional[str] = None
    ) -> Optional[str]:
        prompt = self.build_prompt(parent_code, strategy, exemplars=exemplars)
        temp = temperature if temperature is not None else (strategy.temperature if strategy else 0.7)
        p_val = top_p if top_p is not None else (strategy.top_p if strategy else 0.9)

        # Choose client & model based on tier
        if use_frontier and self.frontier_client:
            client = self.frontier_client
            model = model_override or self.frontier_model
        else:
            client = self.local_client
            model = model_override or self.local_model

        try:
            resp = await client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=50,  # Expression-only requires very few tokens!
                temperature=temp,
                top_p=p_val,
                timeout=5.0
            )
            raw = resp.choices[0].message.content or ""
            return self.assemble_code(raw)
        except Exception as e:
            logger.debug(f"Mutation using {model} failed or offline: {e}")
            # If local SLM failed, try frontier if available and not already tried
            if not use_frontier and self.frontier_client:
                try:
                    resp = await self.frontier_client.chat.completions.create(
                        model=self.frontier_model,
                        messages=[{"role": "user", "content": prompt}],
                        max_tokens=50,
                        temperature=temp,
                        top_p=p_val,
                        timeout=5.0
                    )
                    raw = resp.choices[0].message.content or ""
                    return self.assemble_code(raw)
                except Exception as fe:
                    logger.debug(f"Frontier fallback also failed: {fe}")
            return None

    async def mutate_expression_beam(
        self,
        parent_code: str,
        exemplars: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.20,
        top_p: float = 0.70,
        beam_width: int = 1,
        strategy: Optional[PromptStrategy] = None,
        use_frontier: bool = False,
        model_override: Optional[str] = None
    ) -> List[str]:
        """
        Generates a beam of K candidate mutations in parallel using the given sampling policy.
        Filters duplicates and empty extracts.
        """
        prompt = self.build_prompt(parent_code, strategy, exemplars=exemplars)

        client = (
            self.frontier_client
            if (use_frontier and self.frontier_client)
            else self.local_client
        )
        model = model_override or (self.frontier_model if use_frontier else self.local_model)

        async def _sample_single() -> Optional[str]:
            try:
                resp = await client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=50,
                    temperature=temperature,
                    top_p=top_p,
                    timeout=5.0
                )
                raw = resp.choices[0].message.content or ""
                return self.assemble_code(raw)
            except Exception as e:
                logger.debug(f"Mutation using {model} failed: {e}")
                return None

        tasks = [_sample_single() for _ in range(max(1, beam_width))]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        candidates: List[str] = []
        seen = set()
        for res in results:
            if isinstance(res, str) and res and res not in seen:
                seen.add(res)
                candidates.append(res)

        return candidates

expression_mutator = ExpressionMutator()

async def mutate_expression(
    parent_code: str,
    exemplars: Optional[List[Dict[str, Any]]] = None,
    temperature: float = 0.3,
    top_p: float = 0.7,
    strategy: Optional[PromptStrategy] = None,
    use_frontier: bool = False,
    model_override: Optional[str] = None
) -> Optional[str]:
    return await expression_mutator.mutate_expression(
        parent_code=parent_code,
        strategy=strategy,
        use_frontier=use_frontier,
        temperature=temperature,
        top_p=top_p,
        exemplars=exemplars,
        model_override=model_override
    )

async def mutate_expression_beam(
    parent_code: str,
    exemplars: Optional[List[Dict[str, Any]]] = None,
    temperature: float = 0.20,
    top_p: float = 0.70,
    beam_width: int = 1,
    strategy: Optional[PromptStrategy] = None,
    use_frontier: bool = False,
    model_override: Optional[str] = None
) -> List[str]:
    return await expression_mutator.mutate_expression_beam(
        parent_code=parent_code,
        exemplars=exemplars,
        temperature=temperature,
        top_p=top_p,
        beam_width=beam_width,
        strategy=strategy,
        use_frontier=use_frontier,
        model_override=model_override
    )
