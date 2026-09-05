import hashlib
import logging
from typing import Any, List, Optional, Tuple
from config import config

logger = logging.getLogger("WasmSandbox")

class WasmExecutionEngine:
    def __init__(self, fuel_budget: int = 50_000_000):
        self.fuel_budget = fuel_budget
        self._engine = None

    def _get_engine(self):
        if self._engine is None:
            from wasmtime import Config, Engine
            cfg = Config()
            cfg.consume_fuel = True
            self._engine = Engine(cfg)
        return self._engine

    def compile_wat(self, wat_code: str) -> Tuple[bool, Optional[Any], str]:
        try:
            from wasmtime import Module
            engine = self._get_engine()
            module = Module(engine, wat_code)
            return True, module, ""
        except Exception as e:
            return False, None, str(e)

    def score_benchmark_wasm(
        self,
        module: Any,
        sequences: List[List[float]],
        bin_size: float = 100.0
    ) -> Tuple[bool, float, str]:
        try:
            from wasmtime import Instance, Store, Trap, WasmtimeError
            engine = getattr(module, "engine", None) or self._get_engine()
            store = Store(engine)
            store.set_fuel(self.fuel_budget)

            instance = Instance(store, module, [])
            priority_fn = instance.exports(store)["priority"]

            total_bins = 0
            total_vol = 0.0

            for seq in sequences:
                bins: List[float] = []
                total_vol += sum(seq)

                for item in seq:
                    best_idx = -1
                    max_score = -float("inf")

                    for idx, cap in enumerate(bins):
                        if cap >= item:
                            try:
                                score = float(priority_fn(store, float(item), float(cap)))
                            except (Trap, WasmtimeError) as t:
                                return False, -1.0, f"WASM Trap (Fuel/Memory Limit Exhausted): {str(t)}"

                            if score > max_score:
                                max_score = score
                                best_idx = idx

                    if best_idx != -1:
                        bins[best_idx] -= item
                    else:
                        bins.append(bin_size - item)

                total_bins += len(bins)

            if total_bins == 0:
                return True, 0.0, ""

            efficiency = total_vol / (total_bins * bin_size)
            return True, max(0.0, min(1.0, efficiency)), ""

        except Exception as e:
            return False, -1.0, f"Execution Error: {str(e)}"

wasm_engine = WasmExecutionEngine(fuel_budget=config.WASM_FUEL_BUDGET)
