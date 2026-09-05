import ast
import hashlib
import json
import logging
import sqlite3
import threading
from typing import Any, Dict, Optional, Tuple
from config import config
from agent.db import configure_sync_connection

logger = logging.getLogger("ASTCache")

def canonicalize_expr(code_str: str) -> str:
    """
    Normalizes variable names and structure to prevent re-evaluating duplicate heuristics.
    Maps:
      - bin_capacity, capacity, cap, c -> c
      - item, item_size, it, x, i -> i
      - gap, residual, rem, r, g -> g
    """
    try:
        tree = ast.parse(code_str.strip())
    except Exception:
        return code_str.strip()

    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            nid = node.id.lower()
            if nid in ("bin_capacity", "capacity", "cap", "c"):
                node.id = "c"
            elif nid in ("item", "item_size", "it", "x", "i"):
                node.id = "i"
            elif nid in ("gap", "residual", "rem", "r", "g"):
                node.id = "g"
        elif isinstance(node, ast.arg):
            nid = node.arg.lower()
            if nid in ("bin_capacity", "capacity", "cap", "c"):
                node.arg = "c"
            elif nid in ("item", "item_size", "it", "x", "i"):
                node.arg = "i"

    return ast.unparse(tree)

def compute_ast_hash(code_str: str) -> str:
    """Computes a SHA-256 fingerprint from the canonical AST."""
    canonical = canonicalize_expr(code_str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

class ASTEvaluationCache:
    """Thread-safe, dual-layer (memory + SQLite) cache for evaluated heuristics."""
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or config.DB_PATH
        self._memory_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self):
        try:
            with sqlite3.connect(self.db_path, timeout=10.0) as conn:
                configure_sync_connection(conn)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS ast_memo_cache (
                        ast_hash TEXT PRIMARY KEY,
                        canonical_code TEXT NOT NULL,
                        fitness REAL NOT NULL,
                        diagnostic_json TEXT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                conn.commit()
        except Exception as e:
            logger.warning(f"Could not initialize ast_memo_cache table: {e}")

    def get(self, code_str: str) -> Optional[Tuple[float, Dict[str, Any]]]:
        try:
            from agent.metrics import record_ast_lookup
        except Exception:
            record_ast_lookup = None

        ast_hash = compute_ast_hash(code_str)
        with self._lock:
            if ast_hash in self._memory_cache:
                if record_ast_lookup:
                    record_ast_lookup(is_hit=True)
                return self._memory_cache[ast_hash]

        # SQLite fallback
        try:
            with sqlite3.connect(self.db_path, timeout=10.0) as conn:
                configure_sync_connection(conn)
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT fitness, diagnostic_json FROM ast_memo_cache WHERE ast_hash = ?",
                    (ast_hash,)
                )
                row = cursor.fetchone()
                if row:
                    fitness = float(row[0])
                    diag = json.loads(row[1]) if row[1] else {}
                    with self._lock:
                        self._memory_cache[ast_hash] = (fitness, diag)
                    if record_ast_lookup:
                        record_ast_lookup(is_hit=True)
                    return fitness, diag
        except Exception as e:
            logger.debug(f"Cache read error: {e}")

        if record_ast_lookup:
            record_ast_lookup(is_hit=False)
        return None

    def put(self, code_str: str, fitness: float, diagnostic: Optional[Dict[str, Any]] = None):
        ast_hash = compute_ast_hash(code_str)
        canonical = canonicalize_expr(code_str)
        diag = diagnostic or {}
        diag_json = json.dumps(diag)

        with self._lock:
            self._memory_cache[ast_hash] = (fitness, diag)

        try:
            with sqlite3.connect(self.db_path, timeout=10.0) as conn:
                configure_sync_connection(conn)
                conn.execute("""
                    INSERT OR REPLACE INTO ast_memo_cache (ast_hash, canonical_code, fitness, diagnostic_json)
                    VALUES (?, ?, ?, ?)
                """, (ast_hash, canonical, fitness, diag_json))
                conn.commit()
        except Exception as e:
            logger.debug(f"Cache write error: {e}")

    def clear(self, clear_db: bool = False):
        with self._lock:
            self._memory_cache.clear()
        if clear_db:
            try:
                with sqlite3.connect(self.db_path, timeout=10.0) as conn:
                    configure_sync_connection(conn)
                    conn.execute("DELETE FROM ast_memo_cache")
                    conn.commit()
            except Exception as e:
                logger.debug(f"Cache clear DB error: {e}")

ast_cache = ASTEvaluationCache()
