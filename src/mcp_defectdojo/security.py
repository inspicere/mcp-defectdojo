import asyncio
import re
import time
import unicodedata
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

# Cyrillic letters that visually match Latin lowercase — collapsed for the
# injection-detection pre-pass only. Operators should never see these
# collapsed in stored values; this is a one-way fold for regex matching.
_HOMOGLYPH_FOLD_TABLE = str.maketrans({
    "а": "a", "А": "A",   # U+0430 / U+0410
    "е": "e", "Е": "E",   # U+0435 / U+0415
    "о": "o", "О": "O",   # U+043E / U+041E
    "р": "p", "Р": "P",   # U+0440 / U+0420
    "с": "c", "С": "C",   # U+0441 / U+0421
    "у": "y", "У": "Y",   # U+0443 / U+0423
    "х": "x", "Х": "X",   # U+0445 / U+0425
    "і": "i", "І": "I",   # U+0456 / U+0406 (Ukrainian / Belarusian)
})

# Tag character allowlist (F-002 D1.4) — accept only the safe ASCII subset
# that DefectDojo handles well (alphanumerics, dot, underscore, colon, slash,
# hyphen, plus, space). Notably excludes parentheses, equals signs, commas,
# semicolons, quotes, and angle brackets — all of which appear in the
# function-call payloads observed in the red-team report.
# NOTE: T4 owns Unicode-category-based validation. This allowlist is the
# ASCII-only baseline; do not widen without coordinating with T4.
_TAG_ALLOWED_RE = re.compile(r"^[A-Za-z0-9._:/\-+ ]+$")


def validate_tag(tag: str) -> None:
    """Reject tag values containing control characters, commas, or chars
    outside the ASCII allowlist.

    Closes:
      F-002 D1.4 — function-call syntax in tags (parens, equals, colons with args)
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
    # Unicode-category branch (F-006 / F-017) — catches U+2028 LINE SEPARATOR,
    # U+2029 PARAGRAPH SEPARATOR, U+0085 NEXT LINE, and other Cc/Cf/Zl/Zp code
    # points whose bytes are not in the 0x00-0x1F/0x7F range and so slip past
    # _CONTROL_CHAR_RE. Runs BEFORE the ASCII allowlist so the exact AC-9.6
    # error string is emitted regardless of which category triggered it.
    for ch in tag:
        cat = unicodedata.category(ch)
        if cat[0] == "C" or cat in ("Zl", "Zp"):
            raise ToolError("tag must not contain control or line-break characters")
    if not _TAG_ALLOWED_RE.match(tag):
        raise ToolError(
            "tag contains disallowed characters — only letters, digits, and "
            "'._:/-+ ' are accepted (parentheses, equals signs, and similar "
            "function-call syntax are rejected)"
        )


# SB-001 — placeholder values that frequently appear in vulnerability prose
# but are NOT real secrets. Used to suppress false positives on the lowercase
# password=/passwd=/token=/secret= assignment patterns after the 12-char
# length floor (see DEC-026 in DECISIONS.md).
_PLACEHOLDER_VALUE_RE = re.compile(
    r"^(?:<[^>]*>"                              # <value>, <password>, <REDACTED>
    r"|YOUR_[A-Z_]+_HERE"                       # YOUR_PASSWORD_HERE
    r"|\*{3,}"                                  # ***, ****+
    r"|\[REDACTED(?::[^\]]+)?\]"                # [REDACTED] / [REDACTED:class]
    r"|\$\{[^}]+\}"                             # ${VAR}
    r"|placeholder|example|anything|something"   # common prose values
    r"|value|test|hunter2|password\d*)$",
    re.IGNORECASE,
)

# The four lowercase assignment pattern classes that go through the
# placeholder gate. Other _SECRET_PATTERNS entries match shapes that are
# unlikely to appear as placeholder text (random-alphanumeric, prefix-keyed
# tokens) so they bypass the gate.
_PLACEHOLDER_GATED_CLASSES = frozenset({
    "password_assignment",
    "passwd_assignment",
    "token_assignment",
    "secret_assignment",
})


def is_placeholder_value(value: str) -> bool:
    """Return True if `value` looks like a documentation/example placeholder
    rather than a real secret. Used by validate_no_secrets, the audit log
    RedactingFilter, and redact_response_text to suppress SB-001 false
    positives on vulnerability description prose.
    """
    return bool(value and _PLACEHOLDER_VALUE_RE.match(value))


# Patterns that look like embedded secrets. The list is intentionally
# conservative — false positives on user-supplied content are worse than the
# residual risk of a missed esoteric pattern. The redactor in audit_logging
# protects log output; this validator protects the stored fields.
#
# Schema is (redaction_class, compiled_pattern): the class string is exposed
# verbatim inside the `[REDACTED:<class>]` marker emitted by
# audit_logging.redact_response_text (F-016 read-side redaction). Keep class
# names lowercase snake_case so they tokenize cleanly in SIEM queries.
_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("aws_secret_assignment", re.compile(r"AWS_SECRET_ACCESS_KEY\s*=\s*\S+", re.IGNORECASE)),
    ("generic_api_key_assignment", re.compile(r"\b[A-Z][A-Z0-9_]*(?:API[_-]?KEY|SECRET|TOKEN|PASSWORD)\s*=\s*\S+", re.IGNORECASE)),
    # Lowercase key=value assignments — F-005 residual coverage (F-016).
    # Phase 11 tightening (DEC-026): require ≥12 non-whitespace chars as the
    # value. A second-stage `is_placeholder_value()` gate at every match site
    # suppresses fake-but-long placeholders like YOUR_PASSWORD_HERE. Together
    # these close SB-001 false positives on vulnerability prose
    # ("attacker supplies password=anything to bypass").
    ("password_assignment", re.compile(r"\bpassword\s*=\s*(\S{12,})", re.IGNORECASE)),
    ("passwd_assignment", re.compile(r"\bpasswd\s*=\s*(\S{12,})", re.IGNORECASE)),
    ("token_assignment", re.compile(r"\btoken\s*=\s*(\S{12,})", re.IGNORECASE)),
    ("secret_assignment", re.compile(r"\bsecret\s*=\s*(\S{12,})", re.IGNORECASE)),
    ("bearer_token", re.compile(r"\bBearer\s+[A-Za-z0-9._\-]+\b", re.IGNORECASE)),
    ("pem_private_key", re.compile(r"-----BEGIN (?:RSA |DSA |EC |OPENSSH |ENCRYPTED |)PRIVATE KEY-----")),
    # GitHub PATs — fine-grained (`github_pat_`), classic (`ghp_`), and the
    # specialized token families (`gho_` user OAuth, `ghu_` user-to-server,
    # `ghs_` server-to-server, `ghr_` refresh).
    ("github_pat", re.compile(r"\bghp_[A-Za-z0-9]{36,}\b")),
    ("github_oauth", re.compile(r"\bgho_[A-Za-z0-9]{36,}\b")),
    ("github_user_to_server", re.compile(r"\bghu_[A-Za-z0-9]{36,}\b")),
    ("github_server_to_server", re.compile(r"\bghs_[A-Za-z0-9]{36,}\b")),
    ("github_refresh", re.compile(r"\bghr_[A-Za-z0-9]{36,}\b")),
    ("gitlab_pat", re.compile(r"\bglpat-[A-Za-z0-9_\-]{20,}\b")),
    ("slack_token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    # Long base64-like blob adjacent to an auth/token/secret keyword — catches
    # `Authorization: <blob>`, `secret = <blob>`, etc. Intentionally narrow
    # (must follow the keyword) to avoid false-positives on legitimate hashes.
    ("base64_near_auth", re.compile(r"(?i)(?:auth|authorization|token|secret)[^A-Za-z0-9+/]+[A-Za-z0-9+/=]{40,}")),

    # SEC-02 — GitHub fine-grained PATs. Format: github_pat_<11-base62><71+>
    # of base62+_. The 82-char minimum total tail length avoids matching the
    # literal string "github_pat_test" used in docs / examples.
    ("github_pat_finegrained", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{82,}\b")),

    # SEC-03 — HashiCorp Vault. hvs.* = service tokens, hvb.* = batch
    # tokens, s.* = legacy root tokens (pre-1.10). 24+ chars after prefix.
    ("vault_token", re.compile(r"\b(?:hvs|hvb)\.[A-Za-z0-9_\-]{24,}\b")),
    ("vault_legacy_token", re.compile(r"\bs\.[A-Za-z0-9]{24,}\b")),

    # SEC-03 — Anthropic API keys: sk-ant-api03-<long>, sk-ant-<other>-<long>.
    ("anthropic_api_key", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{40,}\b")),

    # SEC-03 — OpenAI project-scoped keys (legacy sk- keys not included to
    # avoid collisions with Stripe sk_test_ formatting in docs snippets).
    ("openai_project_key", re.compile(r"\bsk-proj-[A-Za-z0-9_\-]{40,}\b")),

    # SEC-03 — Stripe live keys. Test-mode `sk_test_` keys excluded to
    # avoid false-positives on documentation snippets.
    ("stripe_live_key", re.compile(r"\b(?:sk|rk)_live_[A-Za-z0-9]{24,}\b")),

    # SEC-03 — Twilio Account SID (AC...) and API Key SID (SK...) — both
    # are 34 chars total (2-char prefix + 32 hex). Case-sensitive — Stripe
    # `sk_live_` is lowercase, Twilio `SK` is uppercase.
    ("twilio_account_sid", re.compile(r"\bAC[a-f0-9]{32}\b")),
    ("twilio_api_key_sid", re.compile(r"\bSK[a-f0-9]{32}\b")),

    # SEC-03 — SendGrid API keys: SG.<22+ chars>.<40+ chars>.
    ("sendgrid_api_key", re.compile(r"\bSG\.[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{40,}\b")),

    # SEC-03 — Explicit ed25519 / ECDSA PEM headers. Distinct class names
    # for SIEM clarity even though pem_private_key would also catch them.
    ("ed25519_private_key", re.compile(r"-----BEGIN ED25519 PRIVATE KEY-----")),
    ("ecdsa_private_key", re.compile(r"-----BEGIN ECDSA PRIVATE KEY-----")),
)


# --- F-002: Stored prompt injection detector ---
# These patterns detect instruction-like content planted in user-controlled
# fields (title, description, tags, notes) by an attacker holding write scope.
# The patterns are intentionally narrow — they target the exact attack vectors
# documented in F-002 D1.1–D1.4 reproductions, not generic "looks suspicious"
# heuristics. False positives on legitimate vulnerability descriptions would
# undermine the trust model far more than a missed esoteric variant would.

# Enumerated 24 MCP tool names — hardcoded here to detect function-call syntax
# planted in stored fields. Keep in sync with @mcp.tool decorators in server.py.
_KNOWN_TOOL_NAMES: frozenset[str] = frozenset({
    "health_check",
    "list_products", "get_product", "create_product",
    "list_product_types",
    "list_engagements", "get_engagement", "create_engagement",
    "list_tests", "get_test", "create_test",
    "list_test_types",
    "list_findings", "get_finding", "create_finding", "update_finding",
    "close_finding", "reopen_finding",
    "import_scan", "reimport_scan",
    "add_finding_note", "list_finding_notes",
    "add_finding_tags", "remove_finding_tags",
})

# Build a regex that matches a tool invocation for any known tool. Compiled
# once at import. Two surface forms are caught:
#   1. Plain function-call:  tool_name(args)         — `tool_name\s*\(`
#   2. Angle-bracket wrapper: <tool_name>(args)      — `<tool_name>\s*\(`
# Form (2) was a D1.3 verification gap discovered in Phase 9 / T6: the
# original detector matched only `name\s*\(`, which let `<create_product>(...)`
# through because the `>` between `name` and `(` broke the contiguity.
_TOOL_NAME_ALT = "|".join(re.escape(t) for t in _KNOWN_TOOL_NAMES)
_TOOL_CALL_RE = re.compile(
    r"(?:\b(?:" + _TOOL_NAME_ALT + r")\s*\(|"
    r"<\s*(?:" + _TOOL_NAME_ALT + r")\s*>\s*\()",
    re.IGNORECASE,
)

# "IGNORE PREVIOUS/PRIOR INSTRUCTIONS" — D1.1 vector.
_IGNORE_INSTRUCTIONS_RE = re.compile(
    r"\bIGNORE\s+(?:PREVIOUS|PRIOR|ALL|ABOVE)\s+INSTRUCTIONS\b",
    re.IGNORECASE,
)

# Authority-spoofing system markers — D1.2 vector.
_SYSTEM_MARKER_RE = re.compile(
    r"(?:^|[\s\W])SYSTEM\s*:|</?\s*system\s*>",
    re.IGNORECASE,
)

# D1.4 tag-style payload: tool_name:arg:value (also caught by the tag
# allowlist for actual tag fields, but title/description should also reject).
_TOOL_COLON_PAYLOAD_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(t) for t in _KNOWN_TOOL_NAMES) + r")\s*:\s*\S",
    re.IGNORECASE,
)


def _normalize_for_injection_check(value: str) -> str:
    """NFKC-normalize and strip Unicode formatting code points so
    prompt-injection regexes match laundered payloads.

    NFKC collapses fullwidth ASCII to ASCII and decomposes ligatures.
    The Cf-category strip removes zero-width spaces (U+200B/200C/200D),
    BOM (U+FEFF), and other invisible formatters. NFKC does NOT collapse
    Cyrillic а → Latin a (categorically distinct), so we additionally
    transliterate the known-confusable Cyrillic letters used in attacks.
    """
    normalized = unicodedata.normalize("NFKC", value)
    filtered = "".join(c for c in normalized if unicodedata.category(c) != "Cf")
    return filtered.translate(_HOMOGLYPH_FOLD_TABLE)


def validate_no_prompt_injection(value: str, field_name: str) -> None:
    """Reject values containing patterns recognized as stored prompt injection.

    Closes F-002 (D1.1 title, D1.2 description, D1.3 function-call syntax,
    D1.4 tag-encoded payload) by blocking the attack at the write boundary.

    Detected patterns (case-insensitive):
      - "IGNORE PREVIOUS/PRIOR INSTRUCTIONS"
      - "SYSTEM:" / "<system>" / "</system>" authority-spoofing markers
      - MCP function-call syntax for any registered tool: `tool_name(...)`
      - Tool-name:arg:value tag-encoded payloads

    Error messages never echo the offending input — only the field name and
    the category of pattern matched, so injection content does not propagate
    into client-side logs.
    """
    if not isinstance(value, str) or not value:
        return
    normalized = _normalize_for_injection_check(value)
    if _IGNORE_INSTRUCTIONS_RE.search(normalized):
        raise ToolError(
            f"{field_name} contains an instruction-override phrase "
            "(\"ignore previous instructions\"-style). Reword to describe the "
            "vulnerability without directing the reader to take actions."
        )
    if _SYSTEM_MARKER_RE.search(normalized):
        raise ToolError(
            f"{field_name} contains an authority-spoofing marker (\"SYSTEM:\" "
            "or <system> tag). Vulnerability content must not impersonate "
            "system instructions."
        )
    if _TOOL_CALL_RE.search(normalized):
        raise ToolError(
            f"{field_name} contains MCP function-call syntax. Tool invocations "
            "are not permitted in stored vulnerability fields."
        )
    if _TOOL_COLON_PAYLOAD_RE.search(normalized):
        raise ToolError(
            f"{field_name} contains a tool-name:argument-style payload. "
            "Stored fields must not encode tool invocations."
        )


def validate_no_secrets(value: str, field_name: str) -> None:
    """Reject values containing patterns that look like embedded secrets.

    Closes F-005 — embedded secrets in user-controlled fields (title, description,
    tags, note entries) were stored verbatim with no redaction.
    """
    if not isinstance(value, str):
        return
    for label, pattern in _SECRET_PATTERNS:
        m = pattern.search(value)
        if not m:
            continue
        if label in _PLACEHOLDER_GATED_CLASSES:
            captured = m.group(1) if m.lastindex else m.group(0)
            if is_placeholder_value(captured):
                continue
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
