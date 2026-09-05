import logging
from typing import Optional
import httpx
from config import config

logger = logging.getLogger("Notifications")

async def send_telegram_alert(message: str) -> bool:
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        logger.info(f"Telegram notification skipped (unset): {message[:80]}...")
        return False

    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": config.TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload)
            return resp.status_code == 200
    except Exception as e:
        logger.error(f"Failed to send Telegram alert: {e}")
        return False

async def send_telegram_document(pdf_buffer, filename: str = "security_report.pdf", caption: str = "") -> bool:
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        return False

    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendDocument"
    data = {"chat_id": config.TELEGRAM_CHAT_ID, "caption": caption}
    files = {"document": (filename, pdf_buffer, "application/pdf")}

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, data=data, files=files)
            return resp.status_code == 200
    except Exception as e:
        logger.error(f"Failed to send Telegram PDF: {e}")
        return False
