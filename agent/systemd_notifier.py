import os
import socket
import logging
from typing import Optional

logger = logging.getLogger("SystemdNotifier")

class SystemdNotifier:
    """Zero-dependency client for systemd's sd_notify protocol."""

    def __init__(self):
        self.socket_path: Optional[str] = os.environ.get("NOTIFY_SOCKET")
        watchdog_usec = os.environ.get("WATCHDOG_USEC")
        self.watchdog_interval_sec: Optional[float] = (
            float(watchdog_usec) / 1_000_000.0 if watchdog_usec else None
        )

    @property
    def is_enabled(self) -> bool:
        return bool(self.socket_path and hasattr(socket, "AF_UNIX"))

    def notify(self, state: str) -> bool:
        """Sends a raw state string to systemd's notification socket."""
        if not self.is_enabled or not self.socket_path:
            return False

        sock_addr = self.socket_path
        # Linux abstract namespace sockets start with '@'
        if sock_addr.startswith("@"):
            sock_addr = "\0" + sock_addr[1:]

        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
                sock.connect(sock_addr)
                sock.sendall(state.encode("utf-8"))
            return True
        except Exception as e:
            logger.warning(f"Failed to deliver sd_notify message '{state}': {e}")
            return False

    def notify_ready(self):
        """Notifies systemd that startup and initialization are complete."""
        self.notify("READY=1")

    def notify_watchdog(self):
        """Sends a keepalive heartbeat to reset the watchdog timer."""
        self.notify("WATCHDOG=1")

    def notify_stopping(self):
        """Informs systemd that the daemon is entering graceful termination."""
        self.notify("STOPPING=1")

    def notify_status(self, status_text: str):
        """Updates the status line displayed in `systemctl status`."""
        self.notify(f"STATUS={status_text}")

systemd_notifier = SystemdNotifier()
