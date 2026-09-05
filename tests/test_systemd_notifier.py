import os
import pytest
from unittest.mock import patch, MagicMock
from agent.systemd_notifier import SystemdNotifier

def test_systemd_notifier_disabled_by_default():
    with patch.dict(os.environ, {}, clear=True):
        notifier = SystemdNotifier()
        assert not notifier.is_enabled
        assert notifier.notify("READY=1") is False
        assert notifier.watchdog_interval_sec is None

def test_systemd_notifier_watchdog_interval_parsing():
    with patch.dict(os.environ, {"NOTIFY_SOCKET": "/run/systemd/notify", "WATCHDOG_USEC": "20000000"}):
        notifier = SystemdNotifier()
        assert notifier.watchdog_interval_sec == pytest.approx(20.0)

import socket

def test_systemd_notifier_mock_delivery():
    with patch.dict(os.environ, {"NOTIFY_SOCKET": "/run/systemd/notify", "WATCHDOG_USEC": "10000000"}):
        with patch.object(socket, "AF_UNIX", 1, create=True):
            notifier = SystemdNotifier()

            with patch("socket.socket") as mock_sock_cls:
                mock_sock = MagicMock()
                mock_sock_cls.return_value.__enter__.return_value = mock_sock

                notifier.notify_ready()
                mock_sock.connect.assert_called_with("/run/systemd/notify")
                mock_sock.sendall.assert_called_with(b"READY=1")

                notifier.notify_watchdog()
                mock_sock.sendall.assert_called_with(b"WATCHDOG=1")

                notifier.notify_status("Engine healthy")
                mock_sock.sendall.assert_called_with(b"STATUS=Engine healthy")

                notifier.notify_stopping()
                mock_sock.sendall.assert_called_with(b"STOPPING=1")
