"""Phase 9 / T3 / DEC-023 — caller_id sourced from authenticated token and
dual-bucket rate limiter (authenticated 60/min per token, open-access 10/min total).

These tests verify the F-004 root-cause fix: that an attacker cannot bypass the
rate limiter by sending requests with varied client-controlled `_meta.client_id`
values, and that all open-access traffic shares one aggressive bucket.
"""
import asyncio
import re

import pytest
from unittest.mock import MagicMock

from fastmcp.exceptions import ToolError

import mcp_defectdojo.server as server_module
from mcp_defectdojo.audit_logging import OPEN_ACCESS_CALLER_ID, resolve_identity
from mcp_defectdojo.security import MutationRateLimiter


# ---------------------------------------------------------------------------
# resolve_identity — trusted authenticated_caller_id preferred over meta
# ---------------------------------------------------------------------------


def test_resolve_identity_prefers_authenticated_token_over_meta(monkeypatch):
    """When a bearer token is present, authenticated_caller_id reflects token.client_id
    even if ctx.client_id (the client-controlled meta) says something different."""
    fake_token = MagicMock()
    fake_token.client_id = "claude"
    import fastmcp.server.dependencies as deps
    monkeypatch.setattr(deps, "get_access_token", lambda: fake_token)

    ctx = MagicMock()
    ctx.client_id = "spoofed-meta"
    authenticated, meta = resolve_identity(ctx)
    assert authenticated == "claude"  # trusted
    assert meta == "spoofed-meta"  # legacy meta path


def test_resolve_identity_falls_back_to_open_access_when_no_token(monkeypatch):
    """No auth provider configured → authenticated_caller_id == 'open-access'."""
    import fastmcp.server.dependencies as deps
    monkeypatch.setattr(deps, "get_access_token", lambda: None)
    ctx = MagicMock()
    ctx.client_id = "whatever"
    authenticated, meta = resolve_identity(ctx)
    assert authenticated == OPEN_ACCESS_CALLER_ID
    assert meta == "whatever"


def test_resolve_identity_falls_back_when_get_access_token_raises(monkeypatch):
    """If FastMCP can't resolve the token (e.g., test with no request scope),
    treat as open-access for the trusted path."""
    import fastmcp.server.dependencies as deps
    def _raise():
        raise RuntimeError("no http request")
    monkeypatch.setattr(deps, "get_access_token", _raise)
    ctx = MagicMock()
    ctx.client_id = "meta-id"
    authenticated, meta = resolve_identity(ctx)
    assert authenticated == OPEN_ACCESS_CALLER_ID
    assert meta == "meta-id"


def test_resolve_identity_no_ctx():
    """ctx=None still produces a valid (open-access, anonymous) tuple."""
    authenticated, meta = resolve_identity(None)
    assert authenticated == OPEN_ACCESS_CALLER_ID
    assert meta == "anonymous"


# ---------------------------------------------------------------------------
# Dual-bucket rate limiter — F-004 bypass prevention
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_open_access_burst_with_varied_meta_hits_shared_bucket(monkeypatch, patched_client=None):
    """The F-004 attack: 50 parallel calls with 50 different `_meta.client_id` values.
    Pre-fix this bypassed the limiter (each got its own bucket). Post-fix all 50
    hit the single open-access bucket (default 10/min) → 10 succeed, 40 rate-limited."""
    # Tighten the open-access limiter for a fast deterministic test.
    server_module._open_access_limiter = MutationRateLimiter(max_mutations=10, window_seconds=60)

    # Force open-access mode regardless of any auth env that may leak through.
    import fastmcp.server.dependencies as deps
    monkeypatch.setattr(deps, "get_access_token", lambda: None)

    successes = 0
    failures = 0
    for i in range(50):
        ctx = MagicMock()
        ctx.client_id = f"attacker-meta-{i}"  # rotated per call — the F-004 vector
        try:
            await server_module._check_mutation_rate_limit(ctx)
            successes += 1
        except ToolError:
            failures += 1

    assert successes == 10, f"open-access bucket should allow exactly 10, got {successes}"
    assert failures == 40, f"40 calls should be rejected, got {failures}"


@pytest.mark.asyncio
async def test_authenticated_burst_under_one_token_hits_per_token_bucket(monkeypatch):
    """Under one authenticated token, 70 parallel calls hit the per-token bucket
    (authenticated tier, default 60/min) → 60 succeed, 10 rate-limited."""
    monkeypatch.setattr(server_module, "_mutation_limiter", MutationRateLimiter(max_mutations=60, window_seconds=60))

    fake_token = MagicMock()
    fake_token.client_id = "claude"
    import fastmcp.server.dependencies as deps
    monkeypatch.setattr(deps, "get_access_token", lambda: fake_token)

    successes = 0
    failures = 0
    for i in range(70):
        ctx = MagicMock()
        # Even with rotated meta, all calls map to the authenticated bucket "claude":
        ctx.client_id = f"attacker-meta-{i}"
        try:
            await server_module._check_mutation_rate_limit(ctx)
            successes += 1
        except ToolError:
            failures += 1

    assert successes == 60
    assert failures == 10


@pytest.mark.asyncio
async def test_two_tokens_get_independent_buckets(monkeypatch):
    """Two distinct authenticated tokens get independent rate-limit windows."""
    monkeypatch.setattr(server_module, "_mutation_limiter", MutationRateLimiter(max_mutations=3, window_seconds=60))

    tokens = [MagicMock() for _ in range(2)]
    tokens[0].client_id = "scanner-a"
    tokens[1].client_id = "scanner-b"

    import fastmcp.server.dependencies as deps
    state = {"current": tokens[0]}
    monkeypatch.setattr(deps, "get_access_token", lambda: state["current"])

    ctx = MagicMock()
    ctx.client_id = "irrelevant-meta"

    # scanner-a fills its bucket
    for _ in range(3):
        await server_module._check_mutation_rate_limit(ctx)
    with pytest.raises(ToolError, match="Rate limit"):
        await server_module._check_mutation_rate_limit(ctx)

    # scanner-b should be unaffected
    state["current"] = tokens[1]
    for _ in range(3):
        await server_module._check_mutation_rate_limit(ctx)
    with pytest.raises(ToolError, match="Rate limit"):
        await server_module._check_mutation_rate_limit(ctx)


@pytest.mark.asyncio
async def test_rate_limit_error_includes_retry_after():
    """Rate-limit ToolError must include `Retry-After: <N>s` so callers can back off."""
    limiter = MutationRateLimiter(max_mutations=1, window_seconds=60)
    await limiter.check("caller")
    try:
        await limiter.check("caller")
        pytest.fail("expected ToolError")
    except ToolError as e:
        msg = str(e)
        assert "Rate limit exceeded" in msg
        m = re.search(r"Retry-After:\s*(\d+)s", msg)
        assert m is not None, f"Retry-After not found in: {msg}"
        retry_after = int(m.group(1))
        assert 1 <= retry_after <= 60, f"Retry-After out of range: {retry_after}"


# ---------------------------------------------------------------------------
# Concurrency — atomic check-and-append under asyncio.gather
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_open_access_burst_atomic_under_gather(monkeypatch):
    """Even under asyncio.gather (concurrent dispatch), the atomic limiter
    enforces exactly N successes for limit=N."""
    server_module._open_access_limiter = MutationRateLimiter(max_mutations=5, window_seconds=60)
    import fastmcp.server.dependencies as deps
    monkeypatch.setattr(deps, "get_access_token", lambda: None)

    async def _attempt(i):
        ctx = MagicMock()
        ctx.client_id = f"meta-{i}"
        try:
            await server_module._check_mutation_rate_limit(ctx)
            return True
        except ToolError:
            return False

    results = await asyncio.gather(*[_attempt(i) for i in range(20)])
    assert sum(results) == 5
    assert sum(1 for r in results if not r) == 15


@pytest.mark.asyncio
async def test_authenticated_tier_70_parallel_under_gather(monkeypatch):
    """AC-13.8 / Phase 9 SA-004 follow-up — literal "70 parallel under one
    authenticated token via asyncio.gather" reproduction.

    With the authenticated per-token bucket sized at 60/60s, 70 concurrent
    `_check_mutation_rate_limit` calls dispatched via `asyncio.gather` must
    split exactly 60 success + 10 ToolError-rate-limit. Confirms the
    MutationRateLimiter's asyncio.Lock-backed check-and-append is atomic
    under concurrent dispatch (not just sequential iteration).
    """
    monkeypatch.setattr(
        server_module,
        "_mutation_limiter",
        MutationRateLimiter(max_mutations=60, window_seconds=60),
    )

    fake_token = MagicMock()
    fake_token.client_id = "parallel-test-token"
    import fastmcp.server.dependencies as deps
    monkeypatch.setattr(deps, "get_access_token", lambda: fake_token)

    async def _attempt(i):
        ctx = MagicMock()
        # Rotated meta confirms the bucket key is the authenticated token,
        # not the client-controlled meta value.
        ctx.client_id = f"attacker-meta-{i}"
        await server_module._check_mutation_rate_limit(ctx)
        return True

    coros = [_attempt(i) for i in range(70)]
    results = await asyncio.gather(*coros, return_exceptions=True)

    successes = sum(1 for r in results if not isinstance(r, BaseException))
    failures = sum(1 for r in results if isinstance(r, ToolError))
    assert successes == 60, (
        f"expected 60 successes under 60/60s authenticated bucket; got {successes}"
    )
    assert failures == 10, (
        f"expected 10 ToolError rate-limit rejections; got {failures}"
    )
    # Confirm the failures really are rate-limit errors, not some other
    # ToolError class (e.g. validation).
    for r in results:
        if isinstance(r, ToolError):
            assert "rate limit" in str(r).lower(), (
                f"failure was not a rate-limit ToolError: {r!r}"
            )
