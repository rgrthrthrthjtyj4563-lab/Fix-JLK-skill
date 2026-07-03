"""Internal reference guard — shared validator for cross-section text rules.

The Word report targets external readers (clinicians, pharmacists, marketing).
Internal data-model identifiers (`q01`/`q02`/...) and section orchestration
language ("第1段对应q02") must never leak into rendered body text. The front
matter is exempt because it never reaches the Word document.

This module is intentionally dependency-free (no imports from build_payload /
expression_data) so it can be reused by preflight, final validation, and tests
without circular-import risk.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


# Internal question ref pattern: `q` followed by digits, case-insensitive.
# Reports never legitimately contain `q\d+` in body text — front matter is the
# sole carrier, and is excluded by callers.
INTERNAL_REF_PATTERN = re.compile(r"q\d+", re.IGNORECASE)

# Section-orchestration language: "第1段对应q02" / "第 2 段：" etc.
# Allow reader-facing ordinals in patient questions ("第一个选项") — this only
# flags explicit "第N段" or "第N段对应..." patterns.
INTERNAL_SECTION_REF_PATTERN = re.compile(r"第\s*\d+\s*段")


@dataclass(frozen=True)
class InternalRefIssue:
    """A single violation surfaced by the guard."""
    rule: str  # "internal_ref" | "section_orchestration"
    snippet: str  # The offending substring (truncated)
    description: str  # Human-readable explanation for the AI author


def find_internal_ref_violations(text: str, *, max_snippet: int = 60) -> list[InternalRefIssue]:
    """Return all internal-ref / section-orchestration violations in ``text``.

    Empty / whitespace-only text returns no violations. Each issue carries a
    snippet up to ``max_snippet`` characters centered on the match for
    actionable error messages.
    """
    if not text or not text.strip():
        return []
    issues: list[InternalRefIssue] = []
    for match in INTERNAL_REF_PATTERN.finditer(text):
        issues.append(
            InternalRefIssue(
                rule="internal_ref",
                snippet=_centered_snippet(text, match.start(), match.end(), max_snippet),
                description=(
                    "正文含内部题号 q\\d+，请改用题目语义。"
                    "front matter 的 key_issue_question_refs 字段不受此限制。"
                ),
            )
        )
    for match in INTERNAL_SECTION_REF_PATTERN.finditer(text):
        issues.append(
            InternalRefIssue(
                rule="section_orchestration",
                snippet=_centered_snippet(text, match.start(), match.end(), max_snippet),
                description=(
                    "正文含'第N段'内部编排痕迹（如'第1段对应q02'），"
                    "请删除前缀或直接以题目语义开头。"
                ),
            )
        )
    return issues


def _centered_snippet(text: str, start: int, end: int, max_len: int) -> str:
    """Return up to ``max_len`` chars of ``text`` centered on the [start, end) match."""
    if end - start >= max_len:
        return text[start : start + max_len]
    pad = (max_len - (end - start)) // 2
    left = max(0, start - pad)
    right = min(len(text), end + pad)
    snippet = text[left:right]
    if left > 0:
        snippet = "..." + snippet
    if right < len(text):
        snippet = snippet + "..."
    return snippet


def assert_clean_body_text(text: str, *, location: str) -> None:
    """Raise ``ValueError`` with a structured message if ``text`` is not clean.

    ``location`` is a short string used in the error message to identify where
    the bad text came from (e.g. ``"4.2 / q05 / 复查项目认知分析"`` or
    ``"5.1 / 第 2 段"``).
    """
    issues = find_internal_ref_violations(text)
    if not issues:
        return
    parts = [f"{location}：{issue.description}（匹配：{issue.snippet!r}）" for issue in issues]
    raise ValueError("；".join(parts))
