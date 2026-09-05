import gzip
import os
import shutil
import sqlite3
import time
from pathlib import Path
import pytest

from scripts.restore_db import (
    get_latest_backup,
    verify_sqlite_integrity,
    archive_active_db,
    restore_database,
    confirm_restoration,
    dry_run_database,
)

def create_sample_sqlite_db(path: Path, table_name: str = "items", record_count: int = 5):
    """Utility to create a valid SQLite database with seeded records."""
    conn = sqlite3.connect(str(path))
    conn.execute(f"CREATE TABLE {table_name} (id INTEGER PRIMARY KEY, name TEXT);")
    for i in range(record_count):
        conn.execute(f"INSERT INTO {table_name} (name) VALUES (?);", (f"item_{i}",))
    conn.commit()
    conn.close()

def get_table_row_count(path: Path, table_name: str = "items") -> int:
    """Utility to count rows in a given table."""
    conn = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    cursor = conn.cursor()
    cursor.execute(f"SELECT COUNT(*) FROM {table_name};")
    count = cursor.fetchone()[0]
    conn.close()
    return count

# ---------------------------------------------------------------------------
# 1. Backup Discovery Tests
# ---------------------------------------------------------------------------

def test_get_latest_backup_ordering(tmp_path: Path):
    """Ensures get_latest_backup selects the newest file by modification timestamp."""
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()

    old_file = backup_dir / "agent_state_20260901_000000Z.db.gz"
    mid_file = backup_dir / "agent_state_20260902_000000Z.db"
    new_file = backup_dir / "agent_state_20260903_000000Z.db.gz"

    for f in [old_file, mid_file, new_file]:
        f.touch()

    # Explicitly set modification times
    now = time.time()
    os.utime(old_file, (now - 200, now - 200))
    os.utime(mid_file, (now - 100, now - 100))
    os.utime(new_file, (now, now))

    latest = get_latest_backup(backup_dir)
    assert latest is not None
    assert latest.name == new_file.name

def test_get_latest_backup_empty_dir(tmp_path: Path):
    """Returns None when no backup snapshots exist."""
    empty_dir = tmp_path / "empty_backups"
    empty_dir.mkdir()
    assert get_latest_backup(empty_dir) is None

def test_get_latest_backup_nonexistent_dir(tmp_path: Path):
    """Returns None when the backup directory does not exist."""
    missing_dir = tmp_path / "nonexistent"
    assert get_latest_backup(missing_dir) is None

# ---------------------------------------------------------------------------
# 2. SQLite Integrity Verification Tests
# ---------------------------------------------------------------------------

def test_verify_sqlite_integrity_valid_db(tmp_path: Path):
    """Confirms healthy database passes PRAGMA integrity_check."""
    db_file = tmp_path / "healthy.db"
    create_sample_sqlite_db(db_file, record_count=10)
    res = verify_sqlite_integrity(db_file)
    is_valid = res[0] if isinstance(res, (tuple, list)) else res
    assert is_valid is True

def test_verify_sqlite_integrity_corrupted_file(tmp_path: Path):
    """Rejects corrupted or non-SQLite files."""
    corrupt_file = tmp_path / "corrupt.db"
    corrupt_file.write_bytes(b"INVALID_SQLITE_HEADER_RANDOM_GARBAGE_BYTES_123456789")
    res = verify_sqlite_integrity(corrupt_file)
    is_valid = res[0] if isinstance(res, (tuple, list)) else res
    assert is_valid is False

# ---------------------------------------------------------------------------
# 3. Pre-Restore Archival Tests
# ---------------------------------------------------------------------------

def test_archive_active_db_creates_valid_compressed_archive(tmp_path: Path):
    """Verifies that active database is safely cloned and gzipped before restore."""
    active_db = tmp_path / "agent_state.db"
    backup_dir = tmp_path / "backups"
    create_sample_sqlite_db(active_db, record_count=8)

    archive_path = archive_active_db(active_db, backup_dir)
    assert archive_path is not None
    assert archive_path.exists()
    assert archive_path.suffix == ".gz"

    # Decompress archive and verify record integrity
    decompressed = tmp_path / "decompressed_archive.db"
    with gzip.open(archive_path, "rb") as f_in, open(decompressed, "wb") as f_out:
        shutil.copyfileobj(f_in, f_out)

    res = verify_sqlite_integrity(decompressed)
    assert (res[0] if isinstance(res, (tuple, list)) else res) is True
    assert get_table_row_count(decompressed) == 8

def test_archive_active_db_missing_target(tmp_path: Path):
    """Returns None when target active database does not exist."""
    missing_db = tmp_path / "nonexistent.db"
    backup_dir = tmp_path / "backups"
    assert archive_active_db(missing_db, backup_dir) is None

# ---------------------------------------------------------------------------
# 4. Decompression and Restoration Tests
# ---------------------------------------------------------------------------

def test_restore_database_from_gzip_with_wal_rearm(tmp_path: Path):
    """Validates full end-to-end restore from .db.gz, replacing old state and re-enabling WAL."""
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()

    # 1. Create source backup with 15 records
    raw_source = tmp_path / "source.db"
    create_sample_sqlite_db(raw_source, record_count=15)
    source_gz = backup_dir / "agent_state_20260905_120000Z.db.gz"

    with open(raw_source, "rb") as f_in, gzip.open(source_gz, "wb") as f_out:
        shutil.copyfileobj(f_in, f_out)

    # 2. Create target active DB with only 2 records
    target_db = tmp_path / "agent_state.db"
    create_sample_sqlite_db(target_db, record_count=2)

    # 3. Execute restore
    restore_database(
        source_path=source_gz,
        target_db=target_db,
        backup_dir=backup_dir,
        skip_archive=False
    )

    # 4. Assert restored state
    assert get_table_row_count(target_db) == 15

    # Check WAL pragmas were re-applied
    conn = sqlite3.connect(str(target_db))
    cursor = conn.cursor()
    cursor.execute("PRAGMA journal_mode;")
    mode = cursor.fetchone()[0]
    conn.close()
    assert mode.lower() == "wal"

    # Confirm pre-restore archive was generated
    archives = list(backup_dir.glob("pre_restore_archive_*.db.gz"))
    assert len(archives) == 1

# ---------------------------------------------------------------------------
# 5. Rollback and Fail-Safe Tests
# ---------------------------------------------------------------------------

def test_restore_aborts_without_modifying_target_on_corrupt_snapshot(tmp_path: Path):
    """Ensures a corrupted .db.gz is rejected during staging and leaves active DB untouched."""
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()

    # Active DB with critical state
    target_db = tmp_path / "agent_state.db"
    create_sample_sqlite_db(target_db, record_count=20)

    # Corrupt gzipped file
    corrupt_gz = backup_dir / "corrupted_snapshot.db.gz"
    with gzip.open(corrupt_gz, "wb") as f_out:
        f_out.write(b"NOT_A_VALID_SQLITE_FILE_CONTENT")

    # Attempt restore; expect sys.exit(1)
    with pytest.raises(SystemExit) as exc_info:
        restore_database(
            source_path=corrupt_gz,
            target_db=target_db,
            backup_dir=backup_dir
        )

    assert exc_info.value.code == 1

    # Active DB must be completely unaffected
    assert target_db.exists()
    res = verify_sqlite_integrity(target_db)
    assert (res[0] if isinstance(res, (tuple, list)) else res) is True
    assert get_table_row_count(target_db) == 20

def test_restore_rollback_when_post_swap_integrity_fails(tmp_path: Path, monkeypatch):
    """
    Tests rollback protection if an unexpected error or integrity failure occurs
    immediately after the target file is swapped.
    """
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()

    # Original target DB
    target_db = tmp_path / "agent_state.db"
    create_sample_sqlite_db(target_db, record_count=7)

    # Valid snapshot
    raw_source = tmp_path / "source.db"
    create_sample_sqlite_db(raw_source, record_count=12)
    source_gz = backup_dir / "agent_state_valid.db.gz"
    with open(raw_source, "rb") as f_in, gzip.open(source_gz, "wb") as f_out:
        shutil.copyfileobj(f_in, f_out)

    # Monkeypatch verify_sqlite_integrity:
    # 1st call (staging verification) -> returns True
    # 2nd call (post-swap verification on target_db) -> returns False to trigger emergency rollback
    calls = []
    original_verify = verify_sqlite_integrity

    def mock_verify(db_path: Path) -> bool:
        calls.append(db_path)
        if len(calls) == 1:
            return True  # Staging validation passes
        return False     # Post-swap validation fails

    monkeypatch.setattr("scripts.restore_db.verify_sqlite_integrity", mock_verify)

    # Attempt restore; should trigger rollback and exit
    with pytest.raises(SystemExit) as exc_info:
        restore_database(
            source_path=source_gz,
            target_db=target_db,
            backup_dir=backup_dir
        )

    assert exc_info.value.code == 1

    # Verify that target_db was rolled back to its original 7 rows
    monkeypatch.setattr("scripts.restore_db.verify_sqlite_integrity", original_verify)
    res = verify_sqlite_integrity(target_db)
    assert (res[0] if isinstance(res, (tuple, list)) else res) is True
    assert get_table_row_count(target_db) == 7

# ---------------------------------------------------------------------------
# 6. Interactive Confirmation & Flag Tests
# ---------------------------------------------------------------------------

def test_confirm_restoration_bypass_with_assume_yes(tmp_path: Path):
    """Verifies that assume_yes=True returns True without requiring stdin input."""
    dummy_source = tmp_path / "snapshot.db.gz"
    dummy_source.touch()
    dummy_target = tmp_path / "agent_state.db"

    assert confirm_restoration(dummy_source, dummy_target, assume_yes=True) is True

def test_confirm_restoration_interactive_inputs(tmp_path: Path, monkeypatch):
    """Validates affirmative ('y') and rejecting ('n') responses via simulated input."""
    dummy_source = tmp_path / "snapshot.db.gz"
    dummy_source.touch()
    dummy_target = tmp_path / "agent_state.db"

    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    # 1. Affirmative 'y'
    monkeypatch.setattr("builtins.input", lambda prompt="": "y")
    assert confirm_restoration(dummy_source, dummy_target, assume_yes=False) is True

    # 2. Rejection 'n'
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")
    assert confirm_restoration(dummy_source, dummy_target, assume_yes=False) is False

    # 3. Default empty response (Enter key)
    monkeypatch.setattr("builtins.input", lambda prompt="": "")
    assert confirm_restoration(dummy_source, dummy_target, assume_yes=False) is False

def test_confirm_restoration_non_tty_fails_safely(tmp_path: Path, monkeypatch):
    """Ensures non-interactive environments without --yes safely abort."""
    dummy_source = tmp_path / "snapshot.db.gz"
    dummy_source.touch()
    dummy_target = tmp_path / "agent_state.db"

    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert confirm_restoration(dummy_source, dummy_target, assume_yes=False) is False

# ---------------------------------------------------------------------------
# 7. Dry-Run Inspection Tests
# ---------------------------------------------------------------------------

def test_dry_run_leaves_active_db_untouched(tmp_path: Path):
    """Verifies that dry-run successfully inspects a snapshot without altering target_db."""
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()

    # Create active database with 5 records
    target_db = tmp_path / "agent_state.db"
    create_sample_sqlite_db(target_db, table_name="metrics", record_count=5)
    target_mtime_before = target_db.stat().st_mtime

    # Create snapshot database with 20 records
    source_db = tmp_path / "snapshot_source.db"
    create_sample_sqlite_db(source_db, table_name="metrics", record_count=20)
    source_gz = backup_dir / "agent_state_20260905_060000Z.db.gz"

    with open(source_db, "rb") as f_in, gzip.open(source_gz, "wb") as f_out:
        shutil.copyfileobj(f_in, f_out)

    # Execute dry run
    result = dry_run_database(source_path=source_gz, target_db=target_db)
    assert result is True

    # Confirm active database row count and mtime are completely untouched
    assert get_table_row_count(target_db, table_name="metrics") == 5
    assert target_db.stat().st_mtime == target_mtime_before

    # Confirm no pre-restore archives were created in backups/
    archives = list(backup_dir.glob("pre_restore_archive_*.db.gz"))
    assert len(archives) == 0

def test_dry_run_reports_failure_on_corrupted_snapshot(tmp_path: Path):
    """Verifies that dry-run returns False when evaluating a corrupt archive."""
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()

    corrupted_gz = backup_dir / "agent_state_corrupt.db.gz"
    with gzip.open(corrupted_gz, "wb") as f_out:
        f_out.write(b"CORRUPTED_NON_SQLITE_PAYLOAD_DATA")

    target_db = tmp_path / "agent_state.db"

    result = dry_run_database(source_path=corrupted_gz, target_db=target_db)
    assert result is False
    assert not target_db.exists()

# ---------------------------------------------------------------------------
# 8. CLI Arguments & Listing Tests
# ---------------------------------------------------------------------------

def test_restore_cli_list_flag(tmp_path: Path, monkeypatch, capsys):
    """Verifies that --list lists available snapshots with sizes and UTC timestamps."""
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    snap = backup_dir / "agent_state_20260905_120000Z.db.gz"
    snap.touch()

    test_args = ["restore_db.py", "--list", "-b", str(backup_dir)]
    monkeypatch.setattr("sys.argv", test_args)

    from scripts.restore_db import main
    main()

    captured = capsys.readouterr()
    assert "agent_state_20260905_120000Z.db.gz" in captured.out

def test_restore_cli_list_empty(tmp_path: Path, monkeypatch, capsys):
    """Verifies that --list reports when no snapshots exist."""
    empty_backup_dir = tmp_path / "empty_backups"
    empty_backup_dir.mkdir()

    test_args = ["restore_db.py", "--list", "-b", str(empty_backup_dir)]
    monkeypatch.setattr("sys.argv", test_args)

    from scripts.restore_db import main
    main()

    captured = capsys.readouterr()
    assert "No snapshots found" in captured.out
