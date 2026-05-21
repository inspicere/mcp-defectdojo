import json
import logging
import os
import queue
import time
from unittest.mock import MagicMock, patch

import pytest

from mcp_defectdojo.audit_logging import (
    HTTPSLogHandler,
    IntegrityChainFormatter,
    SyslogForwardHandler,
    configure_logging,
)


def _make_record(msg="test message", level=logging.INFO):
    return logging.LogRecord(
        name="test", level=level, pathname="", lineno=0,
        msg=msg, args=(), exc_info=None,
    )


def _fast_close(handler):
    """PERF-08: close a forwarding handler without waiting the full 10s join.

    The forwarder workers are daemon threads that block in
    ``queue.get(timeout=flush_interval)``. The production ``close()`` calls
    ``_thread.join(timeout=10)``, which pays the full wait when
    ``flush_interval`` is long (e.g. 60s) and the worker is still blocked at
    shutdown. In tests we don't care about a clean thread join (daemon threads
    exit with the interpreter), so we set the shutdown flag, set a tiny join
    timeout, and proceed. Any work the worker has already done — including
    the assertions' targets like ``urlopen`` calls — remains observable.
    """
    handler._shutdown.set()
    handler._thread.join(timeout=0.1)
    try:
        super(type(handler), handler).close()
    except Exception:
        pass


def _wait_until(predicate, timeout=2.0, interval=0.005):
    """PERF-08: poll ``predicate`` until truthy or ``timeout`` elapses.

    Replaces fixed ``time.sleep(0.3)`` waits in forwarder tests — the worker
    thread typically processes a queued batch in microseconds, so polling at
    5ms intervals returns ~50× faster than the old fixed sleep without
    sacrificing determinism.

    Uses ``threading.Event.wait`` for the inter-poll delay (not ``time.sleep``)
    so that tests which monkey-patch ``time.sleep`` to a no-op don't turn this
    helper into a busy loop.
    """
    import threading as _t
    sentinel = _t.Event()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        sentinel.wait(timeout=interval)
    return predicate()


class TestSyslogForwardHandler:
    def _emit_and_drain(self, handler, record):
        handler.emit(record)
        handler.close()

    def test_udp_emit(self):
        with patch("mcp_defectdojo.audit_logging.socket.socket") as mock_cls:
            mock_sock = MagicMock()
            mock_cls.return_value = mock_sock

            handler = SyslogForwardHandler("localhost", 514, transport="udp")
            handler.setFormatter(logging.Formatter("%(message)s"))
            self._emit_and_drain(handler, _make_record())

            mock_sock.sendto.assert_called_once()
            data = mock_sock.sendto.call_args[0][0]
            assert b"mcp-defectdojo" in data
            assert b"test message" in data

    def test_tcp_emit_with_octet_framing(self):
        with patch("mcp_defectdojo.audit_logging.socket.socket") as mock_cls:
            mock_sock = MagicMock()
            mock_cls.return_value = mock_sock

            handler = SyslogForwardHandler("localhost", 514, transport="tcp")
            handler.setFormatter(logging.Formatter("%(message)s"))
            self._emit_and_drain(handler, _make_record())

            mock_sock.connect.assert_called_once_with(("localhost", 514))
            mock_sock.sendall.assert_called_once()
            raw = mock_sock.sendall.call_args[0][0]
            space_idx = raw.index(b" ")
            length = int(raw[:space_idx])
            assert length == len(raw) - space_idx - 1

    def test_tcp_tls_wraps_socket(self):
        with patch("mcp_defectdojo.audit_logging.socket.socket") as mock_cls, \
             patch("mcp_defectdojo.audit_logging.ssl.create_default_context") as mock_ssl:
            mock_sock = MagicMock()
            mock_cls.return_value = mock_sock
            mock_tls_sock = MagicMock()
            mock_ssl.return_value.wrap_socket.return_value = mock_tls_sock

            handler = SyslogForwardHandler("siem.example.com", 6514, transport="tcp+tls")
            handler.setFormatter(logging.Formatter("%(message)s"))
            self._emit_and_drain(handler, _make_record())

            mock_ssl.assert_called_once_with(cafile=None)
            mock_ssl.return_value.wrap_socket.assert_called_once_with(
                mock_sock, server_hostname="siem.example.com",
            )
            mock_tls_sock.sendall.assert_called_once()

    def test_custom_ca_cert(self):
        with patch("mcp_defectdojo.audit_logging.socket.socket"), \
             patch("mcp_defectdojo.audit_logging.ssl.create_default_context") as mock_ssl:
            mock_ssl.return_value.wrap_socket.return_value = MagicMock()

            handler = SyslogForwardHandler(
                "siem.example.com", 6514,
                transport="tcp+tls", ca_cert="/etc/ssl/custom-ca.pem",
            )
            handler.setFormatter(logging.Formatter("%(message)s"))
            self._emit_and_drain(handler, _make_record())

            mock_ssl.assert_called_once_with(cafile="/etc/ssl/custom-ca.pem")

    def test_reconnect_on_failure(self):
        with patch("mcp_defectdojo.audit_logging.socket.socket") as mock_cls:
            mock_sock = MagicMock()
            mock_cls.return_value = mock_sock
            mock_sock.sendall.side_effect = [OSError("reset"), None]

            handler = SyslogForwardHandler("localhost", 514, transport="tcp")
            handler.setFormatter(logging.Formatter("%(message)s"))
            self._emit_and_drain(handler, _make_record())

            assert mock_sock.connect.call_count == 2

    def test_rfc5424_priority_critical(self):
        with patch("mcp_defectdojo.audit_logging.socket.socket") as mock_cls:
            mock_sock = MagicMock()
            mock_cls.return_value = mock_sock

            handler = SyslogForwardHandler("localhost", 514, transport="udp")
            handler.setFormatter(logging.Formatter("%(message)s"))
            self._emit_and_drain(handler, _make_record(level=logging.CRITICAL))

            data = mock_sock.sendto.call_args[0][0]
            # LOCAL0 (16) * 8 + CRITICAL (2) = 130
            assert data.startswith(b"<130>1 ")

    def test_rfc5424_priority_error(self):
        with patch("mcp_defectdojo.audit_logging.socket.socket") as mock_cls:
            mock_sock = MagicMock()
            mock_cls.return_value = mock_sock

            handler = SyslogForwardHandler("localhost", 514, transport="udp")
            handler.setFormatter(logging.Formatter("%(message)s"))
            self._emit_and_drain(handler, _make_record(level=logging.ERROR))

            data = mock_sock.sendto.call_args[0][0]
            # LOCAL0 (16) * 8 + ERROR (3) = 131
            assert data.startswith(b"<131>1 ")

    def test_rfc5424_priority_warning(self):
        with patch("mcp_defectdojo.audit_logging.socket.socket") as mock_cls:
            mock_sock = MagicMock()
            mock_cls.return_value = mock_sock

            handler = SyslogForwardHandler("localhost", 514, transport="udp")
            handler.setFormatter(logging.Formatter("%(message)s"))
            self._emit_and_drain(handler, _make_record(level=logging.WARNING))

            data = mock_sock.sendto.call_args[0][0]
            # LOCAL0 (16) * 8 + WARNING (4) = 132
            assert data.startswith(b"<132>1 ")

    def test_close_closes_socket(self):
        handler = SyslogForwardHandler("localhost", 514, transport="tcp")
        mock_sock = MagicMock()
        handler._sock = mock_sock
        handler.close()
        mock_sock.close.assert_called_once()

    def test_emit_handles_total_failure(self):
        with patch("mcp_defectdojo.audit_logging.socket.socket") as mock_cls:
            mock_sock = MagicMock()
            mock_cls.return_value = mock_sock
            mock_sock.sendall.side_effect = OSError("permanent failure")
            mock_sock.connect.side_effect = [None, OSError("also down")]

            handler = SyslogForwardHandler("localhost", 514, transport="tcp")
            handler.setFormatter(logging.Formatter("%(message)s"))
            self._emit_and_drain(handler, _make_record())

    def test_queue_full_does_not_raise(self):
        handler = SyslogForwardHandler("localhost", 514, transport="udp")
        handler.setFormatter(logging.Formatter("%(message)s"))
        handler._queue = queue.Queue(maxsize=1)
        handler._queue.put("filler")
        handler.emit(_make_record("overflow"))
        handler.close()

    def test_circuit_breaker_trips_after_consecutive_failures(self, caplog, monkeypatch):
        # PERF-08: no-op real time.sleep so the test pays only the poll latency.
        monkeypatch.setattr("time.sleep", lambda _: None)
        with patch("mcp_defectdojo.audit_logging.socket.socket") as mock_cls:
            mock_sock = MagicMock()
            mock_cls.return_value = mock_sock
            mock_sock.sendall.side_effect = OSError("down")
            mock_sock.connect.side_effect = OSError("refused")

            handler = SyslogForwardHandler("localhost", 514, transport="tcp")
            handler.setFormatter(logging.Formatter("%(message)s"))
            with caplog.at_level(logging.ERROR, logger="mcp_defectdojo.audit_logging"):
                for _ in range(5):
                    handler.emit(_make_record())
                # Wait for the circuit-breaker event to land rather than sleeping
                # a fixed duration — the worker processes the failed sends in
                # microseconds once the queue is filled.
                _wait_until(lambda: any(
                    getattr(r, "event_type", None) == "audit_forward_failure"
                    and getattr(r, "forwarder", None) == "syslog"
                    for r in caplog.records
                ))
                _fast_close(handler)

            forward_failures = [
                r for r in caplog.records
                if getattr(r, "event_type", None) == "audit_forward_failure"
                and getattr(r, "forwarder", None) == "syslog"
            ]
            assert forward_failures, "Expected at least one audit_forward_failure event for syslog"

    def test_circuit_breaker_recovers(self, monkeypatch):
        # PERF-08: no-op real time.sleep so the test pays only the poll latency.
        monkeypatch.setattr("time.sleep", lambda _: None)
        with patch("mcp_defectdojo.audit_logging.socket.socket") as mock_cls:
            mock_sock = MagicMock()
            mock_cls.return_value = mock_sock

            handler = SyslogForwardHandler("localhost", 514, transport="udp")
            handler.setFormatter(logging.Formatter("%(message)s"))
            handler._consecutive_failures = 3
            handler._circuit_open_until = time.monotonic() - 1

            handler.emit(_make_record("recovered"))
            _wait_until(lambda: mock_sock.sendto.called)
            _fast_close(handler)

            mock_sock.sendto.assert_called()
            assert handler._consecutive_failures == 0


class TestHTTPSLogHandler:
    def test_batch_triggers_flush(self, monkeypatch):
        # PERF-08: no-op real time.sleep so the test pays only the poll latency.
        monkeypatch.setattr("time.sleep", lambda _: None)
        with patch("mcp_defectdojo.audit_logging.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp

            handler = HTTPSLogHandler(
                "https://siem.example.com/ingest",
                token="test-token", batch_size=2, flush_interval=60,
            )
            handler.setFormatter(logging.Formatter('{"msg": "%(message)s"}'))

            handler.emit(_make_record("event1"))
            handler.emit(_make_record("event2"))
            _wait_until(lambda: mock_urlopen.called)
            _fast_close(handler)

            assert mock_urlopen.called
            req = mock_urlopen.call_args[0][0]
            assert req.get_header("Authorization") == "Bearer test-token"
            assert req.get_header("Content-type") == "application/json"
            body = json.loads(req.data)
            assert len(body) == 2

    def test_interval_triggers_flush(self, monkeypatch):
        # PERF-08: no-op real time.sleep so the test pays only the poll latency.
        monkeypatch.setattr("time.sleep", lambda _: None)
        with patch("mcp_defectdojo.audit_logging.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp

            handler = HTTPSLogHandler(
                "https://siem.example.com/ingest",
                batch_size=100, flush_interval=0.2,
            )
            handler.setFormatter(logging.Formatter('{"msg": "%(message)s"}'))

            handler.emit(_make_record("lone event"))
            _wait_until(lambda: mock_urlopen.called)
            _fast_close(handler)

            assert mock_urlopen.called

    def test_flush_on_close(self):
        with patch("mcp_defectdojo.audit_logging.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp

            handler = HTTPSLogHandler(
                "https://siem.example.com/ingest",
                batch_size=100, flush_interval=60,
            )
            handler.setFormatter(logging.Formatter('{"msg": "%(message)s"}'))

            handler.emit(_make_record("final"))
            handler.close()

            assert mock_urlopen.called
            body = json.loads(mock_urlopen.call_args[0][0].data)
            assert len(body) == 1
            assert body[0]["msg"] == "final"

    def test_no_auth_header_without_token(self, monkeypatch):
        # PERF-08: no-op real time.sleep so the test pays only the poll latency.
        monkeypatch.setattr("time.sleep", lambda _: None)
        with patch("mcp_defectdojo.audit_logging.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp

            handler = HTTPSLogHandler(
                "https://siem.example.com/ingest",
                token=None, batch_size=1, flush_interval=0.1,
            )
            handler.setFormatter(logging.Formatter('{"msg": "%(message)s"}'))

            handler.emit(_make_record())
            _wait_until(lambda: mock_urlopen.called)
            _fast_close(handler)

            req = mock_urlopen.call_args[0][0]
            assert not req.has_header("Authorization")

    def test_queue_full_does_not_raise(self):
        handler = HTTPSLogHandler(
            "https://siem.example.com/ingest",
            batch_size=10, flush_interval=60,
        )
        handler._queue = queue.Queue(maxsize=1)
        handler.setFormatter(logging.Formatter('{"msg": "%(message)s"}'))
        handler._queue.put("filler")

        handler.emit(_make_record("overflow"))
        handler.close()

    def test_http_error_does_not_crash(self, caplog, monkeypatch):
        # PERF-08: no-op real time.sleep so the test pays only the poll latency.
        monkeypatch.setattr("time.sleep", lambda _: None)
        with patch("mcp_defectdojo.audit_logging.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = Exception("connection refused")

            handler = HTTPSLogHandler(
                "https://siem.example.com/ingest",
                batch_size=1, flush_interval=0.1,
            )
            handler.setFormatter(logging.Formatter('{"msg": "%(message)s"}'))

            with caplog.at_level(logging.ERROR, logger="mcp_defectdojo.audit_logging"):
                handler.emit(_make_record())
                _wait_until(lambda: any(
                    getattr(r, "event_type", None) == "audit_forward_failure"
                    and getattr(r, "forwarder", None) == "https"
                    for r in caplog.records
                ))
                _fast_close(handler)

            forward_failures = [
                r for r in caplog.records
                if getattr(r, "event_type", None) == "audit_forward_failure"
                and getattr(r, "forwarder", None) == "https"
            ]
            assert forward_failures, "Expected at least one audit_forward_failure event for https"


class TestForwarderFailureAuditEvents:
    """AUD-04 (AC-10.6, AC-10.7): forwarder delivery failures emit
    audit_forward_failure events through the root logger so file/stderr
    sinks record the failure even when the forwarder itself is down."""

    def test_syslog_circuit_open_emits_audit_event(self, caplog, capsys, monkeypatch):
        # PERF-08: no-op real time.sleep so the test pays only the poll latency.
        monkeypatch.setattr("time.sleep", lambda _: None)
        with patch("mcp_defectdojo.audit_logging.socket.socket") as mock_cls:
            mock_sock = MagicMock()
            mock_cls.return_value = mock_sock
            mock_sock.sendall.side_effect = OSError("permanent down")
            mock_sock.connect.side_effect = OSError("refused")

            handler = SyslogForwardHandler("siem.example.com", 6514, transport="tcp")
            handler.setFormatter(logging.Formatter("%(message)s"))

            with caplog.at_level(logging.ERROR, logger="mcp_defectdojo.audit_logging"):
                for _ in range(5):
                    handler.emit(_make_record())
                _wait_until(lambda: any(
                    getattr(r, "event_type", None) == "audit_forward_failure"
                    and getattr(r, "forwarder", None) == "syslog"
                    for r in caplog.records
                ))
                _fast_close(handler)

            captured = capsys.readouterr()
            assert "AUDIT-SYSLOG-CIRCUIT-OPEN" not in captured.err, (
                "Plain stderr print() must be replaced by structured logger.error()"
            )

            failure_events = [
                r for r in caplog.records
                if getattr(r, "event_type", None) == "audit_forward_failure"
                and getattr(r, "forwarder", None) == "syslog"
            ]
            assert failure_events, "Expected audit_forward_failure event with forwarder=syslog"
            evt = failure_events[0]
            assert evt.host == "siem.example.com"
            assert evt.port == 6514
            assert evt.consecutive_failures >= SyslogForwardHandler._CIRCUIT_BREAKER_THRESHOLD
            assert evt.levelname == "ERROR"

    def test_https_flush_failure_emits_audit_event(self, caplog, capsys):
        import urllib.error

        with patch("mcp_defectdojo.audit_logging.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = urllib.error.URLError("dest unreachable")

            handler = HTTPSLogHandler(
                "https://siem.example.com/ingest",
                batch_size=2, flush_interval=60,
            )
            handler.setFormatter(logging.Formatter('{"msg": "%(message)s"}'))

            with caplog.at_level(logging.ERROR, logger="mcp_defectdojo.audit_logging"):
                handler._flush(['{"msg": "a"}', '{"msg": "b"}'])

            captured = capsys.readouterr()
            assert "AUDIT-LOG-HTTPS-FORWARD-ERROR" not in captured.err, (
                "Plain stderr print() must be replaced by structured logger.error()"
            )

            failure_events = [
                r for r in caplog.records
                if getattr(r, "event_type", None) == "audit_forward_failure"
                and getattr(r, "forwarder", None) == "https"
            ]
            assert failure_events, "Expected audit_forward_failure event with forwarder=https"
            evt = failure_events[0]
            assert evt.url == "https://siem.example.com/ingest"
            assert evt.batch_size == 2
            assert evt.reason == "URLError"
            # PERF-08: avoid the 10s join — worker has nothing more to do.
            _fast_close(handler)


def _mock_handler():
    """Create a MagicMock that satisfies logging.Handler interface."""
    h = MagicMock()
    h.level = logging.NOTSET
    h.filters = []
    h.lock = MagicMock()
    return h


class TestConfigureLoggingForwarding:
    def test_syslog_tcp_from_env(self):
        env = {"AUDIT_LOG_SYSLOG": "tcp://syslog.example.com:514", "LOG_LEVEL": "INFO"}
        with patch.dict(os.environ, env, clear=False), \
             patch("mcp_defectdojo.audit_logging.SyslogForwardHandler") as mock_cls:
            mock_cls.return_value = _mock_handler()
            configure_logging()
            mock_cls.assert_called_once_with(
                "syslog.example.com", 514,
                transport="tcp", ca_cert=None,
            )

    def test_syslog_tls_default_port(self):
        env = {"AUDIT_LOG_SYSLOG": "tcp+tls://syslog.example.com", "LOG_LEVEL": "INFO"}
        with patch.dict(os.environ, env, clear=False), \
             patch("mcp_defectdojo.audit_logging.SyslogForwardHandler") as mock_cls:
            mock_cls.return_value = _mock_handler()
            configure_logging()
            mock_cls.assert_called_once_with(
                "syslog.example.com", 6514,
                transport="tcp+tls", ca_cert=None,
            )

    def test_syslog_bare_hostname_defaults_to_tls(self):
        env = {"AUDIT_LOG_SYSLOG": "syslog.example.com", "LOG_LEVEL": "INFO"}
        with patch.dict(os.environ, env, clear=False), \
             patch("mcp_defectdojo.audit_logging.SyslogForwardHandler") as mock_cls:
            mock_cls.return_value = _mock_handler()
            configure_logging()
            mock_cls.assert_called_once_with(
                "syslog.example.com", 6514,
                transport="tcp+tls", ca_cert=None,
            )

    def test_syslog_ca_cert_env(self):
        env = {
            "AUDIT_LOG_SYSLOG": "tcp+tls://syslog.example.com:6514",
            "AUDIT_LOG_SYSLOG_CA": "/tmp/test-ca.pem",
            "LOG_LEVEL": "INFO",
        }
        with patch.dict(os.environ, env, clear=False), \
             patch("mcp_defectdojo.audit_logging.SyslogForwardHandler") as mock_cls:
            mock_cls.return_value = _mock_handler()
            configure_logging()
            mock_cls.assert_called_once_with(
                "syslog.example.com", 6514,
                transport="tcp+tls", ca_cert="/tmp/test-ca.pem",
            )

    def test_https_from_env(self):
        env = {
            "AUDIT_LOG_HTTPS_URL": "https://siem.example.com/ingest",
            "AUDIT_LOG_HTTPS_TOKEN": "my-token",
            "AUDIT_LOG_HTTPS_BATCH_SIZE": "25",
            "AUDIT_LOG_HTTPS_FLUSH_SECS": "10",
            "LOG_LEVEL": "INFO",
        }
        with patch.dict(os.environ, env, clear=False), \
             patch("mcp_defectdojo.audit_logging.HTTPSLogHandler") as mock_cls:
            mock_cls.return_value = _mock_handler()
            configure_logging()
            mock_cls.assert_called_once_with(
                "https://siem.example.com/ingest",
                token="my-token", batch_size=25, flush_interval=10.0,
            )

    def test_https_defaults(self):
        env = {
            "AUDIT_LOG_HTTPS_URL": "https://siem.example.com/ingest",
            "LOG_LEVEL": "INFO",
        }
        with patch.dict(os.environ, env, clear=False), \
             patch("mcp_defectdojo.audit_logging.HTTPSLogHandler") as mock_cls:
            mock_cls.return_value = _mock_handler()
            configure_logging()
            mock_cls.assert_called_once_with(
                "https://siem.example.com/ingest",
                token=None, batch_size=10, flush_interval=5.0,
            )

    def test_no_forwarding_without_env(self):
        env = {"LOG_LEVEL": "INFO"}
        with patch.dict(os.environ, env, clear=False), \
             patch("mcp_defectdojo.audit_logging.SyslogForwardHandler") as mock_syslog, \
             patch("mcp_defectdojo.audit_logging.HTTPSLogHandler") as mock_https:
            for key in ("AUDIT_LOG_SYSLOG", "AUDIT_LOG_HTTPS_URL"):
                os.environ.pop(key, None)
            configure_logging()
            mock_syslog.assert_not_called()
            mock_https.assert_not_called()


class TestHTTPSTokenRedaction:
    def test_https_token_in_secret_vars(self):
        from mcp_defectdojo.audit_logging import RedactingFilter
        assert "AUDIT_LOG_HTTPS_TOKEN" in RedactingFilter._SECRET_ENV_VARS
