import aiosqlite
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Database")

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
"""

class Database:
    def __init__(self, db_path: str = "agent_state.db"):
        self.db_path = db_path

    async def init_db(self):
        """Initializes tables, triggers, and seeds the singleton state row."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(SCHEMA)
            await db.execute(
                "INSERT OR IGNORE INTO agent_state (id, iteration, status) VALUES (1, 0, 'INITIALIZING')"
            )
            await db.commit()
            logger.info("SQLite schema initialized with WAL mode & FTS5.")

    async def init_schema(self):
        """Initializes tables, triggers, and seeds the singleton state row (alias for init_db)."""
        await self.init_db()
