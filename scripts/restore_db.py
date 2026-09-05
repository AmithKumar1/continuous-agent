#!/usr/bin/env python3
import argparse
import gzip
import logging
import os
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("DBRestore")

def get_latest_backup(backup_dir: Path) -> Optional[Path]:
    """Finds the most recent .db.gz or .db snapshot in the backup directory."""
    if not backup_dir.exists():
        return None
    backups = sorted(
        list(backup_dir.glob("agent_state_*.db.gz")) + list(backup_dir.glob("agent_state_*.db")),
        key=lambda p: p.stat().st_mtime,
        reverse=True
    )
    return backups[0] if backups else None

def _eval_integrity_res(res) -> Tuple[bool, str]:
    """Evaluates integrity check result whether returned as tuple or boolean."""
    if isinstance(res, (tuple, list)):
        is_valid = bool(res[0])
        msg = str(res[1]) if len(res) > 1 else ("ok" if is_valid else "integrity check failed")
        return is_valid, msg
    is_valid = bool(res)
    return is_valid, ("ok" if is_valid else "integrity check failed")

def verify_sqlite_integrity(db_path: Path) -> Tuple[bool, str, List[Tuple]]:
    """
    Runs PRAGMA integrity_check and foreign_key_check on a database file.
    Returns: (is_valid, integrity_message, list_of_fk_violations)
    """
    conn = None
    try:
        conn = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True, timeout=15.0)
        cursor = conn.cursor()

        cursor.execute("PRAGMA integrity_check;")
        integrity_res = cursor.fetchone()[0]

        cursor.execute("PRAGMA foreign_key_check;")
        fk_violations = cursor.fetchall()

        is_valid = (integrity_res == "ok") and (len(fk_violations) == 0)
        return is_valid, integrity_res, fk_violations
    except Exception as e:
        logger.error(f"Integrity verification crashed: {e}")
        return False, str(e), []
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass

def inspect_database_schema(db_path: Path) -> Dict[str, int]:
    """Inspects user tables and their record counts."""
    counts = {}
    conn = None
    try:
        conn = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True, timeout=15.0)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name;"
        )
        tables = [row[0] for row in cursor.fetchall()]
        for table in tables:
            cursor.execute(f'SELECT COUNT(*) FROM "{table}";')
            counts[table] = cursor.fetchone()[0]
    except Exception as e:
        logger.warning(f"Could not enumerate table statistics: {e}")
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass
    return counts

def archive_active_db(target_db: Path, backup_dir: Path) -> Optional[Path]:
    """Safely archives the live database and associated WAL/SHM files before replacement."""
    if not target_db.exists():
        logger.info(f"No existing database found at '{target_db}'. Skipping pre-restore archive.")
        return None

    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    archive_path = backup_dir / f"pre_restore_archive_{timestamp}.db.gz"

    logger.info(f"Archiving current database to '{archive_path}' before restore...")
    temp_archive = backup_dir / f"pre_restore_{timestamp}.tmp"

    src = None
    dst = None
    try:
        src = sqlite3.connect(str(target_db), timeout=15.0)
        dst = sqlite3.connect(str(temp_archive))
        with dst:
            src.backup(dst, pages=100, sleep=0.01)
        dst.close()
        src.close()
        src = None
        dst = None

        with open(temp_archive, "rb") as f_in, gzip.open(archive_path, "wb", compresslevel=6) as f_out:
            shutil.copyfileobj(f_in, f_out)

        temp_archive.unlink()
        logger.info("Pre-restore archive saved successfully.")
        return archive_path
    except Exception as e:
        logger.error(f"Failed to create pre-restore archive: {e}")
        if temp_archive.exists():
            temp_archive.unlink()
        raise
    finally:
        if dst:
            try:
                dst.close()
            except Exception:
                pass
        if src:
            try:
                src.close()
            except Exception:
                pass

def confirm_restoration(source_path: Path, target_db: Path, assume_yes: bool = False) -> bool:
    """Displays snapshot diagnostics and prompts for user confirmation."""
    if assume_yes:
        return True

    src_size_kb = source_path.stat().st_size / 1024
    src_mtime = datetime.fromtimestamp(
        source_path.stat().st_mtime, tz=timezone.utc
    ).strftime("%Y-%m-%d %H:%M:%S UTC")

    target_status = "Target does not exist (new database will be created)"
    if target_db.exists():
        tgt_size_kb = target_db.stat().st_size / 1024
        tgt_mtime = datetime.fromtimestamp(
            target_db.stat().st_mtime, tz=timezone.utc
        ).strftime("%Y-%m-%d %H:%M:%S UTC")
        target_status = f"Active ({tgt_size_kb:.1f} KB, Modified: {tgt_mtime})"

    print("\n" + "=" * 70)
    print("           CONTINUOUS AGENT: DATABASE RESTORATION PROMPT           ")
    print("=" * 70)
    print(f" Source Snapshot : {source_path.name}")
    print(f" Source Path     : {source_path.resolve()}")
    print(f" Snapshot Size   : {src_size_kb:.1f} KB")
    print(f" Timestamp (UTC) : {src_mtime}")
    print("-" * 70)
    print(f" Target Database : {target_db.resolve()}")
    print(f" Current State   : {target_status}")
    print("=" * 70)
    print(" WARNING: Restoring replaces active state with the chosen snapshot.")
    print(" (An automated pre-restore backup will be created in backups/)")
    print("=" * 70 + "\n")

    if not sys.stdin.isatty():
        logger.error("Terminal is non-interactive. Supply '--yes' or '-y' to confirm automatically.")
        return False

    try:
        reply = input("Proceed with database restore? [y/N]: ").strip().lower()
        return reply in ("y", "yes")
    except (KeyboardInterrupt, EOFError):
        print()
        return False

def dry_run_database(source_path: Path, target_db: Path) -> bool:
    """
    Executes a non-destructive dry-run:
    - Stages snapshot in a sandbox
    - Decompresses and validates PRAGMA integrity
    - Prints table census and row counts
    - Leaves active target database untouched
    """
    if not source_path.exists():
        logger.error(f"Snapshot file '{source_path}' does not exist.")
        return False

    src_size_kb = source_path.stat().st_size / 1024
    logger.info(f"[DRY RUN] Staging and inspecting snapshot: {source_path.name} ({src_size_kb:.1f} KB)")

    with tempfile.TemporaryDirectory() as tmpdir:
        staged_db = Path(tmpdir) / "staged_restore.db"

        # 1. Test Decompression
        try:
            if source_path.suffix == ".gz":
                with gzip.open(source_path, "rb") as f_in, open(staged_db, "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)
            else:
                shutil.copyfile(source_path, staged_db)
        except Exception as e:
            logger.error(f"[DRY RUN] Decompression failed: {e}")
            return False

        decompressed_size_kb = staged_db.stat().st_size / 1024

        # 2. Structural & PRAGMA Verification
        res = verify_sqlite_integrity(staged_db)
        is_valid, integrity_msg = _eval_integrity_res(res)
        fk_violations = list(res[2]) if isinstance(res, (tuple, list)) and len(res) > 2 else []
        if not is_valid:
            logger.error(f"[DRY RUN] Integrity check FAILED: {integrity_msg}")
            if fk_violations:
                logger.error(f"[DRY RUN] Foreign key violations: {len(fk_violations)}")
            return False

        # 3. Schema & Record Enumeration
        table_counts = inspect_database_schema(staged_db)

        # 4. Display Diagnostic Report
        print("\n" + "=" * 70)
        print("          CONTINUOUS AGENT: DRY-RUN RESTORATION REPORT            ")
        print("=" * 70)
        print(f" Source Snapshot      : {source_path.name}")
        print(f" Compression Type     : {'Gzip (.gz)' if source_path.suffix == '.gz' else 'Raw (.db)'}")
        print(f" Compressed Size      : {src_size_kb:.1f} KB")
        print(f" Decompressed Size    : {decompressed_size_kb:.1f} KB")
        print(f" PRAGMA Integrity     : {integrity_msg}")
        print(f" Foreign Key Check    : 0 violations")
        print("-" * 70)
        print(" Table Inventory & Record Counts:")
        if table_counts:
            for tbl, rows in table_counts.items():
                print(f"   • {tbl:<25} : {rows:>8} rows")
        else:
            print("   • (Database contains no user tables)")
        print("-" * 70)
        print(f" Target Database Path : {target_db.resolve()}")
        print(" STATUS               : VALID (Eligible for zero-downtime restore)")
        print(" MODIFICATION NOTICE  : No disk writes were made to the target database.")
        print("=" * 70 + "\n")

    return True

def restore_database(source_path: Path, target_db: Path, backup_dir: Path, skip_archive: bool = False):
    """Executes staged restoration with validation and rollback safety."""
    if not source_path.exists():
        logger.error(f"Backup file '{source_path}' does not exist.")
        sys.exit(1)

    logger.info(f"Target destination: '{target_db}'")
    logger.info(f"Source snapshot:    '{source_path}'")

    with tempfile.TemporaryDirectory() as tmpdir:
        staged_db = Path(tmpdir) / "staged_restore.db"

        if source_path.suffix == ".gz":
            logger.info("Decompressing gzip snapshot to staging area...")
            with gzip.open(source_path, "rb") as f_in, open(staged_db, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
        else:
            shutil.copyfile(source_path, staged_db)

        logger.info("Verifying staged snapshot integrity...")
        is_valid, integrity_msg = _eval_integrity_res(verify_sqlite_integrity(staged_db))
        if not is_valid:
            logger.error(f"Snapshot failed integrity check: {integrity_msg}. Aborting restore.")
            sys.exit(1)
        logger.info("Snapshot integrity verified: OK.")

        archive_path: Optional[Path] = None
        if not skip_archive:
            archive_path = archive_active_db(target_db, backup_dir)

        wal_file = target_db.with_name(f"{target_db.name}-wal")
        shm_file = target_db.with_name(f"{target_db.name}-shm")
        emergency_backup = target_db.with_suffix(".emergency_bak") if target_db.exists() else None

        try:
            if target_db.exists() and emergency_backup:
                shutil.copyfile(target_db, emergency_backup)

            if wal_file.exists():
                wal_file.unlink()
            if shm_file.exists():
                shm_file.unlink()

            shutil.copyfile(staged_db, target_db)

            is_target_valid, msg = _eval_integrity_res(verify_sqlite_integrity(target_db))
            if not is_target_valid:
                raise RuntimeError(f"Integrity check failed immediately after file swap: {msg}")

            conn = sqlite3.connect(str(target_db))
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA busy_timeout = 10000;")
            conn.execute("PRAGMA synchronous = NORMAL;")
            conn.close()

            if emergency_backup and emergency_backup.exists():
                emergency_backup.unlink()

            logger.info("✓ Database restored and re-armed with WAL mode successfully.")

        except Exception as err:
            logger.critical(f"Restoration swap failed: {err}. Initiating rollback...")
            if emergency_backup and emergency_backup.exists():
                shutil.copyfile(emergency_backup, target_db)
                emergency_backup.unlink()
                logger.info("Rolled back to original state using emergency snapshot.")
            elif archive_path and archive_path.exists():
                with gzip.open(archive_path, "rb") as f_in, open(target_db, "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)
                logger.info(f"Rolled back to pre-restore state from '{archive_path}'.")

            sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="Continuous Agent Safe Database Restore Utility")
    parser.add_argument(
        "-s", "--source",
        type=Path,
        help="Path to backup file (.db or .db.gz). Defaults to latest in backup directory."
    )
    parser.add_argument(
        "-t", "--target",
        type=Path,
        default=Path(os.getenv("DB_PATH", "agent_state.db")),
        help="Target database path (default: agent_state.db)"
    )
    parser.add_argument(
        "-b", "--backup-dir",
        type=Path,
        default=Path(os.getenv("BACKUP_DIR", "backups")),
        help="Directory containing backup archives (default: backups/)"
    )
    parser.add_argument(
        "-y", "--yes",
        action="store_true",
        help="Bypass interactive confirmation prompt (required for automated pipelines and CI/CD)."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and inspect the snapshot without modifying the live database."
    )
    parser.add_argument(
        "--skip-archive",
        action="store_true",
        help="Skip creating a pre-restore archive of the current active database."
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available backup snapshots and exit."
    )
    args = parser.parse_args()

    if args.list:
        backups = sorted(
            list(args.backup_dir.glob("agent_state_*.db.gz")) + list(args.backup_dir.glob("agent_state_*.db")),
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )
        if not backups:
            print(f"No snapshots found in '{args.backup_dir}'.")
            return
        print(f"Available Snapshots in '{args.backup_dir}':")
        for b in backups:
            size_kb = b.stat().st_size / 1024
            mtime = datetime.fromtimestamp(b.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            print(f"  • {b.name:<40} ({size_kb:>8.1f} KB) - {mtime}")
        return

    source = args.source
    if not source:
        source = get_latest_backup(args.backup_dir)
        if not source:
            logger.error(f"No backup files found in directory '{args.backup_dir}'.")
            sys.exit(1)
        logger.info(f"Auto-selected latest snapshot: '{source.name}'")

    # If dry-run requested, bypass prompt and run read-only validation
    if args.dry_run:
        success = dry_run_database(source_path=source, target_db=args.target)
        sys.exit(0 if success else 1)

    if not confirm_restoration(source_path=source, target_db=args.target, assume_yes=args.yes):
        logger.info("Restoration cancelled by user. Active database remains unchanged.")
        sys.exit(0)

    restore_database(
        source_path=source,
        target_db=args.target,
        backup_dir=args.backup_dir,
        skip_archive=args.skip_archive
    )

if __name__ == "__main__":
    main()
