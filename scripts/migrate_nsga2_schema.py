#!/usr/bin/env python3
import argparse
import os
import shutil
import sqlite3
import sys
import time
from pathlib import Path
from agent.db import configure_sync_connection

def migrate_database(db_path: Path, skip_backup: bool = False):
    if not db_path.exists():
        print(f"Database file '{db_path}' not found. Nothing to migrate.")
        return

    # 1. Hot backup before migration
    if not skip_backup:
        backup_path = db_path.with_suffix(f".pre_migration_{int(time.time())}.bak")
        print(f"Creating pre-migration snapshot: {backup_path}")
        src = sqlite3.connect(str(db_path))
        dst = sqlite3.connect(str(backup_path))
        with dst:
            src.backup(dst)
        dst.close()
        src.close()

    # 2. Connect and configure concurrency
    conn = sqlite3.connect(str(db_path), timeout=30.0)
    configure_sync_connection(conn)
    cursor = conn.cursor()

    try:
        # Check existing columns
        cursor.execute("PRAGMA table_info(heuristics);")
        columns = {row["name"] for row in cursor.fetchall()}

        if "pareto_rank" not in columns:
            print("Adding column: heuristics.pareto_rank (INTEGER)...")
            cursor.execute("ALTER TABLE heuristics ADD COLUMN pareto_rank INTEGER DEFAULT NULL;")
        else:
            print("Column 'pareto_rank' already exists. Skipping.")

        if "crowding_distance" not in columns:
            print("Adding column: heuristics.crowding_distance (REAL)...")
            cursor.execute("ALTER TABLE heuristics ADD COLUMN crowding_distance REAL DEFAULT NULL;")
        else:
            print("Column 'crowding_distance' already exists. Skipping.")

        print("Ensuring composite Pareto index exists...")
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_heuristics_pareto 
            ON heuristics(island_id, pareto_rank, crowding_distance DESC);
            """
        )

        conn.commit()

        # 3. Verify integrity post-migration
        cursor.execute("PRAGMA integrity_check;")
        check = cursor.fetchone()[0]
        if check != "ok":
            raise RuntimeError(f"Integrity check failed post-migration: {check}")

        print("✓ Migration complete. Database integrity verified: OK.")

    except Exception as e:
        conn.rollback()
        print(f"ERROR: Migration failed: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        conn.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate SQLite heuristics table to support NSGA-II.")
    parser.add_argument(
        "--db-path",
        type=Path,
        default=Path(os.getenv("DB_PATH", "agent_state.db")),
        help="Path to target database"
    )
    parser.add_argument(
        "--skip-backup",
        action="store_true",
        help="Skip pre-migration database snapshot"
    )
    args = parser.parse_args()
    migrate_database(args.db_path, args.skip_backup)
