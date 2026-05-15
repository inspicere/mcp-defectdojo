import asyncio
import re
import time
from collections import defaultdict, deque

from fastmcp.exceptions import ToolError

MAX_TITLE_LENGTH = 200
MAX_DESCRIPTION_LENGTH = 10000
MAX_NAME_LENGTH = 200


def validate_field_length(value: str, field_name: str, max_length: int) -> None:
    if len(value) > max_length:
        raise ToolError(
            f"{field_name} exceeds maximum length of {max_length} characters "
            f"(got {len(value)})"
        )


# Control characters (0x00-0x1F, 0x7F) — covers newlines, tabs, ANSI ESC (0x1B),
# and other terminal-injection vectors. Tag field is a frequent output target
# rendered in terminals and log viewers, so we reject all of these.
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]")


def validate_tag(tag: str) -> None:
    """Reject tag values containing control characters or commas.

    Closes:
      F-006 — newline characters accepted in tags
      F-009 — commas split a single tag into multiple server-side
      F-010 — ANSI escape sequences accepted in tag names
    """
    if not isinstance(tag, str):
        raise ToolError("tag must be a string")
    if not tag:
        raise ToolError("tag must not be empty")
    if _CONTROL_CHAR_RE.search(tag):
        raise ToolError("tag must not contain control characters (including newlines, tabs, ANSI escapes)")
    if "," in tag:
        raise ToolError("tag must not contain commas — DefectDojo splits comma-separated values into multiple tags")


# Patterns that look like embedded secrets. The list is intentionally
# conservative — false positives on user-supplied content are worse than the
# residual risk of a missed esoteric pattern. The redactor in audit_logging
# protects log output; this validator protects the stored fields.
_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("AWS access key id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("AWS secret key assignment", re.compile(r"AWS_SECRET_ACCESS_KEY\s*=\s*\S+", re.IGNORECASE)),
    ("generic API key assignment", re.compile(r"\b[A-Z][A-Z0-9_]*(?:API[_-]?KEY|SECRET|TOKEN|PASSWORD)\s*=\s*\S+", re.IGNORECASE)),
    ("bearer token", re.compile(r"\bBearer\s+[A-Za-z0-9_\-\.]{20,}\b")),
    ("PEM private key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |ENCRYPTED |)PRIVATE KEY-----")),
    ("GitHub personal access token", re.compile(r"\bghp_[A-Za-z0-9]{36,}\b")),
    ("Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
)


def validate_no_secrets(value: str, field_name: str) -> None:
    """Reject values containing patterns that look like embedded secrets.

    Closes F-005 — embedded secrets in user-controlled fields (title, description,
    tags, note entries) were stored verbatim with no redaction.
    """
    if not isinstance(value, str):
        return
    for label, pattern in _SECRET_PATTERNS:
        if pattern.search(value):
            raise ToolError(
                f"{field_name} appears to contain an embedded secret ({label}). "
                "Remove credentials before storing — secrets in vulnerability records "
                "are exposed to every reader."
            )


class MutationRateLimiter:
    def __init__(self, max_mutations: int = 60, window_seconds: int = 60):
        self.max_mutations = max_mutations
        self.window_seconds = window_seconds
        self._windows: dict[str, deque] = defaultdict(deque)
        self._lock = asyncio.Lock()
        self._last_cleanup = 0.0

    async def check(self, caller_id: str) -> None:
        async with self._lock:
            now = time.monotonic()

            if now - self._last_cleanup > self.window_seconds * 2:
                self._evict_stale(now)
                self._last_cleanup = now

            window = self._windows[caller_id]
            cutoff = now - self.window_seconds

            while window and window[0] < cutoff:
                window.popleft()

            if len(window) >= self.max_mutations:
                # Compute Retry-After: seconds until the oldest entry exits the
                # window. Ceil to a whole second and clamp to [1, window_seconds].
                retry_after = max(
                    1, min(self.window_seconds, int((window[0] + self.window_seconds - now)) + 1)
                )
                raise ToolError(
                    f"Rate limit exceeded: {self.max_mutations} mutations per "
                    f"{self.window_seconds}s. Retry-After: {retry_after}s."
                )
            window.append(now)

    def _evict_stale(self, now: float) -> None:
        cutoff = now - self.window_seconds
        stale = [k for k, v in self._windows.items() if not v or v[-1] < cutoff]
        for k in stale:
            del self._windows[k]
