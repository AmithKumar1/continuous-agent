#!/usr/bin/env bash
set -e

ENDPOINT="http://127.0.0.1:8000/api/scheduler/status"
STATUS_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$ENDPOINT" || echo "000")

if [ "$STATUS_CODE" -ne 200 ]; then
    echo "[$(date -u)] Health check failed with code $STATUS_CODE. Restarting continuous-agent..." >> /var/log/continuous-agent/watchdog.log
    sudo systemctl restart continuous-agent
fi
