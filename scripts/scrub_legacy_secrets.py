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
import os
import sys
from typing import Any
from urllib.parse import urlparse

import httpx

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
    """Yield findings one at a time, paginating through /findings/."""
    offset = 0
    fetched = 0
    while True:
        params = {"limit": PAGE_SIZE, "offset": offset}
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

    matches = 0
    findings_with_matches = 0
    findings_scanned = 0
    mutations_applied = 0
    errors = 0

    with _build_client(base_url, api_key) as client:
        try:
            for finding in _iter_findings(client, args.limit):
                findings_scanned += 1
                finding_id = finding.get("id")
                if finding_id is None:
                    continue

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
                    try:
                        _patch_finding(client, finding_id, patch_body)
                        mutations_applied += 1
                    except httpx.HTTPError as e:
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
        except httpx.HTTPError as e:
            print(f"[scrub] fatal API error: {e}", file=sys.stderr)
            return 1

    summary = {
        "summary": True,
        "mode": mode,
        "findings_scanned": findings_scanned,
        "findings_with_matches": findings_with_matches,
        "matches": matches,
        "mutations_applied": mutations_applied,
        "errors": errors,
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
    args = parser.parse_args()
    if args.dry_run and args.apply:
        parser.error("--dry-run and --apply are mutually exclusive")
    return scrub(args)


if __name__ == "__main__":
    sys.exit(main())
