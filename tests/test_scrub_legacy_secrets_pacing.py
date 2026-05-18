"""Phase 13 / T3 / AC-13.9 — pacing, 429 backoff, and checkpoint-resume tests
for the scripts/scrub_legacy_secrets.py one-shot scrubber.

These tests run the `scrub()` entrypoint with mocked HTTP I/O so they exercise
the pacing/backoff/checkpoint deltas without touching real DefectDojo.
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
import time
import types
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest


# ---------------------------------------------------------------------------
# Module loader — scripts/ is not a package, so import by file path.
# ---------------------------------------------------------------------------

SCRIPT_PATH = (
    Path(__file__).resolve().parent.parent / "scripts" / "scrub_legacy_secrets.py"
)


def _load_scrub_module() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(
        "scrub_legacy_secrets_for_test", str(SCRIPT_PATH)
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def scrub_module():
    return _load_scrub_module()


# ---------------------------------------------------------------------------
# Test helpers — build a fake httpx.Client that satisfies the script's I/O.
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, status_code: int = 200, json_data=None):
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            req = httpx.Request("PATCH", "http://test.local/x")
            raise httpx.HTTPStatusError(
                f"status {self.status_code}",
                request=req,
                response=httpx.Response(self.status_code, request=req),
            )


def _make_findings(ids):
    """Build a list of fake DefectDojo finding dicts whose `description`
    contains an AWS-key-like secret so `_redact_field` always finds a match
    and the script tries to PATCH."""
    return [
        {
            "id": i,
            "title": f"finding-{i}",
            "description": "AKIAIOSFODNN7EXAMPLE leaked",  # AWS access key pattern
            "tags": [],
            "file_path": None,
            "component_name": None,
        }
        for i in ids
    ]


class _FakeClient:
    """A minimal context-manager + GET/PATCH stub that mirrors the surface of
    the httpx.Client the script holds."""

    def __init__(self, findings, *, patch_responses=None):
        self._findings = findings
        # patch_responses: optional callable(finding_id, payload) -> _FakeResponse
        self._patch_responses = patch_responses
        self.patch_calls: list[dict] = []
        self.patch_timestamps: list[float] = []
        self._yielded = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get(self, path, params=None):
        # /findings/ — paginate as one page then empty page.
        if path == "/findings/":
            if self._yielded:
                return _FakeResponse(200, {"results": [], "next": None})
            self._yielded = True
            return _FakeResponse(
                200, {"results": self._findings, "next": None, "count": len(self._findings)}
            )
        # /findings/{id}/notes/ — keep simple: no notes.
        if path.startswith("/findings/") and path.endswith("/notes/"):
            return _FakeResponse(200, [])
        return _FakeResponse(404, {})

    def patch(self, path, json=None):
        # Capture timestamp on entry (used by pacing test).
        self.patch_timestamps.append(time.monotonic())
        finding_id = None
        # path looks like "/findings/{id}/"
        if path.startswith("/findings/") and path.endswith("/"):
            try:
                finding_id = int(path.split("/")[2])
            except (IndexError, ValueError):
                finding_id = None
        self.patch_calls.append({"path": path, "finding_id": finding_id, "json": json})
        if self._patch_responses is not None:
            return self._patch_responses(finding_id, json)
        return _FakeResponse(200, {})


def _build_args(
    *,
    apply=True,
    rate_per_second=10.0,
    checkpoint=".scrub-checkpoint-test",
    checkpoint_interval=10,
    limit=None,
) -> argparse.Namespace:
    return argparse.Namespace(
        apply=apply,
        dry_run=False,
        limit=limit,
        rate_per_second=rate_per_second,
        checkpoint=checkpoint,
        checkpoint_interval=checkpoint_interval,
    )


def _patch_env_and_client(monkeypatch, scrub_module, fake_client):
    monkeypatch.setenv("DEFECTDOJO_URL", "https://dojo.test.local")
    monkeypatch.setenv("DEFECTDOJO_API_KEY_ADMIN", "fake-admin-key-1234567890")
    monkeypatch.setattr(
        scrub_module, "_build_client", lambda base_url, api_key: fake_client
    )


# ---------------------------------------------------------------------------
# (1) test_scrub_paces_requests
# ---------------------------------------------------------------------------


def test_scrub_paces_requests(monkeypatch, tmp_path, scrub_module):
    """With --rate-per-second=10 (interval = 0.1s), the PATCH calls must be
    spaced by approximately the pacing interval.

    Uses a fake time.sleep that records sleep durations (no real wall-clock
    delay) plus a fake time.monotonic that advances by the requested sleep.
    """
    findings = _make_findings([1, 2, 3])
    fake_client = _FakeClient(findings)
    _patch_env_and_client(monkeypatch, scrub_module, fake_client)

    sleep_durations: list[float] = []
    fake_now = [1000.0]

    def fake_sleep(s):
        sleep_durations.append(s)
        fake_now[0] += s

    def fake_monotonic():
        return fake_now[0]

    monkeypatch.setattr(scrub_module.time, "sleep", fake_sleep)
    monkeypatch.setattr(scrub_module.time, "monotonic", fake_monotonic)

    args = _build_args(
        rate_per_second=10.0,
        checkpoint=str(tmp_path / "ckpt"),
    )
    rc = scrub_module.scrub(args)
    assert rc == 0

    # 3 findings → 3 PATCHes → at least 2 pacing sleeps of ~0.1s each.
    pacing_sleeps = [s for s in sleep_durations if 0.05 <= s <= 0.2]
    assert len(pacing_sleeps) >= 2, (
        f"expected ≥2 pacing sleeps ≥0.05s; got durations={sleep_durations}"
    )


# ---------------------------------------------------------------------------
# (2) test_scrub_backs_off_on_429
# ---------------------------------------------------------------------------


def test_scrub_backs_off_on_429(monkeypatch, tmp_path, scrub_module):
    """When PATCH returns 429 twice then 200, the script must retry at least
    twice and the backoff between retries must roughly double (1s, then 2s)."""
    findings = _make_findings([42])
    call_count = {"n": 0}

    def patch_response(finding_id, json):
        call_count["n"] += 1
        if call_count["n"] <= 2:
            return _FakeResponse(429, {})
        return _FakeResponse(200, {})

    fake_client = _FakeClient(findings, patch_responses=patch_response)
    _patch_env_and_client(monkeypatch, scrub_module, fake_client)

    sleep_durations: list[float] = []

    def fake_sleep(s):
        sleep_durations.append(s)

    monkeypatch.setattr(scrub_module.time, "sleep", fake_sleep)

    args = _build_args(
        rate_per_second=100.0,  # near-zero pacing so we isolate backoff sleeps
        checkpoint=str(tmp_path / "ckpt"),
    )
    rc = scrub_module.scrub(args)
    assert rc == 0

    # The retry loop entered for 2 failed PATCHes plus 1 success.
    assert call_count["n"] == 3, f"expected 3 PATCH attempts, got {call_count['n']}"

    # Backoff sleeps live in sleep_durations alongside pacing sleeps. The
    # backoff schedule is 1.0s then 2.0s — both should appear.
    backoff_sleeps = [s for s in sleep_durations if s >= 0.9]
    assert len(backoff_sleeps) >= 2, (
        f"expected ≥2 backoff sleeps ≥0.9s; got durations={sleep_durations}"
    )
    # The second backoff (2.0s) must be ~2x the first (1.0s) — i.e. doubled.
    assert backoff_sleeps[1] >= backoff_sleeps[0] * 1.5, (
        f"backoff did not double: {backoff_sleeps[:2]}"
    )


# ---------------------------------------------------------------------------
# (3) test_scrub_resumes_from_checkpoint
# ---------------------------------------------------------------------------


def test_scrub_resumes_from_checkpoint(monkeypatch, tmp_path, scrub_module):
    """When the checkpoint file contains `5`, findings 1..5 are skipped and
    only 6 and 7 are PATCHed."""
    checkpoint_path = tmp_path / "ckpt"
    checkpoint_path.write_text("5")

    findings = _make_findings([1, 2, 3, 4, 5, 6, 7])
    fake_client = _FakeClient(findings)
    _patch_env_and_client(monkeypatch, scrub_module, fake_client)

    # Disable real sleeping so the test is fast.
    monkeypatch.setattr(scrub_module.time, "sleep", lambda s: None)

    args = _build_args(
        rate_per_second=1000.0,  # no pacing
        checkpoint=str(checkpoint_path),
        checkpoint_interval=1,
    )
    rc = scrub_module.scrub(args)
    assert rc == 0

    patched_ids = sorted(c["finding_id"] for c in fake_client.patch_calls)
    assert patched_ids == [6, 7], (
        f"expected PATCH only for findings 6 and 7; got {patched_ids}"
    )

    # Checkpoint should now reflect the latest processed id.
    assert checkpoint_path.read_text().strip() == "7"
