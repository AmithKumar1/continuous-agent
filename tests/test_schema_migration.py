import sqlite3
import pytest
from pathlib import Path
from scripts.migrate_nsga2_schema import migrate_database

def test_nsga2_schema_migration(tmp_path: Path):
    db_file = tmp_path / "legacy_agent_state.db"

    # 1. Build legacy schema without NSGA-II columns
    conn = sqlite3.connect(str(db_file))
    conn.execute(
        """
        CREATE TABLE heuristics (
            id TEXT PRIMARY KEY,
            island_id INTEGER NOT NULL,
            generation INTEGER NOT NULL,
            code TEXT NOT NULL,
            fitness REAL,
            wasm_fuel INTEGER,
            phenotype_signature TEXT
        );
        """
    )
    # Seed dummy record
    conn.execute(
        """
        INSERT INTO heuristics (id, island_id, generation, code, fitness, wasm_fuel, phenotype_signature)
        VALUES ('h_legacy', 0, 1, 'return 1.0', 0.92, 450, 'sig_0');
        """
    )
    conn.commit()
    conn.close()

    # 2. Run migration script
    migrate_database(db_path=db_file, skip_backup=False)

    # 3. Verify columns exist and legacy row remains intact
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("PRAGMA table_info(heuristics);")
    cols = {row["name"] for row in cursor.fetchall()}
    assert "pareto_rank" in cols
    assert "crowding_distance" in cols

    # Validate row preservation
    cursor.execute("SELECT * FROM heuristics WHERE id = 'h_legacy';")
    row = cursor.fetchone()
    assert row["fitness"] == 0.92
    assert row["pareto_rank"] is None
    assert row["crowding_distance"] is None

    # Verify index creation
    cursor.execute("PRAGMA index_list(heuristics);")
    indexes = {r["name"] for r in cursor.fetchall()}
    assert "idx_heuristics_pareto" in indexes

    conn.close()

def test_migration_idempotency(tmp_path: Path):
    """Running migration repeatedly on an already-upgraded DB causes no errors."""
    db_file = tmp_path / "idempotent.db"
    conn = sqlite3.connect(str(db_file))
    conn.execute("CREATE TABLE heuristics (id TEXT PRIMARY KEY, island_id INTEGER);")
    conn.commit()
    conn.close()

    # First migration
    migrate_database(db_path=db_file, skip_backup=True)
    # Second migration (should execute without exception)
    migrate_database(db_path=db_file, skip_backup=True)
