import aiosqlite
import json
from typing import Any, List
from config import config

DB_PATH = config.DB_PATH

async def init_evolution_tables():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS evolved_programs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signature TEXT UNIQUE,
                code TEXT,
                fitness REAL,
                generation INTEGER,
                char_length INTEGER,
                origin_island INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()

async def persist_program(program: Any):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO evolved_programs (signature, code, fitness, generation, char_length, origin_island)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(signature) DO UPDATE SET
                code = excluded.code,
                char_length = excluded.char_length
            WHERE excluded.char_length < evolved_programs.char_length
        """, (
            getattr(program, "signature", ""),
            getattr(program, "code", ""),
            getattr(program, "fitness", 0.0),
            getattr(program, "generation", 0),
            getattr(program, "char_length", 0),
            getattr(program, "origin_island", 0)
        ))
        await db.commit()
