import gzip
import os
import sqlite3
import pytest
from unittest.mock import patch
from agent.db import Database, configure_sync_connection, get_db
from scripts.backup_db import perform_online_backup

@pytest.mark.asyncio
async def test_sqlite_wal_pragmas(tmp_path):
    test_db = str(tmp_path / "test_pragmas.db")
    db_inst = Database(db_path=test_db)
    await db_inst.init_db()

    async with get_db(test_db) as conn:
        cursor = await conn.execute("PRAGMA journal_mode;")
        journal_mode = (await cursor.fetchone())[0]
        assert journal_mode.lower() == "wal"

        cursor = await conn.execute("PRAGMA busy_timeout;")
        busy_timeout = (await cursor.fetchone())[0]
        assert busy_timeout == 10000

        cursor = await conn.execute("PRAGMA synchronous;")
        synchronous = (await cursor.fetchone())[0]
        # NORMAL is 1
        assert synchronous == 1

def test_sync_sqlite_pragmas(tmp_path):
    test_db = str(tmp_path / "test_sync.db")
    with sqlite3.connect(test_db) as conn:
        configure_sync_connection(conn)
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode = WAL;")
        cursor.execute("PRAGMA busy_timeout;")
        assert cursor.fetchone()[0] == 10000

def test_online_hot_backup_and_rotation(tmp_path):
    source_db = tmp_path / "agent_state_live.db"
    backup_dir = tmp_path / "backups"

    # Initialize source DB with test data
    with sqlite3.connect(str(source_db)) as conn:
        configure_sync_connection(conn)
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("CREATE TABLE test_data (id INTEGER PRIMARY KEY, value TEXT);")
        conn.execute("INSERT INTO test_data (value) VALUES ('heuristic_champion');")
        conn.commit()

    with patch.dict(os.environ, {
        "DB_PATH": str(source_db),
        "BACKUP_DIR": str(backup_dir),
        "MAX_BACKUPS_RETAINED": "2"
    }):
        # Run backup 1
        perform_online_backup()
        backups = list(backup_dir.glob("agent_state_*.db.gz"))
        assert len(backups) == 1

        # Verify backup contents by decompressing in memory
        with gzip.open(backups[0], "rb") as gz:
            content = gz.read()
        recovered_db = tmp_path / "recovered.db"
        recovered_db.write_bytes(content)

        with sqlite3.connect(str(recovered_db)) as vconn:
            cur = vconn.cursor()
            cur.execute("PRAGMA integrity_check;")
            assert cur.fetchone()[0] == "ok"
            cur.execute("SELECT value FROM test_data;")
            assert cur.fetchone()[0] == "heuristic_champion"

        # Run backup 2 and 3 to test retention pruning (limit 2)
        import time
        time.sleep(0.05)
        perform_online_backup()
        time.sleep(0.05)
        perform_online_backup()

        backups_pruned = list(backup_dir.glob("agent_state_*.db.gz"))
        assert len(backups_pruned) == 2
