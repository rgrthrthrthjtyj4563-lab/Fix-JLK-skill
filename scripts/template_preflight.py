"""Template preflight: validate manifest contract against payload + docx.

Runs *before* :class:`TemplateRenderer` so that mismatches between the bundled
template, the manifest contract, and the run-specific payload fail loudly with
stable error codes rather than silently producing a malformed report.

Two modes:
  * ``warning`` (default during transition): collect every error into the
    returned ``preflight_result`` dict but do not raise; the pipeline writes
    ``template_preflight.json`` and continues to render. Used while Tasks 5-8
    are still inserting placeholders incrementally.
  * ``fail``: raise :class:`TemplatePreflightError` carrying the collected
    errors so that the pipeline aborts before render. Switched on once the
    template fully describes its contract.

Stable error codes (mirrors the spec)::

    MISSING_PAYLOAD_PATH      - required_payload_paths entry not in payload
    INVALID_PAYLOAD_TYPE      - payload value has the wrong shape
    MISSING_PLACEHOLDER       - required singleton not present in template
    DUPLICATE_SINGLETON       - singleton appears more than once
    INVALID_PLACEHOLDER       - placeholder uses unknown {{kind.path}} prefix
    TEMPLATE_TYPE_MISMATCH    - manifest template_type vs. payload meta mismatch
    INVALID_CHART_MODE        - payload chart render_mode not in allowlist
    MISSING_BLOCK_BOUNDARY    - repeat bookmark start/end is absent
    INVALID_BLOCK_BOUNDARY    - repeat bookmark is duplicated/reversed/crossed
"""
from __future__ import annotations

import re
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

try:
    from .template_contract import TemplateContract
except ImportError:  # pragma: no cover - script-style import
    from template_contract import TemplateContract


# Public placeholder regex. Captures (kind, path) for every well-formed
# ``{{kind.path}}`` token. Whitespace inside the braces is tolerated.
PLACEHOLDER_RE = re.compile(r"\{\{\s*(field|block|repeat|media)\.([a-zA-Z0-9_.\-]+)\s*\}\}")

# Catches any double-brace token, well-formed or not. Used to flag malformed
# placeholders such as ``{{foo.bar}}`` (unknown kind) or ``{{ field. }}``.
ANY_DOUBLE_BRACE_RE = re.compile(r"\{\{[^{}]+\}\}")


# Subset of OOXML parts that may legitimately contain placeholders. Keeping
# this list explicit avoids accidentally scanning unrelated XML such as
# ``[Content_Types].xml`` or chart definitions.
SCANNED_PARTS = (
    "word/document.xml",
    "word/header1.xml",
    "word/header2.xml",
    "word/header3.xml",
    "word/footer1.xml",
    "word/footer2.xml",
    "word/footer3.xml",
)


class TemplatePreflightError(RuntimeError):
    """Raised in ``mode='fail'`` when preflight finds at least one error."""

    def __init__(self, errors: list[dict]) -> None:
        first = errors[0] if errors else {"code": "UNKNOWN", "message": "preflight failed"}
        super().__init__(f"[{first['code']}] {first['message']} (+{len(errors) - 1} more)")
        self.errors = errors


@dataclass
class _Issue:
    code: str
    message: str
    location: str | None = None

    def to_dict(self) -> dict:
        out = {"code": self.code, "message": self.message}
        if self.location is not None:
            out["location"] = self.location
        return out


def _payload_get(payload: Any, dotted_path: str) -> tuple[bool, Any]:
    """Return ``(found, value)`` for a dotted path against ``payload``.

    Path components may address dict keys; integer-looking components address
    list indices. Missing or out-of-range lookups return ``(False, None)``.
    """
    cur = payload
    for part in dotted_path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
            continue
        if isinstance(cur, list) and part.isdigit():
            idx = int(part)
            if 0 <= idx < len(cur):
                cur = cur[idx]
                continue
        return False, None
    return True, cur


def _read_template_xml_parts(template_path: Path) -> dict[str, str]:
    """Return ``{part_name: xml_text}`` for the SCANNED_PARTS that exist."""
    parts: dict[str, str] = {}
    with zipfile.ZipFile(template_path) as zf:
        names = set(zf.namelist())
        for part in SCANNED_PARTS:
            if part in names:
                parts[part] = zf.read(part).decode("utf-8", errors="replace")
    return parts


def _strip_xml_tags(xml_text: str) -> str:
    """Roughly strip XML tags so placeholders split across multiple ``w:t``
    runs are still detectable. Preserves text nodes' relative order."""
    # Drop element tags entirely; they do not contain placeholder syntax.
    return re.sub(r"<[^>]+>", "", xml_text)


def scan_template_placeholders(template_path: Path) -> dict[str, list[str]]:
    """Return ``{placeholder_token: [parts where it appears]}`` for the docx.

    ``placeholder_token`` is the canonical ``{{kind.path}}`` (whitespace
    normalised), regardless of whether the source XML split it across runs.
    """
    occurrences: dict[str, list[str]] = {}
    for part_name, xml_text in _read_template_xml_parts(template_path).items():
        flat = _strip_xml_tags(xml_text)
        for match in PLACEHOLDER_RE.finditer(flat):
            token = "{{" + match.group(1) + "." + match.group(2) + "}}"
            occurrences.setdefault(token, []).append(part_name)
    return occurrences


def _scan_invalid_placeholders(template_path: Path) -> list[str]:
    """Return raw double-brace tokens that don't conform to PLACEHOLDER_RE."""
    bad: list[str] = []
    for xml_text in _read_template_xml_parts(template_path).values():
        flat = _strip_xml_tags(xml_text)
        for match in ANY_DOUBLE_BRACE_RE.finditer(flat):
            token = match.group(0)
            if not PLACEHOLDER_RE.fullmatch(token.replace(" ", "")):
                bad.append(token)
    return bad


def _check_payload_paths(
    contract: TemplateContract, payload: dict, issues: list[_Issue]
) -> None:
    for path in contract.required_payload_paths:
        found, value = _payload_get(payload, path)
        if not found:
            issues.append(
                _Issue(
                    code="MISSING_PAYLOAD_PATH",
                    message=f"required payload path not found: {path}",
                    location=path,
                )
            )
            continue
        if value is None:
            issues.append(
                _Issue(
                    code="INVALID_PAYLOAD_TYPE",
                    message=f"required payload path is null: {path}",
                    location=path,
                )
            )


def _check_singletons(
    contract: TemplateContract,
    template_path: Path,
    issues: list[_Issue],
) -> None:
    if not contract.required_singletons and not contract.optional_singletons:
        return
    occurrences = scan_template_placeholders(template_path)
    counts: Counter[str] = Counter({tok: len(parts) for tok, parts in occurrences.items()})

    for token in contract.required_singletons:
        if counts.get(token, 0) == 0:
            issues.append(
                _Issue(
                    code="MISSING_PLACEHOLDER",
                    message=f"required placeholder absent from template: {token}",
                    location=token,
                )
            )
        elif counts[token] > 1:
            issues.append(
                _Issue(
                    code="DUPLICATE_SINGLETON",
                    message=f"singleton placeholder appears {counts[token]} times: {token}",
                    location=token,
                )
            )

    for token in contract.optional_singletons:
        if counts.get(token, 0) > 1:
            issues.append(
                _Issue(
                    code="DUPLICATE_SINGLETON",
                    message=f"optional singleton placeholder appears {counts[token]} times: {token}",
                    location=token,
                )
            )


def _check_invalid_placeholders(
    template_path: Path, issues: list[_Issue]
) -> None:
    for token in _scan_invalid_placeholders(template_path):
        issues.append(
            _Issue(
                code="INVALID_PLACEHOLDER",
                message=f"placeholder does not match {{{{kind.path}}}}: {token}",
                location=token,
            )
        )


def _iter_render_modes(payload: dict, payload_key: str) -> Iterable[str]:
    """Yield ``render_mode`` strings for a payload list at ``payload_key``."""
    items = payload.get(payload_key)
    if not isinstance(items, list):
        return
    for entry in items:
        if isinstance(entry, dict):
            mode = entry.get("render_mode")
            if isinstance(mode, str):
                yield mode


def _check_chart_modes(
    contract: TemplateContract, payload: dict, issues: list[_Issue]
) -> None:
    for payload_key, allowed in contract.allowed_chart_modes.items():
        for mode in _iter_render_modes(payload, payload_key):
            if mode not in allowed:
                issues.append(
                    _Issue(
                        code="INVALID_CHART_MODE",
                        message=(
                            f"{payload_key} render_mode={mode!r} not in allowed "
                            f"{list(allowed)}"
                        ),
                        location=payload_key,
                    )
                )


def _check_repeat_bookmarks(
    contract: TemplateContract,
    template_path: Path,
    issues: list[_Issue],
) -> None:
    if not contract.repeat_bookmarks:
        return
    with zipfile.ZipFile(template_path) as zipped:
        root = ET.fromstring(zipped.read("word/document.xml"))

    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    name_attr = f"{{{w}}}name"
    id_attr = f"{{{w}}}id"
    ordered = list(root.iter())
    positions = {id(node): index for index, node in enumerate(ordered)}
    intervals: list[tuple[int, int, str]] = []

    for token, bookmark_name in contract.repeat_bookmarks.items():
        starts = [
            node
            for node in root.iter(f"{{{w}}}bookmarkStart")
            if node.get(name_attr) == bookmark_name
        ]
        if len(starts) != 1:
            code = "MISSING_BLOCK_BOUNDARY" if not starts else "INVALID_BLOCK_BOUNDARY"
            issues.append(
                _Issue(
                    code=code,
                    message=f"repeat bookmark start count={len(starts)}: {bookmark_name}",
                    location=token,
                )
            )
            continue

        bookmark_id = starts[0].get(id_attr)
        ends = [
            node
            for node in root.iter(f"{{{w}}}bookmarkEnd")
            if node.get(id_attr) == bookmark_id
        ]
        if len(ends) != 1:
            code = "MISSING_BLOCK_BOUNDARY" if not ends else "INVALID_BLOCK_BOUNDARY"
            issues.append(
                _Issue(
                    code=code,
                    message=f"repeat bookmark end count={len(ends)}: {bookmark_name}",
                    location=token,
                )
            )
            continue

        start_pos = positions[id(starts[0])]
        end_pos = positions[id(ends[0])]
        if end_pos <= start_pos:
            issues.append(
                _Issue(
                    code="INVALID_BLOCK_BOUNDARY",
                    message=f"repeat bookmark is reversed: {bookmark_name}",
                    location=token,
                )
            )
            continue
        intervals.append((start_pos, end_pos, bookmark_name))

    for index, (start, end, name) in enumerate(intervals):
        for other_start, other_end, other_name in intervals[index + 1:]:
            if (
                start < other_start < end < other_end
                or other_start < start < other_end < end
            ):
                issues.append(
                    _Issue(
                        code="INVALID_BLOCK_BOUNDARY",
                        message=f"repeat bookmarks cross: {name}, {other_name}",
                        location=name,
                    )
                )


def preflight_template(
    contract: TemplateContract,
    payload: dict,
    *,
    mode: str = "warning",
) -> dict:
    """Validate ``payload`` against ``contract`` and the template on disk.

    Always returns a result dict::

        {"status": "ok"|"error", "errors": [...], "warnings": [...],
         "metrics": {"placeholder_count": N, "singleton_count": M}}

    In ``mode='fail'`` raises :class:`TemplatePreflightError` if any errors
    were collected, after writing the result to disk via the caller.
    """
    if mode not in {"warning", "fail"}:
        raise ValueError(f"unknown preflight mode: {mode!r}")

    issues: list[_Issue] = []
    template_path = contract.template_path

    _check_payload_paths(contract, payload, issues)
    _check_singletons(contract, template_path, issues)
    _check_invalid_placeholders(template_path, issues)
    _check_chart_modes(contract, payload, issues)
    _check_repeat_bookmarks(contract, template_path, issues)

    occurrences = scan_template_placeholders(template_path)
    metrics = {
        "placeholder_count": sum(len(v) for v in occurrences.values()),
        "distinct_placeholders": len(occurrences),
        "required_singleton_count": len(contract.required_singletons),
        "optional_singleton_count": len(contract.optional_singletons),
    }

    errors = [issue.to_dict() for issue in issues]
    result = {
        "status": "ok" if not errors else "error",
        "mode": mode,
        "template_id": contract.template_id,
        "template_type": contract.template_type,
        "template_path": str(template_path),
        "errors": errors,
        "warnings": [],
        "metrics": metrics,
    }

    if mode == "fail" and errors:
        raise TemplatePreflightError(errors)
    return result
