#!/usr/bin/env python3
"""One-shot scrubber for legacy embedded secrets in DefectDojo findings.

Phase 9 / T4 / F-005 / F-016 — operator-run remediation tool.

Walks every finding visible to the configured admin API key and scans
`title`, `description`, `tags`, and `notes` against the same regex set used
by the write-side `validate_no_secrets` validator (see
`src/mcp_defectdojo/security.py:_SECRET_PATTERNS`). For each match, prints
`finding_id, field, class, before_excerpt, after_excerpt` to stdout as a JSON
record, and (with `--apply`) rewrites the field with `[REDACTED:<class>]`
markers via the DefectDojo PATCH API.

Default mode is `--dry-run` (mutations require explicit `--apply`). The
summary record on stdout is a single line of JSON at the end of the run.
Per-record findings stream as JSON Lines on stdout. Progress / errors stream
to stderr.

Usage:
    DEFECTDOJO_URL=https://defectdojo.example.com \\
    DEFECTDOJO_API_KEY_ADMIN=$(vault kv get -field=api_key secret/dojo-admin) \\
    uv run python scripts/scrub_legacy_secrets.py [--apply] [--limit N]

Environment:
    DEFECTDOJO_URL          base URL (required)
    DEFECTDOJO_API_KEY_ADMIN admin API key with read+write on every finding (required)
    ALLOW_INSECURE_HTTP     "true" to permit http:// base URL (test only)

Exit codes:
    0 — completed cleanly (dry-run or apply)
    1 — auth/connection failure
    2 — bad CLI invocation
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from typing import Any
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

# Reuse the same patterns the server uses. This module is a one-shot script,
# so direct import is fine — the import path is set up by `uv run`.
from mcp_defectdojo.security import _SECRET_PATTERNS

PAGE_SIZE = 100


def _excerpt(text: str, max_len: int = 80) -> str:
    """Short excerpt of a field value for logging — no full secret leakage."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def _redact_field(value: Any) -> tuple[Any, list[str]]:
    """Apply every secret pattern; return (new_value, classes_matched).

    `value` may be a string, list[str], or None — mirrors the field shapes in
    DefectDojo's finding schema (description=str, tags=list[str]).
    """
    if value is None:
        return value, []
    if isinstance(value, list):
        new_list: list[Any] = []
        classes: list[str] = []
        for el in value:
            new_el, el_classes = _redact_field(el)
            new_list.append(new_el)
            classes.extend(el_classes)
        return new_list, classes
    if not isinstance(value, str):
        return value, []
    new = value
    classes: list[str] = []
    for cls_name, pattern in _SECRET_PATTERNS:
        if pattern.search(new):
            new = pattern.sub(f"[REDACTED:{cls_name}]", new)
            classes.append(cls_name)
    return new, classes


def _build_client(base_url: str, api_key: str) -> httpx.Client:
    parsed = urlparse(base_url)
    if parsed.scheme not in ("http", "https"):
        raise SystemExit(f"DEFECTDOJO_URL scheme must be http or https, got '{parsed.scheme}'")
    if parsed.scheme == "http" and os.environ.get("ALLOW_INSECURE_HTTP", "").lower() != "true":
        raise SystemExit(
            "DEFECTDOJO_URL uses http:// — refuse to send admin API key over cleartext. "
            "Set ALLOW_INSECURE_HTTP=true if this is a local test."
        )
    return httpx.Client(
        base_url=f"{base_url.rstrip('/')}/api/v2",
        headers={
            "Authorization": f"Token {api_key}",
            "Accept": "application/json",
        },
        timeout=30.0,
    )


def _iter_findings(client: httpx.Client, limit: int | None):
    """Yield findings one at a time, paginating through /findings/.

    SB-001: pagination MUST be monotonic by `id` so the `<= resume_after`
    checkpoint-resume skip in scrub() is correct. DefectDojo's default
    ordering is unspecified (often `-numerical_severity` or `-created`),
    which would silently skip low-id findings that appear later in page
    order. Pass `ordering=id` explicitly.
    """
    offset = 0
    fetched = 0
    while True:
        params = {"limit": PAGE_SIZE, "offset": offset, "ordering": "id"}
        resp = client.get("/findings/", params=params)
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results") or []
        if not results:
            return
        for r in results:
            yield r
            fetched += 1
            if limit is not None and fetched >= limit:
                return
        if not data.get("next"):
            return
        offset += PAGE_SIZE


def _list_notes(client: httpx.Client, finding_id: int) -> list[dict[str, Any]]:
    """Best-effort fetch of notes for a finding. Endpoint shape varies — fall
    back to an empty list on 404 so the scrubber keeps moving."""
    try:
        resp = client.get(f"/findings/{finding_id}/notes/")
        resp.raise_for_status()
        return resp.json() or []
    except httpx.HTTPStatusError:
        return []


def _patch_finding(client: httpx.Client, finding_id: int, payload: dict[str, Any]) -> None:
    resp = client.patch(f"/findings/{finding_id}/", json=payload)
    resp.raise_for_status()


def _patch_note(client: httpx.Client, finding_id: int, note_id: int, entry: str) -> None:
    """DefectDojo note PATCH path. Some installs require the nested route."""
    resp = client.patch(f"/notes/{note_id}/", json={"entry": entry})
    resp.raise_for_status()


def _patch_finding_with_backoff(
    client: httpx.Client,
    finding_id: int,
    payload: dict[str, Any],
    max_retries: int = 5,
) -> bool:
    """PATCH /findings/{id}/ with exponential backoff on HTTP 429.

    AC-13.9: starts backoff at 1.0s, doubles on each 429 (cap 60.0s), max
    `max_retries` attempts. Non-429 HTTPStatusError propagates so the caller
    can decide whether to abort. Returns True on success, False if all retries
    were exhausted on 429.
    """
    backoff = 1.0
    for attempt in range(max_retries):
        resp = client.patch(f"/findings/{finding_id}/", json=payload)
        if resp.status_code != 429:
            resp.raise_for_status()
            return True
        # SB-002: log each 429 retry so operators / SIEM can detect a
        # throttled-but-recovering scrub in flight (silent backoff hides
        # a 50x slowdown when retries dominate).
        logger.warning(
            "scrub: 429 backoff attempt=%d backoff=%.1fs finding_id=%s",
            attempt + 1, backoff, finding_id,
        )
        time.sleep(backoff)
        backoff = min(backoff * 2, 60.0)
    logger.error(
        "scrub: PATCH /findings/%s/ failed after %d 429 retries; skipping",
        finding_id, max_retries,
    )
    print(
        f"[scrub] PATCH /findings/{finding_id}/ failed after {max_retries} 429 retries; skipping",
        file=sys.stderr,
    )
    return False


def _read_checkpoint(path: str) -> int | None:
    """Return the last successfully-processed finding id from the checkpoint
    file, or None if the file does not exist / is empty / unparseable.

    SB-003: log a warning when the file EXISTS but is unparseable, so a
    silent fall-back to fresh-start is visible to operators (resume is a
    high-stakes operation — failure modes should be loud).
    """
    if not path:
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = fh.read().strip()
        if not data:
            return None
        return int(data)
    except FileNotFoundError:
        return None
    except ValueError:
        logger.warning(
            "scrub: checkpoint file %s present but unparseable (contents=%r); "
            "starting from scratch (resume disabled this run)",
            path, data,
        )
        return None


def _write_checkpoint(path: str, last_id: int) -> None:
    """Atomically write the last-processed finding id to `path` (write to
    .tmp then os.replace)."""
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(str(last_id))
    os.replace(tmp, path)


def scrub(args: argparse.Namespace) -> int:
    base_url = os.environ.get("DEFECTDOJO_URL", "").rstrip("/")
    api_key = os.environ.get("DEFECTDOJO_API_KEY_ADMIN", "")
    if not base_url or not api_key:
        print(
            "DEFECTDOJO_URL and DEFECTDOJO_API_KEY_ADMIN must be set in the environment.",
            file=sys.stderr,
        )
        return 1

    apply = args.apply
    mode = "APPLY" if apply else "DRY-RUN"
    print(f"[scrub] mode={mode} base_url={base_url}", file=sys.stderr)

    # AC-13.9 pacing + checkpoint configuration
    rate_per_second = max(args.rate_per_second, 0.0001)  # avoid div-by-zero
    pacing_interval = 1.0 / rate_per_second
    checkpoint_path = args.checkpoint
    checkpoint_interval = max(args.checkpoint_interval, 1)
    resume_after = _read_checkpoint(checkpoint_path)
    if resume_after is not None:
        print(
            f"[scrub] resuming from checkpoint: skipping findings with id <= {resume_after}",
            file=sys.stderr,
        )

    matches = 0
    findings_with_matches = 0
    findings_scanned = 0
    mutations_applied = 0
    errors = 0
    skipped_resume = 0
    findings_since_checkpoint = 0
    last_processed_id: int | None = None
    last_patch_at: float | None = None

    with _build_client(base_url, api_key) as client:
        try:
            for finding in _iter_findings(client, args.limit):
                finding_id = finding.get("id")
                if finding_id is None:
                    continue

                # AC-13.9 checkpoint resume — skip findings already processed.
                if resume_after is not None and isinstance(finding_id, int) and finding_id <= resume_after:
                    skipped_resume += 1
                    continue

                findings_scanned += 1

                patch_body: dict[str, Any] = {}
                finding_had_match = False

                for field in ("title", "description", "tags", "file_path", "component_name"):
                    new_val, classes = _redact_field(finding.get(field))
                    if classes:
                        finding_had_match = True
                        for cls in classes:
                            matches += 1
                            print(json.dumps({
                                "finding_id": finding_id,
                                "field": field,
                                "class": cls,
                                "before_excerpt": _excerpt(
                                    finding[field] if isinstance(finding.get(field), str)
                                    else json.dumps(finding.get(field))
                                ),
                                "after_excerpt": _excerpt(
                                    new_val if isinstance(new_val, str)
                                    else json.dumps(new_val)
                                ),
                                "would_apply": apply,
                            }))
                        patch_body[field] = new_val

                if patch_body and apply:
                    # AC-13.9 pacing — sleep between PATCH calls.
                    if last_patch_at is not None:
                        elapsed = time.monotonic() - last_patch_at
                        if elapsed < pacing_interval:
                            time.sleep(pacing_interval - elapsed)
                    try:
                        ok = _patch_finding_with_backoff(client, finding_id, patch_body)
                        last_patch_at = time.monotonic()
                        if ok:
                            mutations_applied += 1
                        else:
                            errors += 1
                    except httpx.HTTPError as e:
                        last_patch_at = time.monotonic()
                        errors += 1
                        print(
                            f"[scrub] PATCH /findings/{finding_id}/ failed: {e}",
                            file=sys.stderr,
                        )

                # Notes — separate endpoint, separate mutation per note.
                for note in _list_notes(client, finding_id):
                    note_id = note.get("id")
                    new_entry, classes = _redact_field(note.get("entry"))
                    if classes:
                        finding_had_match = True
                        for cls in classes:
                            matches += 1
                            print(json.dumps({
                                "finding_id": finding_id,
                                "note_id": note_id,
                                "field": "entry",
                                "class": cls,
                                "before_excerpt": _excerpt(note.get("entry") or ""),
                                "after_excerpt": _excerpt(new_entry or ""),
                                "would_apply": apply,
                            }))
                        if apply and note_id is not None:
                            try:
                                _patch_note(client, finding_id, note_id, new_entry)
                                mutations_applied += 1
                            except httpx.HTTPError as e:
                                errors += 1
                                print(
                                    f"[scrub] PATCH /notes/{note_id}/ failed: {e}",
                                    file=sys.stderr,
                                )

                if finding_had_match:
                    findings_with_matches += 1

                # AC-13.9 checkpoint — record progress after every N findings.
                if isinstance(finding_id, int):
                    last_processed_id = finding_id
                    findings_since_checkpoint += 1
                    if findings_since_checkpoint >= checkpoint_interval and checkpoint_path:
                        _write_checkpoint(checkpoint_path, finding_id)
                        findings_since_checkpoint = 0
        except httpx.HTTPError as e:
            print(f"[scrub] fatal API error: {e}", file=sys.stderr)
            return 1

    # Final flush of checkpoint so resume-after-clean-finish is consistent.
    if checkpoint_path and last_processed_id is not None and findings_since_checkpoint > 0:
        _write_checkpoint(checkpoint_path, last_processed_id)

    summary = {
        "summary": True,
        "mode": mode,
        "findings_scanned": findings_scanned,
        "findings_with_matches": findings_with_matches,
        "matches": matches,
        "mutations_applied": mutations_applied,
        "errors": errors,
        "skipped_resume": skipped_resume,
    }
    print(json.dumps(summary))
    print(f"[scrub] done: {summary}", file=sys.stderr)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scrub legacy embedded secrets from existing DefectDojo findings.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually mutate findings (default: dry-run, print only).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Explicit dry-run flag (default; kept for documentation symmetry).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Stop after scanning N findings (default: all).",
    )
    parser.add_argument(
        "--rate-per-second",
        type=float,
        default=5.0,
        help="Max PATCH requests per second (AC-13.9 pacing). Default: 5.0.",
    )
    parser.add_argument(
        "--checkpoint",
        type=str,
        default=".scrub-checkpoint",
        help="File to read/write the last successfully processed finding id "
             "for resume-after-interruption (AC-13.9). Default: .scrub-checkpoint",
    )
    parser.add_argument(
        "--checkpoint-interval",
        type=int,
        default=10,
        help="Write the checkpoint file after every N findings processed. Default: 10.",
    )
    args = parser.parse_args()
    if args.dry_run and args.apply:
        parser.error("--dry-run and --apply are mutually exclusive")
    return scrub(args)


if __name__ == "__main__":
    sys.exit(main())
