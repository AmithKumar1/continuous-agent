import aiosqlite
import sqlite3
import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Dict, List, Optional
from config import config

logger = logging.getLogger("Database")

PRAGMAS = [
    "PRAGMA journal_mode = WAL;",        # Readers don't block writers; writers don't block readers
    "PRAGMA busy_timeout = 10000;",      # Wait up to 10s for locks to clear before raising OperationalError
    "PRAGMA synchronous = NORMAL;",      # Safe in WAL mode, avoids disk sync bottlenecks
    "PRAGMA cache_size = -64000;",       # 64 MB memory cache allocation
    "PRAGMA wal_autocheckpoint = 1000;", # Checkpoint WAL back to DB every 1,000 pages
    "PRAGMA foreign_keys = ON;",
]

async def configure_connection(conn: aiosqlite.Connection):
    """Applies concurrency and performance PRAGMAs to an active connection."""
    conn.row_factory = aiosqlite.Row
    for pragma in PRAGMAS:
        await conn.execute(pragma)

def configure_sync_connection(conn: sqlite3.Connection):
    """Applies concurrency PRAGMAs to synchronous connections (used by backups and migrations)."""
    conn.row_factory = sqlite3.Row
    for pragma in PRAGMAS:
        conn.execute(pragma)

@asynccontextmanager
async def get_db(db_path: Optional[str] = None) -> AsyncGenerator[aiosqlite.Connection, None]:
    """Async context manager providing a concurrency-hardened SQLite connection."""
    path = db_path or getattr(config, "DB_PATH", "agent_state.db")
    conn = await aiosqlite.connect(path, timeout=10.0)
    await configure_connection(conn)
    try:
        yield conn
    finally:
        await conn.close()

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;

-- 1. Domain Rate Limiting & Cooldowns
CREATE TABLE IF NOT EXISTS domain_cooldowns (
    domain TEXT PRIMARY KEY,
    paused_until REAL NOT NULL,
    tokens REAL NOT NULL,
    last_refill REAL NOT NULL,
    rate REAL NOT NULL,
    capacity REAL NOT NULL,
    updated_at REAL NOT NULL
);

-- 2. Global Agent Metadata (Singleton Row)
CREATE TABLE IF NOT EXISTS agent_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    iteration INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'RUNNING',
    last_heartbeat REAL NOT NULL DEFAULT (unixepoch('now', 'subsec'))
);

-- 3. Execution Cycle Logs
CREATE TABLE IF NOT EXISTS execution_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    iteration INTEGER NOT NULL,
    summary TEXT NOT NULL,
    tool_calls_count INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL DEFAULT (unixepoch('now', 'subsec'))
);
CREATE INDEX IF NOT EXISTS idx_logs_iteration ON execution_logs(iteration DESC);

-- 4. Structured Task Queue
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    description TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('PENDING', 'IN_PROGRESS', 'COMPLETED', 'FAILED')) DEFAULT 'PENDING',
    created_at REAL NOT NULL DEFAULT (unixepoch('now', 'subsec')),
    completed_at REAL
);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);

-- 5. Core Working Memory (Key-Value scratchpad injected into prompts)
CREATE TABLE IF NOT EXISTS core_memory (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at REAL NOT NULL DEFAULT (unixepoch('now', 'subsec'))
);

-- 6. Self-Evolving Heuristics & Learned Rules
CREATE TABLE IF NOT EXISTS learned_heuristics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    condition TEXT NOT NULL,
    actionable_lesson TEXT NOT NULL,
    times_applied INTEGER DEFAULT 1,
    created_at REAL NOT NULL DEFAULT (unixepoch('now', 'subsec'))
);
CREATE INDEX IF NOT EXISTS idx_heuristics_cat ON learned_heuristics(category);

-- 7. Compacted Episodic Snapshots
CREATE TABLE IF NOT EXISTS episodic_summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    start_iteration INTEGER NOT NULL,
    end_iteration INTEGER NOT NULL,
    dense_summary TEXT NOT NULL,
    created_at REAL NOT NULL DEFAULT (unixepoch('now', 'subsec'))
);

-- 8. FTS5 Virtual Table for Episodic Memory Search
CREATE VIRTUAL TABLE IF NOT EXISTS episodic_summaries_fts USING fts5(
    dense_summary,
    content='episodic_summaries',
    content_rowid='id',
    tokenize='porter unicode61 remove_diacritics 2'
);

-- Triggers to synchronize FTS5 with episodic_summaries
CREATE TRIGGER IF NOT EXISTS episodic_summaries_ai AFTER INSERT ON episodic_summaries BEGIN
    INSERT INTO episodic_summaries_fts (rowid, dense_summary)
    VALUES (new.id, new.dense_summary);
END;

CREATE TRIGGER IF NOT EXISTS episodic_summaries_ad AFTER DELETE ON episodic_summaries BEGIN
    INSERT INTO episodic_summaries_fts (episodic_summaries_fts, rowid, dense_summary)
    VALUES ('delete', old.id, old.dense_summary);
END;

CREATE TRIGGER IF NOT EXISTS episodic_summaries_au AFTER UPDATE ON episodic_summaries BEGIN
    INSERT INTO episodic_summaries_fts (episodic_summaries_fts, rowid, dense_summary)
    VALUES ('delete', old.id, old.dense_summary);
    INSERT INTO episodic_summaries_fts (rowid, dense_summary)
    VALUES (new.id, new.dense_summary);
END;

-- 9. Scheduled Periodic Tasks
CREATE TABLE IF NOT EXISTS scheduled_tasks (
    name TEXT PRIMARY KEY,
    cron_expr TEXT NOT NULL,
    target_url TEXT NOT NULL,
    last_run REAL,
    next_run REAL NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1
);

-- 10. Evolved Evolutionary Programs & Signatures
CREATE TABLE IF NOT EXISTS evolved_programs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signature TEXT UNIQUE,
    code TEXT,
    fitness REAL,
    generation INTEGER,
    char_length INTEGER,
    origin_island INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 11. NSGA-II Multi-Objective Evolved Heuristics
CREATE TABLE IF NOT EXISTS heuristics (
    id TEXT PRIMARY KEY,
    island_id INTEGER NOT NULL,
    generation INTEGER NOT NULL,
    code TEXT NOT NULL,
    fitness REAL,
    wasm_fuel INTEGER,
    phenotype_signature TEXT,
    pareto_rank INTEGER DEFAULT NULL,
    crowding_distance REAL DEFAULT NULL,
    verified BOOLEAN DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_heuristics_island_gen 
    ON heuristics(island_id, generation DESC);

CREATE INDEX IF NOT EXISTS idx_heuristics_pareto 
    ON heuristics(island_id, pareto_rank, crowding_distance DESC);

-- 12. Supervisor Policy Transitions & Mutation Beam Audit
CREATE TABLE IF NOT EXISTS supervisor_policy_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    island_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,          -- 'POLICY_TRANSITION' | 'BEAM_EVALUATION'
    entropy REAL NOT NULL,
    temperature REAL NOT NULL,
    top_p REAL NOT NULL,
    beam_width INTEGER NOT NULL,
    candidates_generated INTEGER,      -- Populated during BEAM_EVALUATION
    candidates_accepted INTEGER,       -- Count passing AST & verification checks
    details TEXT,                      -- JSON metadata (diffs, error reasons, parent IDs)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_audit_island_time 
    ON supervisor_policy_audit(island_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_audit_event_type 
    ON supervisor_policy_audit(event_type, created_at DESC);
"""

CREATE_TABLES_SQL = SCHEMA

async def apply_migrations(conn: aiosqlite.Connection):
    """Idempotently adds NSGA-II columns and supervisor_policy_audit table if upgrading an older database schema."""
    cursor = await conn.execute("PRAGMA table_info(heuristics);")
    existing_columns = {row["name"] for row in await cursor.fetchall()}

    if existing_columns:
        if "pareto_rank" not in existing_columns:
            await conn.execute("ALTER TABLE heuristics ADD COLUMN pareto_rank INTEGER DEFAULT NULL;")

        if "crowding_distance" not in existing_columns:
            await conn.execute("ALTER TABLE heuristics ADD COLUMN crowding_distance REAL DEFAULT NULL;")

        # Ensure composite index for Pareto-front lookups exists
        await conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_heuristics_pareto 
            ON heuristics(island_id, pareto_rank, crowding_distance DESC);
            """
        )

    # Ensure supervisor_policy_audit table and indexes exist
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS supervisor_policy_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            island_id INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            entropy REAL NOT NULL,
            temperature REAL NOT NULL,
            top_p REAL NOT NULL,
            beam_width INTEGER NOT NULL,
            candidates_generated INTEGER,
            candidates_accepted INTEGER,
            details TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_audit_island_time ON supervisor_policy_audit(island_id, created_at DESC);"
    )
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_audit_event_type ON supervisor_policy_audit(event_type, created_at DESC);"
    )
    await conn.commit()

class Database:
    def __init__(self, db_path: str = "agent_state.db"):
        self.db_path = db_path

    async def init_db(self):
        """Initializes tables, triggers, and seeds the singleton state row."""
        async with aiosqlite.connect(self.db_path, timeout=10.0) as db:
            await configure_connection(db)
            await db.executescript(SCHEMA)
            await apply_migrations(db)
            await db.execute(
                "INSERT OR IGNORE INTO agent_state (id, iteration, status) VALUES (1, 0, 'INITIALIZING')"
            )
            await db.commit()
            logger.info("SQLite schema initialized with WAL mode, FTS5 & NSGA-II columns.")

    async def init_schema(self):
        """Initializes tables, triggers, and seeds the singleton state row (alias for init_db)."""
        await self.init_db()

async def init_db(db_path: Optional[str] = None):
    """Initializes tables and executes schema migrations."""
    path = db_path or getattr(config, "DB_PATH", "agent_state.db")
    db = Database(path)
    await db.init_db()

