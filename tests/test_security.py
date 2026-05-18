"""Phase 9 / T4 — F-005/F-016 + F-006/F-017 validator regression suite.

Two validator families live in security.py and both have hardened coverage in
Phase 9:

  - `validate_no_secrets` — write-side detector. F-005 / F-016 closes residual
    gaps around lowercase key=value assignments, all GitHub PAT prefix
    families, GitLab PATs, PEM headers without an "RSA " prefix, and long
    base64 blobs adjacent to auth/token/secret keywords. Synthetic fixtures
    only — these are deliberately invalid strings shaped to match the regex,
    never real credentials.

  - `validate_tag` — F-006 / F-017 adds a Unicode-category branch so
    U+2028 / U+2029 / U+0085 and other Cc/Cf/Zl/Zp code points are rejected
    BEFORE the ASCII allowlist runs. The exact error string is fixed by
    AC-9.6 and asserted explicitly.
"""
import pytest

from fastmcp.exceptions import ToolError

from mcp_defectdojo.security import validate_no_secrets, validate_tag


# ---------------------------------------------------------------------------
# validate_no_secrets — extended pattern coverage (F-005 / F-016)
# ---------------------------------------------------------------------------
#
# Each fixture is a synthetic string that matches the regex but is not a real
# credential. Where a class requires entropy or specific characters, the
# fixture clearly labels itself "FAKE" / "SYNTHETIC" so a grep of the test
# suite does not return false-positive "leaked secret" hits.


def test_validate_no_secrets_password_pattern():
    with pytest.raises(ToolError, match="password_assignment"):
        validate_no_secrets("config: password=hunter2-synthetic", "description")


def test_validate_no_secrets_passwd_pattern():
    with pytest.raises(ToolError, match="passwd_assignment"):
        validate_no_secrets("passwd=correcthorsebatterystaple-FAKE", "description")


def test_validate_no_secrets_token_pattern():
    with pytest.raises(ToolError, match="token_assignment"):
        validate_no_secrets("token=ABCDEFGHIJKLMNOPQRST-synthetic", "description")


def test_validate_no_secrets_secret_pattern():
    with pytest.raises(ToolError, match="secret_assignment"):
        validate_no_secrets("secret=SYNTHETIC_VALUE_NOT_A_REAL_KEY", "description")


def test_validate_no_secrets_github_pat_gho():
    with pytest.raises(ToolError, match="github_oauth"):
        validate_no_secrets(
            "config gho_FAKETESTTOKENFORREGEXMATCH0123456789xx end",
            "description",
        )


def test_validate_no_secrets_github_pat_ghu():
    with pytest.raises(ToolError, match="github_user_to_server"):
        validate_no_secrets(
            "ghu_FAKETESTTOKENFORREGEXMATCH0123456789xx",
            "description",
        )


def test_validate_no_secrets_github_pat_ghs():
    with pytest.raises(ToolError, match="github_server_to_server"):
        validate_no_secrets(
            "ghs_FAKETESTTOKENFORREGEXMATCH0123456789xx",
            "description",
        )


def test_validate_no_secrets_github_pat_ghr():
    with pytest.raises(ToolError, match="github_refresh"):
        validate_no_secrets(
            "ghr_FAKETESTTOKENFORREGEXMATCH0123456789xx",
            "description",
        )


def test_validate_no_secrets_gitlab_pat():
    with pytest.raises(ToolError, match="gitlab_pat"):
        validate_no_secrets(
            "glpat-FAKE_TEST_TOKEN_FOR_REGEX_MATCH_ONLY_xx",
            "description",
        )


def test_validate_no_secrets_pem_header():
    with pytest.raises(ToolError, match="pem_private_key"):
        validate_no_secrets("-----BEGIN OPENSSH PRIVATE KEY-----", "description")


def test_validate_no_secrets_pem_header_unprefixed():
    """The non-RSA/EC/OPENSSH/DSA bare form must also match."""
    with pytest.raises(ToolError, match="pem_private_key"):
        validate_no_secrets("-----BEGIN PRIVATE KEY-----", "description")


def test_validate_no_secrets_bearer_token():
    with pytest.raises(ToolError, match="bearer_token"):
        validate_no_secrets(
            "Authorization: Bearer FAKE.SYNTHETIC.NOT-A-REAL-JWT-VALUE",
            "description",
        )


def test_validate_no_secrets_base64_near_auth_keyword():
    """Long base64-like blob adjacent to an auth keyword."""
    blob = "A" * 50  # 50 chars > 40 minimum
    with pytest.raises(ToolError, match="base64_near_auth"):
        validate_no_secrets(f"authorization: {blob}", "description")


def test_validate_no_secrets_clean_text_passes():
    """A plain vulnerability description with no secrets must not trip."""
    validate_no_secrets(
        "SQL injection in /api/v1/login allows authentication bypass.",
        "description",
    )


def test_validate_no_secrets_existing_aws_still_blocks():
    """Pre-existing AWS detection is preserved by the tuple refactor."""
    with pytest.raises(ToolError, match="aws_access_key"):
        validate_no_secrets("creds AKIAIOSFODNN7EXAMPLE found", "description")


# ---------------------------------------------------------------------------
# validate_tag — Unicode-category branch (F-006 / F-017 + AC-13.6 / AC-13.7)
# ---------------------------------------------------------------------------
#
# These code points are classified by Unicode as line/paragraph separators or
# format/control characters that terminal renderers and log viewers treat as
# line breaks. The category check rejects them with the unified AC-9.6 string.
#
# AC-13.7 — Each fixture uses an explicit "\\uXXXX" Python escape (not a raw
# invisible byte in the source). An `assert "\\uXXXX" in fixture` invariant is
# pinned next to each fixture so a future re-indenter / formatter that
# silently strips the escape will fail the test loudly instead of degrading
# coverage in silence.


_EXACT_ERROR = "tag must not contain control or line-break characters"


def test_validate_tag_rejects_u2028():
    """U+2028 LINE SEPARATOR (Zl)."""
    fixture = "severity\u2028high"
    assert "\u2028" in fixture  # AC-13.7 invariant — escape must survive formatters
    with pytest.raises(ToolError) as exc:
        validate_tag(fixture)
    assert str(exc.value) == _EXACT_ERROR


def test_validate_tag_rejects_u2029():
    """U+2029 PARAGRAPH SEPARATOR (Zp)."""
    fixture = "severity\u2029high"
    assert "\u2029" in fixture  # AC-13.7 invariant
    with pytest.raises(ToolError) as exc:
        validate_tag(fixture)
    assert str(exc.value) == _EXACT_ERROR


def test_validate_tag_rejects_u0085():
    """U+0085 NEXT LINE (Cc)."""
    fixture = "severity\x85high"
    assert "\x85" in fixture  # AC-13.7 invariant
    with pytest.raises(ToolError) as exc:
        validate_tag(fixture)
    assert str(exc.value) == _EXACT_ERROR


def test_validate_tag_rejects_other_Cc_categories():
    """Other Cc (control) code points — e.g. U+0080 PADDING CHARACTER —
    are also rejected by the category branch. U+0080 falls outside the
    legacy [\\x00-\\x1f\\x7f] byte range but is still Unicode category Cc,
    so the unified Unicode-category check catches it (AC-13.6)."""
    fixture = "severity\x80high"
    assert "\x80" in fixture  # AC-13.7 invariant
    with pytest.raises(ToolError) as exc:
        validate_tag(fixture)
    assert str(exc.value) == _EXACT_ERROR


def test_validate_tag_rejects_zero_width_joiner():
    """U+200D ZERO WIDTH JOINER (Cf) — format control, also rejected."""
    fixture = "severity\u200Dhigh"
    assert "\u200D" in fixture  # AC-13.7 invariant
    with pytest.raises(ToolError) as exc:
        validate_tag(fixture)
    assert str(exc.value) == _EXACT_ERROR


def test_validate_tag_error_message_exact():
    """AC-9.6 freezes the exact error string for downstream SIEM rules."""
    fixture = "a\u2028b"
    assert "\u2028" in fixture  # AC-13.7 invariant
    with pytest.raises(ToolError) as exc:
        validate_tag(fixture)
    assert str(exc.value) == "tag must not contain control or line-break characters"


def test_validate_tag_clean_ascii_still_accepted():
    """Hardening must not regress the canonical valid tag form."""
    validate_tag("severity:high")
    validate_tag("scanner:semgrep-1.0")


def test_validate_tag_ascii_newline_rejected_via_unicode_category():
    """AC-13.6: ASCII newline (0x0A) is `unicodedata.category(ch) == "Cc"`,
    so it is caught by the unified Unicode-category branch and emits the
    same error string as U+2028 / U+0085 / etc. The legacy per-byte fast-path
    message (which used to enumerate ANSI / newline / tab variants) is gone —
    there is now ONE error string for every control / line-break code point."""
    with pytest.raises(ToolError) as exc:
        validate_tag("severity\nhigh")
    assert str(exc.value) == _EXACT_ERROR
