#!/usr/bin/env python3
import os
import sys
import gzip
import shutil
import sqlite3
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("DBBackup")

def perform_online_backup(
    source_db: Optional[Path] = None,
    backup_dir: Optional[Path] = None,
    max_retained: Optional[int] = None
):
    src = source_db or Path(os.getenv("DB_PATH", "agent_state.db"))
    dest_dir = backup_dir or Path(os.getenv("BACKUP_DIR", "backups"))
    retain = max_retained or int(os.getenv("MAX_BACKUPS_RETAINED", "14"))

    if not src.exists():
        logger.error(f"Source database '{src}' does not exist.")
        sys.exit(1)

    dest_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%fZ")
    raw_backup_path = dest_dir / f"agent_state_{timestamp}.db"
    gz_backup_path = dest_dir / f"agent_state_{timestamp}.db.gz"

    logger.info(f"Starting online hot backup from '{src}'...")

    try:
        # 1. Connect to source with high timeout
        source_conn = sqlite3.connect(str(src), timeout=30.0)
        dest_conn = sqlite3.connect(str(raw_backup_path))

        # 2. Perform non-blocking page-by-page backup
        # pages=250 copies in chunks, sleep=0.01 releases lock momentarily to writers
        with dest_conn:
            source_conn.backup(dest_conn, pages=250, sleep=0.01)

        dest_conn.close()
        source_conn.close()
        logger.info(f"Raw backup completed: {raw_backup_path}")

        # 3. Verify integrity of the backup file before compressing
        verify_conn = sqlite3.connect(str(raw_backup_path))
        cursor = verify_conn.cursor()
        cursor.execute("PRAGMA integrity_check;")
        result = cursor.fetchone()[0]
        verify_conn.close()

        if result != "ok":
            raise ValueError(f"Backup integrity check failed: {result}")
        logger.info("Backup integrity check passed (PRAGMA integrity_check = ok).")

        # 4. Gzip compress to save disk space
        logger.info(f"Compressing backup to '{gz_backup_path}'...")
        with open(raw_backup_path, "rb") as f_in:
            with gzip.open(gz_backup_path, "wb", compresslevel=6) as f_out:
                shutil.copyfileobj(f_in, f_out)

        # Remove uncompressed file
        raw_backup_path.unlink()
        logger.info(f"Compressed backup generated ({gz_backup_path.stat().st_size / 1024:.1f} KB).")

    except Exception as e:
        logger.error(f"Backup failed: {e}", exc_info=True)
        if raw_backup_path.exists():
            raw_backup_path.unlink()
        sys.exit(1)

    # 5. Rotate old backups (keep latest N)
    rotate_old_backups(dest_dir, retain)

def rotate_old_backups(backup_dir: Optional[Path] = None, max_retained: Optional[int] = None):
    dest_dir = backup_dir or Path(os.getenv("BACKUP_DIR", "backups"))
    retain = max_retained or int(os.getenv("MAX_BACKUPS_RETAINED", "14"))

    backups = sorted(dest_dir.glob("agent_state_*.db.gz"), key=lambda p: p.stat().st_mtime)
    excess = len(backups) - retain

    if excess > 0:
        logger.info(f"Pruning {excess} old backup(s) to maintain retention limit ({retain})...")
        for old_file in backups[:excess]:
            logger.info(f"Removing obsolete backup: {old_file.name}")
            old_file.unlink()

if __name__ == "__main__":
    perform_online_backup()
