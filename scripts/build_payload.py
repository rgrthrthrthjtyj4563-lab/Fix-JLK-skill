#!/usr/bin/env python3
from __future__ import annotations

import argparse
import difflib
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path

try:
    from .cluster_dimensions import cluster_dimensions
    from .expression_data import is_complete_analysis
except ImportError:
    from cluster_dimensions import cluster_dimensions
    from expression_data import is_complete_analysis

# ─── Fixed dimension library ──────────────────────────────────────────────
_DIMENSION_LIBRARY_CACHE: dict | None = None


def _dimension_library_path() -> Path:
    """Return the path to data/dimension_library.json relative to this file."""
    return Path(__file__).resolve().parent.parent / "data" / "dimension_library.json"


def load_dimension_library() -> dict | None:
    """Load and cache the fixed dimension library JSON.

    Returns the parsed dict on success, None if the file does not exist.
    """
    global _DIMENSION_LIBRARY_CACHE
    if _DIMENSION_LIBRARY_CACHE is not None:
        return _DIMENSION_LIBRARY_CACHE
    lib_path = _dimension_library_path()
    if not lib_path.exists():
        return None
    with open(lib_path, encoding="utf-8") as f:
        _DIMENSION_LIBRARY_CACHE = json.load(f)
    return _DIMENSION_LIBRARY_CACHE


def resolve_theme(questionnaire: dict, meta: dict, cli_args: argparse.Namespace, library: dict) -> dict | None:
    """Find a matching theme entry from the dimension library.

    Matching strategy (first wins):
      1. cli_args.theme  exact match on theme_name
      2. meta["theme"] / meta["\u4e3b\u9898"]  exact match on theme_name
      3. None \u2192 caller falls back to AI / hardcoded logic
    """
    theme_input = (
        getattr(cli_args, "theme", None)
        or meta.get("theme")
        or meta.get("\u4e3b\u9898")
    )
    if not theme_input:
        return None
    theme_input = normalize_space(theme_input)
    for entry in library.get("themes", []):
        if normalize_space(entry.get("theme_name", "")) == theme_input:
            return entry
    return None


def _chart_rule_for_subtopic(
    dim_idx: int, st_idx: int, total_subtopics: int
) -> dict:
    """Derive a default chart spec for a subtopic.

    Rules (matching the hardcoded templates):
      - First subtopic of first dimension → pie + efficacy_pie
      - First subtopic of second dimension → bar3d + behavior_bar
      - Otherwise no chart
    """
    if dim_idx == 0 and st_idx == 0:
        return {"chart_type": "pie", "chart_style_profile": "efficacy_pie"}
    if dim_idx == 1 and st_idx == 0:
        return {"chart_type": "bar3d", "chart_style_profile": "behavior_bar"}
    return {}


def _unique_pattern_for_question(q_text: str) -> str:
    """Extract a unique regex pattern from a question text.

    Strategy: use the FULL question text (regex-escaped) as the pattern
    so each question matches ONLY its own subtopic in
    _build_from_ai_dimensions. This prevents keyword-overlap issues
    where generic keywords like "心达康" match multiple questions.
    """
    if not q_text:
        return r"\x00NEVER_MATCH"
    # Escape regex special chars, then use full text as pattern
    return re.escape(q_text.strip())


def fixed_dimensions_to_ai(theme_entry: dict, questionnaire: dict) -> dict:
    """Convert a fixed-theme entry into the ai_dimensions format that
    cluster_dimensions._build_from_ai_dimensions() consumes.

    Strategy: for each subtopic, build ONE pattern per question_number
    using the full question text (regex-escaped). This guarantees that
    _build_from_ai_dimensions matches each question to exactly the
    subtopic it belongs to, regardless of keyword overlap across
    different dimensions.
    """
    all_questions = questionnaire.get("questions", [])
    if not all_questions:
        return {"dimensions": []}

    # Build a number->question lookup
    q_by_num = {q.get("number"): q for q in all_questions}

    dimensions_out = []
    for dim_idx, dim in enumerate(theme_entry.get("dimensions", [])):
        subtopics_out = []
        charts_out = []
        for st_idx, sub in enumerate(dim.get("subtopics", [])):
            q_nums = sub.get("question_numbers", [])
            subtitle = sub.get("subtitle", "")
            patterns: list[str] = []

            for qn in q_nums:
                q_obj = q_by_num.get(qn)
                if q_obj and q_obj.get("question"):
                    # Use full question text as regex-escaped pattern
                    # so this question matches ONLY this subtopic
                    patterns.append(_unique_pattern_for_question(str(q_obj["question"])))

            # Fallback: if no question found, use never-match pattern
            if not patterns and q_nums:
                patterns = [r"\x00NEVER_MATCH"]

            subtopics_out.append({
                "patterns": patterns,
                "subtitle": subtitle,
            })

            # Chart specs from rules
            chart_rule = _chart_rule_for_subtopic(dim_idx, st_idx, len(dim.get("subtopics", [])))
            if chart_rule:
                charts_out.append({
                    "patterns": patterns[:1] if patterns else [],
                    **chart_rule,
                })

        dimensions_out.append({
            "name": dim.get("name", ""),
            "intro": "",
            "subtopics": subtopics_out,
            "charts": charts_out,
        })

    return {"dimensions": dimensions_out}

def normalize_space(text: str) -> str:
    return re.sub(r"[ \t\u3000]+", " ", str(text).strip())


def normalize_pct(text: str) -> str:
    value = str(text).strip()
    if not value:
        return ""
    if value.endswith("%"):
        value = value[:-1].strip()
    return f"{float(value):.2f}%"


def split_front_matter(text: str) -> tuple[dict, str]:
    stripped = text.lstrip("\ufeff")
    match = re.match(r"^\s*---\s*\n(.*?)\n\s*---\s*\n?(.*)$", stripped, flags=re.DOTALL)
    if not match:
        return {}, stripped
    meta_block = match.group(1)
    body = match.group(2)
    meta = {}
    for line in meta_block.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip().strip('"').strip("'")
    return meta, body


DIMENSIONS_JSON_CHART_TYPES = {"pie", "bar", "bar3d"}
DIMENSIONS_JSON_CHART_STYLES = {"efficacy_pie", "safety_pie", "behavior_bar"}
MIN_KEY_ISSUE_CHARS = 250
MAX_KEY_ISSUE_CHARS = 350
FORBIDDEN_KEY_ISSUE_PATTERNS = [
    r"呈现出较明确的反馈集中趋势",
    r"该环节已经成为影响",
    r"更适合作为后续患者教育和随访沟通的重点切入点",
]


def _require_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    return value.strip()


def _validate_pattern_list(value: object, field: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field} patterns must be a non-empty list")
    patterns = []
    for idx, pattern in enumerate(value):
        pattern_field = f"{field}[{idx}]"
        text = _require_text(pattern, pattern_field)
        try:
            re.compile(text)
        except re.error as exc:
            raise ValueError(f"{pattern_field} invalid regex: {exc}") from exc
        patterns.append(text)
    return patterns


def _validate_dimensions_json(parsed: object) -> dict:
    if not isinstance(parsed, dict):
        raise ValueError("dimensions_json must be a JSON object")
    dimensions = parsed.get("dimensions")
    if not isinstance(dimensions, list) or not dimensions:
        raise ValueError("dimensions_json.dimensions must be a non-empty list")

    normalized_dimensions = []
    for dim_idx, dimension in enumerate(dimensions):
        dim_field = f"dimensions_json.dimensions[{dim_idx}]"
        if not isinstance(dimension, dict):
            raise ValueError(f"{dim_field} must be an object")
        name = _require_text(dimension.get("name"), f"{dim_field}.name")
        intro = _require_text(dimension.get("intro"), f"{dim_field}.intro")
        subtopics = dimension.get("subtopics")
        if not isinstance(subtopics, list) or not subtopics:
            raise ValueError(f"{dim_field}.subtopics must be a non-empty list")

        normalized_subtopics = []
        for sub_idx, subtopic in enumerate(subtopics):
            sub_field = f"{dim_field}.subtopics[{sub_idx}]"
            if not isinstance(subtopic, dict):
                raise ValueError(f"{sub_field} must be an object")
            patterns = _validate_pattern_list(subtopic.get("patterns"), sub_field)
            subtitle = _require_text(subtopic.get("subtitle"), f"{sub_field}.subtitle")
            normalized_subtopics.append({"patterns": patterns, "subtitle": subtitle})

        charts = dimension.get("charts", [])
        if charts is None:
            charts = []
        if not isinstance(charts, list):
            raise ValueError(f"{dim_field}.charts must be a list")
        normalized_charts = []
        for chart_idx, chart in enumerate(charts):
            chart_field = f"{dim_field}.charts[{chart_idx}]"
            if not isinstance(chart, dict):
                raise ValueError(f"{chart_field} must be an object")
            patterns = _validate_pattern_list(chart.get("patterns"), chart_field)
            chart_type = _require_text(chart.get("chart_type"), f"{chart_field}.chart_type")
            if chart_type not in DIMENSIONS_JSON_CHART_TYPES:
                allowed = ", ".join(sorted(DIMENSIONS_JSON_CHART_TYPES))
                raise ValueError(f"{chart_field}.chart_type must be one of: {allowed}")
            chart_style_profile = _require_text(
                chart.get("chart_style_profile"),
                f"{chart_field}.chart_style_profile",
            )
            if chart_style_profile not in DIMENSIONS_JSON_CHART_STYLES:
                allowed = ", ".join(sorted(DIMENSIONS_JSON_CHART_STYLES))
                raise ValueError(f"{chart_field}.chart_style_profile must be one of: {allowed}")
            normalized_charts.append({
                "patterns": patterns,
                "chart_type": chart_type,
                "chart_style_profile": chart_style_profile,
            })

        normalized_dimensions.append({
            "name": name,
            "intro": intro,
            "subtopics": normalized_subtopics,
            "charts": normalized_charts,
        })

    return {"dimensions": normalized_dimensions}


def parse_dimensions_from_meta(meta: dict) -> dict | None:
    """Parse and validate dynamic dimension config from front matter."""
    raw = meta.get("dimensions_json")
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError(f"dimensions_json must be valid JSON: {exc}") from exc
    return _validate_dimensions_json(parsed)


def parse_paragraphs(lines: list[str]) -> list[str]:
    paragraphs = []
    buf: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if buf:
                paragraphs.append(normalize_space(" ".join(buf)))
                buf = []
            continue
        buf.append(stripped)
    if buf:
        paragraphs.append(normalize_space(" ".join(buf)))
    return paragraphs


def strip_markdown_heading_prefix(text: str) -> str:
    return re.sub(r"^\s{0,3}#{1,6}\s*", "", str(text).strip())


def parse_markdown_content(path: Path) -> tuple[dict, dict]:
    meta, body = split_front_matter(path.read_text(encoding="utf-8"))
    lines = body.splitlines()
    current_section: str | None = None
    current_result_section: dict | None = None
    current_subtopic: dict | None = None

    sections = {
        "preface": [],
        "project_background": [],
        "project_execution": [],
        "questionnaire_note": [],
        "result_analysis_intro": [],
        "result_analysis": [],
        "key_issue_analysis": [],
        "overall_analysis": [],
        "recommendations": [],
    }

    def flush_subtopic() -> None:
        nonlocal current_subtopic, current_result_section
        if current_subtopic and current_result_section:
            current_subtopic["paragraphs"] = parse_paragraphs(current_subtopic["lines"])
            del current_subtopic["lines"]
            current_result_section["subtopics"].append(current_subtopic)
        current_subtopic = None

    def flush_result_section() -> None:
        nonlocal current_result_section
        flush_subtopic()
        if current_result_section:
            current_result_section["intro"] = parse_paragraphs(current_result_section["lines"])
            del current_result_section["lines"]
            sections["result_analysis"].append(current_result_section)
        current_result_section = None

    for line in lines:
        heading = re.match(r"^(#{2,5})\s+(.+?)\s*$", line.lstrip())
        if heading:
            level = len(heading.group(1))
            title = normalize_space(heading.group(2))
            if title in {"前言"}:
                flush_result_section()
                current_section = "preface"
                continue
            if title in {"项目背景", "一、项目背景"}:
                flush_result_section()
                current_section = "project_background"
                continue
            if title in {"项目开展情况", "二、项目开展情况"}:
                flush_result_section()
                current_section = "project_execution"
                continue
            if title in {"问卷说明", "三、问卷说明"}:
                flush_result_section()
                current_section = "questionnaire_note"
                continue
            if title in {"问卷结果分析", "四、问卷结果分析"}:
                flush_result_section()
                current_section = "result_analysis_intro"
                continue
            if title in {"调研结果", "五、调研结果"}:
                flush_result_section()
                current_section = "summary"
                continue
            if level <= 3 and re.match(r"4\.\d+", title):
                flush_result_section()
                current_section = "result_analysis"
                # Extract section_number from title (e.g. "4.1 药品疗效" → "4.1")
                sn_match = re.match(r"(4\.\d+)\s*", title)
                section_number = sn_match.group(1) if sn_match else title
                section_title = title[len(section_number):].strip()
                current_result_section = {
                    "title": title,
                    "section_number": section_number,
                    "section_title": section_title,
                    "lines": [],
                    "subtopics": [],
                }
                continue
            if level >= 4 and current_result_section:
                flush_subtopic()
                current_section = "result_analysis"
                current_subtopic = {"title": title, "lines": [], "subtitle": re.sub(r"^（\d+）\s*", "", title).strip()}
                continue
            if re.match(r"5\.1", title):
                flush_result_section()
                current_section = "key_issue_analysis"
                continue
            if re.match(r"5\.2", title):
                flush_result_section()
                current_section = "overall_analysis"
                continue
            if re.match(r"5\.3", title):
                flush_result_section()
                current_section = "recommendations"
                continue

        if current_section in {"preface", "project_background", "project_execution", "questionnaire_note", "result_analysis_intro", "key_issue_analysis", "overall_analysis", "recommendations"}:
            sections[current_section].append(strip_markdown_heading_prefix(line))
        elif current_result_section and current_subtopic:
            current_subtopic["lines"].append(strip_markdown_heading_prefix(line))
        elif current_result_section:
            current_result_section["lines"].append(strip_markdown_heading_prefix(line))

    flush_result_section()
    return meta, {
        "preface": parse_paragraphs(sections["preface"]),
        "project_background": parse_paragraphs(sections["project_background"]),
        "project_execution": parse_paragraphs(sections["project_execution"]),
        "questionnaire_note": parse_paragraphs(sections["questionnaire_note"]),
        "result_analysis_intro": parse_paragraphs(sections["result_analysis_intro"]),
        "result_analysis": sections["result_analysis"],
        "summary": {
            "key_issue_analysis": parse_paragraphs(sections["key_issue_analysis"]),
            "overall_analysis": parse_paragraphs(sections["overall_analysis"]),
            "recommendations": parse_paragraphs(sections["recommendations"]),
        },
    }


def build_attachment_questions(questionnaire: dict) -> list[dict]:
    items = []
    for question in questionnaire.get("questions", []):
        options = []
        for option in question.get("options", []):
            code = str(option["label"]).strip()
            text = normalize_space(option["text"])
            if not text or text == code:
                continue
            options.append(
                {
                    "code": code,
                    "text": text,
                    "count": str(option.get("count") or "").strip(),
                    "pct": normalize_pct(option["pct"]),
                }
            )
        items.append(
            {
                "question_ref": f"q{int(question['number']):02d}",
                "number": int(question["number"]),
                "question": normalize_space(question["question"]),
                "options": options,
            }
        )
    return items


def _valid_sample_value(value: object) -> str:
    text = str(value or "").strip()
    if not text or text.lower() in {"none", "nan", "null"}:
        return ""
    try:
        number = float(text)
        if number <= 0:
            return ""
        if number.is_integer():
            return str(int(number))
        return str(number)
    except Exception:
        return text


def _sample_int(value: object) -> int | None:
    normalized = _valid_sample_value(value)
    if not normalized:
        return None
    try:
        number = float(normalized)
    except Exception:
        return None
    if number <= 0:
        return None
    return int(number)


def build_settlement(sample_size: object) -> dict:
    sample_count = _sample_int(sample_size) or 0
    sample_unit_price = 100
    report_unit_price = 30000
    report_count = 1
    sample_amount = sample_count * sample_unit_price
    report_amount = report_unit_price * report_count
    return {
        "sample_unit_price": sample_unit_price,
        "sample_count": sample_count,
        "sample_amount": sample_amount,
        "report_unit_price": report_unit_price,
        "report_count": report_count,
        "report_amount": report_amount,
        "total_amount": sample_amount + report_amount,
    }


def _option_count_total(question: dict) -> str:
    counts = []
    for option in question.get("options", []):
        value = _valid_sample_value(option.get("count"))
        if not value:
            return ""
        try:
            counts.append(int(float(value)))
        except Exception:
            return ""
    return str(sum(counts)) if counts else ""


def first_sample_size(questionnaire: dict) -> str | None:
    totals = [
        value
        for value in (_valid_sample_value(item.get("total")) for item in questionnaire.get("questions", []))
        if value
    ]
    if totals:
        common = sorted(set(totals), key=lambda item: (-totals.count(item), item))
        return common[0]

    derived = [
        value
        for value in (_option_count_total(item) for item in questionnaire.get("questions", []))
        if value
    ]
    if not derived:
        return None
    common = sorted(set(derived), key=lambda item: (-derived.count(item), item))
    return common[0]


def format_today() -> str:
    today = date.today()
    return f"{today.year}年{today.month:02d}月{today.day:02d}日"


def format_survey_period_display(survey_period: str) -> str:
    """Return compact display format: omit repeated year when possible."""
    parts = survey_period.split("——")
    if len(parts) != 2:
        return survey_period.replace("——", "-")
    start = parts[0]
    end = parts[1]
    start_match = re.match(r"(\d{4})年(\d{2})月(\d{2})日", start)
    end_match = re.match(r"(\d{4})年(\d{2})月(\d{2})日", end)
    if start_match and end_match:
        sy, sm, sd = start_match.groups()
        ey, em, ed = end_match.groups()
        if sy == ey:
            if sm == em:
                return f"{sy}年{sm}月{sd}日-{ed}日"
            return f"{sy}年{sm}月{sd}日-{em}月{ed}日"
        return f"{sy}年{sm}月{sd}日-{ey}年{em}月{ed}日"
    return survey_period.replace("——", "-")


def normalize_survey_period(text: str) -> str:
    cleaned = normalize_space(text).replace("—", "-").replace("–", "-").replace("至", "-").replace("~", "-")
    parts = [part.strip() for part in re.split(r"\s*-\s*", cleaned, maxsplit=1) if part.strip()]
    if len(parts) != 2:
        raise ValueError(f"Invalid survey_period: {text}")

    def _parse_fragment(fragment: str, default_year: int | None = None, default_month: int | None = None) -> date:
        numbers = [int(x) for x in re.findall(r"\d+", fragment)]
        if len(numbers) == 3:
            year, month, day = numbers
        elif len(numbers) == 2 and default_year is not None:
            year, month, day = default_year, numbers[0], numbers[1]
        elif len(numbers) == 1 and default_year is not None and default_month is not None:
            year, month, day = default_year, default_month, numbers[0]
        else:
            raise ValueError(f"Invalid survey_period: {text}")
        return date(year, month, day)

    start = _parse_fragment(parts[0])
    end = _parse_fragment(parts[1], default_year=start.year, default_month=start.month)
    return f"{start.year}年{start.month:02d}月{start.day:02d}日——{end.year}年{end.month:02d}月{end.day:02d}日"


def derive_service_date(survey_period: str) -> str:
    normalized = normalize_survey_period(survey_period)
    numbers = [int(x) for x in re.findall(r"\d+", normalized)]
    end = date(numbers[3], numbers[4], numbers[5])
    next_month = date(end.year + (1 if end.month == 12 else 0), 1 if end.month == 12 else end.month + 1, 1)
    after_next_month = date(next_month.year + (1 if next_month.month == 12 else 0), 1 if next_month.month == 12 else next_month.month + 1, 1)
    last_day = after_next_month - timedelta(days=1)
    day_span = (last_day - next_month).days
    offset = min(day_span, max(0, (end.day * 3 + end.month) % (day_span + 1)))
    service_dt = next_month + timedelta(days=offset)
    return service_dt.strftime("%Y年%m月%d日")


def as_single_paragraph(content: list[str], fallback: str) -> list[str]:
    chosen = content if content else [fallback]
    merged = normalize_space(" ".join(strip_markdown_heading_prefix(item) for item in chosen if str(item).strip()))
    return [merged] if merged else [fallback]


def choose_paragraphs(content: list[str], fallback: list[str]) -> list[str]:
    normalized = [normalize_space(strip_markdown_heading_prefix(item)) for item in content if str(item).strip()]
    return normalized if normalized else fallback


def sanitize_body_paragraphs(content: list[str]) -> list[str]:
    blocked_patterns = [
        r"^(?:前言|项目背景|项目开展情况|问卷说明|问卷结果分析|调研结果|免责申明)\s*$",
        r"^(?:4|5)\.\d+",
        r"^附件\d+",
    ]
    sanitized = []
    for item in content:
        text = normalize_space(strip_markdown_heading_prefix(item))
        if not text:
            continue
        if any(re.match(pattern, text) for pattern in blocked_patterns):
            continue
        sanitized.append(text)
    return sanitized


def choose_body_paragraphs(content: list[str], fallback: list[str]) -> list[str]:
    normalized = sanitize_body_paragraphs(content)
    return normalized if normalized else fallback

def choose_analysis_paragraphs(content: list[str], fallback: list[str]) -> list[str]:
    normalized = sanitize_body_paragraphs(content)
    if len(normalized) == 1 and is_complete_analysis(normalized[0]):
        return normalized
    # Legacy callers may pass fallback; new callers should use
    # require_ai_analysis_paragraphs() which raises on missing/invalid AI text.
    return fallback


def require_ai_analysis_paragraphs(
    content: list[str],
    section_number: str,
    question_ref: str,
    subtitle: str,
) -> list[str]:
    """Validate AI analysis paragraphs for a 4.x subtopic.

    Raises ValueError with diagnostic info if AI text is missing or invalid,
    instead of silently falling back to programmatic text.
    """
    try:
        from expression_data import (
            MIN_ANALYSIS_CHARS as ED_MIN,
            MAX_ANALYSIS_CHARS as ED_MAX,
            FORBIDDEN_PATTERNS as ED_FORBIDDEN,
            is_complete_analysis as ed_is_complete,
        )
    except ImportError:
        from .expression_data import (
            MIN_ANALYSIS_CHARS as ED_MIN,
            MAX_ANALYSIS_CHARS as ED_MAX,
            FORBIDDEN_PATTERNS as ED_FORBIDDEN,
            is_complete_analysis as ed_is_complete,
        )

    _NUMERIC_PERCENT = r"\d+(?:\.\d+)?[%％]"

    normalized = sanitize_body_paragraphs(content)
    if not normalized:
        raise ValueError(
            f"{section_number} / {question_ref} / {subtitle} "
            "缺少 AI 分析正文"
        )
    if len(normalized) != 1:
        raise ValueError(
            f"{section_number} / {question_ref} / {subtitle} "
            f"AI 分析正文应为 1 段，实际 {len(normalized)} 段"
        )
    text = normalized[0]
    if not ed_is_complete(text):
        # Provide specific diagnostics
        diagnostics = []
        if len(text) < ED_MIN:
            diagnostics.append(f"字数不足({len(text)}<{ED_MIN})")
        if len(text) > ED_MAX:
            diagnostics.append(f"字数超标({len(text)}>{ED_MAX})")
        if not any(marker in text for marker in ["说明", "表明", "反映", "提示"]):
            diagnostics.append("缺少分析判断词(说明/表明/反映/提示)")
        if not any(marker in text for marker in ["整体看", "整体来看", "后续", "需", "仍"]):
            diagnostics.append("缺少收束词(整体看/后续/需/仍)")
        if any(re.search(p, text) for p in ED_FORBIDDEN):
            diagnostics.append("包含禁用模式(A/B/C/D选项等)")
        if not re.search(_NUMERIC_PERCENT, text):
            diagnostics.append("缺少数字百分比")
        raise ValueError(
            f"{section_number} / {question_ref} / {subtitle} "
            f"AI 分析正文不合格: {'; '.join(diagnostics) if diagnostics else '未知原因'}"
        )
    return normalized


def choose_two_paragraphs(content: list[str], fallback: list[str]) -> list[str]:
    normalized = sanitize_body_paragraphs(content)
    if len(normalized) == 2:
        return normalized
    return fallback



def build_project_execution(
    region: str,
    sample_size: str | None,
    survey_period: str,
    question_count: int,
    project_dimensions: list[str],
) -> dict:
    dimensions_text = "、".join(project_dimensions)
    lines = [
        f"项目工具：调查问卷，{question_count}道选择题。其内容涵盖{dimensions_text}{len(project_dimensions)}大维度，全面覆盖患者用药全流程关键节点。",
        f"样本采集范围：{region}",
        f"样本采集数量：本次共收集筛选到有效问卷{sample_size or '问卷未提供'}份。",
        f"样本采集时间：{survey_period}",
    ]
    return {"lines": lines}


def build_questionnaire_note(question_count: int) -> dict:
    intro = "为提升数据可比性与分析结果的科学性，本研究采用以下标准化统计处理方法对原始问卷数据进行系统规整："
    items = [
        "1．数据清洗：剔除无效作答、空白选项及关键信息缺失数据，保障分析数据集的完整性与可靠性。",
        "2．数据转换：按照问卷分析需求对原始选项、样本量和占比进行统一格式化处理，使其适配后续统计逻辑。",
        "3．数据聚合：根据题目主题和分析维度对数据进行归类整合，形成结构化分析单元，降低交叉解读难度。",
        "4．数据可视化：针对重点问题配置结果表格与对应图表，以直观呈现样本分布特征及不同选项之间的差异。",
    ]
    closing = f"通过上述标准化数据处理流程，可在{question_count}道题目的分析中有效强化不同维度数据间的可比性，确保研究结论具备更好的客观性与可信度。"
    return {"intro": intro, "items": items, "closing": closing}


def derive_report_title(theme: str | None = None) -> str:
    theme_text = normalize_space(theme or "")
    if theme_text:
        return f"{theme_text}问卷调研分析报告"
    return "问卷调研分析报告"


def derive_project_background(product: str, region: str = "") -> list[str]:
    return [
        normalize_space(
            f"随着人口老龄化加快和慢性病长期管理需求提升，{product}在真实用药场景中的疗效感知、安全性体验和持续使用支持逐渐成为患者管理中的重要观察内容。"
            f"{region or '目标地区'}患者的用药反馈能够反映区域内治疗习惯、信息获取方式和用药执行差异，为后续优化产品沟通和患者教育提供基础依据。"
        ),
        normalize_space(
            f"本次调研围绕{region or '目标地区'}患者展开，重点关注患者在使用{product}过程中的真实体验与行为表现。"
            "通过结构化问卷收集和维度化分析，可以进一步识别当前用药服务中的优势环节和薄弱环节，为后续形成更具针对性的支持策略提供参考。"
        ),
    ]


def derive_preface(product: str, region: str = "", sample_size: str = "") -> list[str]:
    return [
        normalize_space(
            f"{product}作为临床用药管理中的重要品种，其真实世界使用体验不仅关系到患者对疗效和安全性的主观判断，也会影响长期规范用药、复诊沟通和后续健康管理质量。"
            f"本次调研面向{region or '目标地区'}患者群体开展，共收集有效问卷{sample_size or '若干'}份，围绕患者在认知、执行、便利性和支持需求等方面的核心反馈进行系统整理，力求从患者视角呈现真实使用场景中的主要特征。"
            "通过把患者主观反馈与结构化选项统计结合起来，报告能够更清晰地观察产品使用过程中的稳定表现和潜在改进空间。"
        ),
        normalize_space(
            f"报告结合{region or '目标地区'}样本数据，从问卷结构、结果分布和重点问题三个层面展开分析，重点观察患者在使用{product}过程中的主要感受、行为差异和服务支持需求。"
            "相关结果既可用于识别当前用药沟通中已经形成的积极基础，也可帮助发现仍需补强的教育、提醒和解释环节，为后续优化患者教育内容、完善用药沟通方式和提升服务支持质量提供参考。"
            "因此，本报告不仅呈现统计结果，也为后续患者管理、区域服务优化和产品沟通策略提供可落地的分析依据。"
        ),
    ]


def question_map_by_ref(questionnaire: dict) -> dict:
    mapping = {}
    for question in build_attachment_questions(questionnaire):
        mapping[question["question_ref"]] = question
    return mapping


def default_subtopic_paragraph(question: dict, style_index: int = 0) -> list[str]:
    """Generate analysis paragraphs using expression modules from expression_data.py."""
    try:
        from .expression_data import generate_analysis_paragraphs
    except ImportError:
        from expression_data import generate_analysis_paragraphs

    options = question.get("options", [])
    if not options:
        return ["原始问卷未提供足够的选项数据，无法形成有效统计解释。"]

    return generate_analysis_paragraphs(question.get("question", ""), options, style_index=style_index)


def build_key_issue_analysis(grouped: dict, section_titles: list[str], region: str, product: str) -> list[str]:
    dim_text = "、".join(title for title in section_titles if title)
    return [
        f"本次问卷重点问题主要集中在{dim_text}等维度，整体反馈呈现出积极体验较为集中、个别环节仍有优化空间的特点。",
        f"结合{region or '目标地区'}患者的整体反馈来看，{product}在多数核心维度上已经形成较稳定的正向感知，但在部分行为管理与信息支持环节仍需持续强化沟通和引导。",
    ]


def key_issue_heading(question: dict) -> str:
    text = question.get("question", "")
    rules = [
        (r"血压控制|控压", "1. 血压控制现状与特征"),
        (r"头晕|头痛|不良反应", "2. 不良反应发生率"),
        (r"价格|负担|承受", "2. 药品价格接受度情况"),
        (r"剂量|医嘱", "2. 剂量执行规范性表现"),
        (r"监测血压|监测频率", "2. 血压监测行为特征"),
    ]
    for pattern, heading in rules:
        if re.search(pattern, text):
            return heading
    if re.search(r"忘记服药|漏服", text):
        return "漏服处理与依从风险"
    if re.search(r"自行调整|剂量", text):
        return "剂量调整与规范用药"
    if re.search(r"依从性|改进|提高", text):
        return "依从性提升需求"
    if re.search(r"健康教育|教育支持|培训", text):
        return "健康教育支持需求"
    return "重点问题分析"


def key_issue_chart_title(question: dict) -> str:
    text = question.get("question", "")
    rules = [
        (r"血压控制|控压", "患者血压控制效果"),
        (r"头晕|头痛|不良反应", "不良反应发生率"),
        (r"价格|负担|承受", "药品价格接受度情况"),
        (r"剂量|医嘱", "患者剂量遵循情况"),
        (r"监测血压|监测频率", "患者血压监测频率"),
    ]
    for pattern, title in rules:
        if re.search(pattern, text):
            return title
    if re.search(r"忘记服药|漏服", text):
        return "漏服处理方式"
    if re.search(r"自行调整|剂量", text):
        return "剂量调整行为"
    if re.search(r"依从性|改进|提高", text):
        return "依从性提升需求"
    if re.search(r"健康教育|教育支持|培训", text):
        return "健康教育支持需求"
    return question.get("question", "重点问题")


def key_issue_chart_title_from_subtitle(subtitle: str, question: dict) -> str:
    cleaned = normalize_space(subtitle)
    cleaned = re.sub(r"^（\d+）\s*", "", cleaned)
    cleaned = re.sub(r"[（(]\s*多选\s*[）)]", "", cleaned)
    cleaned = re.sub(r"分析$", "", cleaned).strip()
    return cleaned or key_issue_chart_title(question)


def build_key_issue_paragraph(question: dict, region: str, product: str) -> str:
    options = sorted(
        question.get("options", []),
        key=lambda item: float(str(item.get("pct", "0")).rstrip("%") or 0),
        reverse=True,
    )
    if not options:
        return f"围绕{product}在{region or '目标地区'}患者中的这一重点问题，目前问卷样本不足以支撑稳定结论，建议后续结合补充样本继续观察。"

    lead = options[0]
    second = options[1] if len(options) > 1 else None
    tail = options[-1]
    question_text = question.get("question", "")

    if re.search(r"血压控制|控压", question_text):
        return normalize_space(
            f"在{region or '目标地区'}患者样本中，围绕{product}使用后的血压控制表现，患者反馈主要集中在“{lead.get('text', '')}”"
            f"{'和“' + second.get('text', '') + '”' if second else ''}等正向感知选项，说明多数患者能够较清晰地感受到产品在长期控压中的稳定价值。"
            f"这意味着产品的疗效体验并非停留在抽象认知层面，而是已经在真实用药过程中被患者转化为可感知、可复述的主观评价。"
            f"与此同时，仍有少量反馈落在“{tail.get('text', '')}”等相对谨慎的选项上，提示个别患者在血压管理结果上仍存在波动感受。"
            "从重点问题角度看，这一题反映出的核心并不是产品是否具备降压价值，而是后续如何通过复诊沟通、监测教育与规范用药提醒，让已经形成的正向疗效体验进一步稳定下来，并减少少数患者在血压波动阶段的疑虑。"
        )

    if re.search(r"价格|负担|承受", question_text):
        return normalize_space(
            f"在价格接受度这一重点问题上，患者反馈主要集中在“{lead.get('text', '')}”"
            f"{'和“' + second.get('text', '') + '”' if second else ''}等可接受区间，说明{product}在{region or '当前区域'}的长期使用成本并未普遍构成障碍。"
            "这类结果的意义在于，患者对产品价值的认可并没有因为价格而被明显削弱，长期治疗的连续性因此具备较好的现实基础。"
            f"同时，仍有少量患者落在“{tail.get('text', '')}”等相对保守的选项上，提示不同患者在长期负担感知上仍存在差异。"
            "对于慢病用药而言，价格不是单独存在的判断，而会直接影响患者是否愿意持续购药、是否能够长期坚持治疗。"
            "因此，这一重点题目所反映出的结论不仅是“价格总体可接受”，更是产品在长期管理场景中具备较强的经济可持续性，为稳定依从行为提供了重要支撑。"
        )

    topic = key_issue_heading(question)
    return normalize_space(
        f"{topic}呈现出较明确的反馈集中趋势，患者选择主要落在“{lead.get('text', '')}”"
        f"{'和“' + second.get('text', '') + '”' if second else ''}等选项上，说明该环节已经成为影响{product}长期使用体验的重要观察点。"
        f"同时，“{tail.get('text', '')}”等低频选项仍提示少数患者存在理解、执行或支持不足的情况，不能仅以主流反馈掩盖潜在管理风险。"
        f"结合{region or '当前区域'}样本看，该问题更适合作为后续患者教育和随访沟通的重点切入点，通过更清晰的用药说明、提醒机制和复诊反馈，帮助患者把正确认知转化为稳定的日常行为。"
    )


def select_key_issue_questions(result_sections: list[dict], qmap: dict, preferred_section_numbers: list[str]) -> list[dict]:
    selected = []
    used_refs = set()
    for section_number in preferred_section_numbers:
        section = next((item for item in result_sections if item.get("section_number") == section_number), None)
        if not section:
            continue
        for subtopic in section.get("subtopics", []):
            refs = subtopic.get("question_refs", [])
            if refs and refs[0] in qmap and refs[0] not in used_refs:
                question = qmap[refs[0]]
                selected.append(
                    {
                        "question_ref": refs[0],
                        "heading": key_issue_heading(question),
                        "chart_title": key_issue_chart_title(question),
                        "question": question,
                    }
                )
                used_refs.add(refs[0])
                break
        if len(selected) >= 2:
            break
    return selected[:2]


def _parse_key_issue_sections(meta: dict, valid_numbers: set[str]) -> list[str] | None:
    """从 front matter 解析 key_issue_sections 字段。

    支持两种格式：
      - JSON 字符串：'["4.4", "4.2"]'
      - 逗号分隔字符串：'4.4,4.2'

    校验每个编号是否存在于 valid_numbers 中，不合法则报错。
    最多返回前 2 个有效值，与 select_key_issue_questions 对齐。
    未声明时返回 None，调用方回退到默认顺序。
    """
    raw = meta.get("key_issue_sections") if meta else None
    if not raw:
        return None

    if isinstance(raw, list):
        candidates = [str(item).strip() for item in raw]
    elif isinstance(raw, str):
        stripped = raw.strip()
        if stripped.startswith("["):
            try:
                candidates = json.loads(stripped)
            except (json.JSONDecodeError, TypeError):
                raise ValueError(f"Invalid JSON in key_issue_sections: {raw}")
        else:
            candidates = [item.strip() for item in stripped.split(",") if item.strip()]
    else:
        raise ValueError(f"Unsupported key_issue_sections type: {type(raw).__name__}")

    if not candidates:
        return None

    validated = []
    for candidate in candidates:
        candidate = str(candidate).strip()
        if candidate not in valid_numbers:
            raise ValueError(
                f"key_issue_sections contains unknown section number '{candidate}'. "
                f"Valid section numbers: {sorted(valid_numbers)}"
            )
        validated.append(candidate)

    return validated[:2]


def _parse_key_issue_question_refs(meta: dict, qmap: dict, result_sections: list[dict]) -> list[str]:
    raw = meta.get("key_issue_question_refs") if meta else None
    if not raw:
        raise ValueError("key_issue_question_refs is required and must contain exactly 2 question refs.")

    if isinstance(raw, list):
        candidates = [str(item).strip() for item in raw]
    elif isinstance(raw, str):
        stripped = raw.strip()
        if stripped.startswith("["):
            try:
                candidates = json.loads(stripped)
            except (json.JSONDecodeError, TypeError) as exc:
                raise ValueError(f"Invalid JSON in key_issue_question_refs: {raw}") from exc
        else:
            candidates = [item.strip() for item in stripped.split(",") if item.strip()]
    else:
        raise ValueError(f"Unsupported key_issue_question_refs type: {type(raw).__name__}")

    normalized = []
    for candidate in candidates:
        text = str(candidate).strip()
        if re.fullmatch(r"\d+", text):
            text = f"q{int(text):02d}"
        elif re.fullmatch(r"[qQ]\d+", text):
            text = f"q{int(text[1:]):02d}"
        normalized.append(text)

    if len(normalized) != 2 or len(set(normalized)) != 2:
        raise ValueError("key_issue_question_refs must contain exactly 2 unique question refs.")

    assigned_refs = {
        ref
        for section in result_sections
        for subtopic in section.get("subtopics", [])
        for ref in subtopic.get("question_refs", [])
    }
    for ref in normalized:
        if ref not in qmap:
            raise ValueError(f"key_issue_question_refs contains unknown question ref '{ref}'.")
        if ref not in assigned_refs:
            raise ValueError(f"key_issue_question_refs contains question ref '{ref}' outside result-analysis sections.")
    return normalized


def select_key_issue_questions_by_refs(question_refs: list[str], qmap: dict, subtitle_by_ref: dict[str, str] | None = None) -> list[dict]:
    subtitle_by_ref = subtitle_by_ref or {}
    return [
        {
            "question_ref": ref,
            "heading": key_issue_heading(qmap[ref]),
            "chart_title": key_issue_chart_title_from_subtitle(subtitle_by_ref.get(ref, ""), qmap[ref]),
            "question": qmap[ref],
        }
        for ref in question_refs
    ]


def choose_key_issue_analysis(ai_paragraphs: list[str], expected_count: int) -> list[str]:
    paragraphs = sanitize_body_paragraphs(ai_paragraphs)
    if expected_count <= 0:
        return []
    if len(paragraphs) != expected_count:
        raise ValueError(
            f"5.1问卷重点问题分析 must contain exactly {expected_count} AI paragraphs."
        )
    for index, paragraph in enumerate(paragraphs, start=1):
        length = len(paragraph)
        if length < MIN_KEY_ISSUE_CHARS or length > MAX_KEY_ISSUE_CHARS:
            raise ValueError(
                f"5.1问卷重点问题分析 paragraph {index} length must be "
                f"{MIN_KEY_ISSUE_CHARS}-{MAX_KEY_ISSUE_CHARS} Chinese characters."
            )
        if not any(marker in paragraph for marker in ["说明", "表明", "反映", "提示", "判断"]):
            raise ValueError(f"5.1问卷重点问题分析 paragraph {index} lacks analytical judgment.")
        for pattern in FORBIDDEN_KEY_ISSUE_PATTERNS:
            if re.search(pattern, paragraph):
                raise ValueError(f"5.1问卷重点问题分析 paragraph {index} contains fixed programmatic wording.")
    return paragraphs


def validate_content_structure(content: dict, grouped: dict) -> None:
    expected_sections = grouped.get("sections", [])
    expected_by_number = {section["section_number"]: section for section in expected_sections}
    expected_numbers = [section["section_number"] for section in expected_sections]
    drafted_sections = content.get("result_analysis", [])
    if not drafted_sections:
        return

    drafted_numbers = [section.get("section_number", "") for section in drafted_sections]
    if any(number not in expected_by_number for number in drafted_numbers):
        raise ValueError("AI draft contains result-analysis sections outside the detected template structure.")

    expected_order = [number for number in expected_numbers if number in drafted_numbers]
    if drafted_numbers != expected_order:
        raise ValueError("AI draft result-analysis section order conflicts with the detected template structure.")

    for section in drafted_sections:
        expected = expected_by_number[section["section_number"]]
        drafted_subtopics = section.get("subtopics", [])
        expected_subtopics = expected.get("subtopics", [])
        if len(drafted_subtopics) > len(expected_subtopics):
            raise ValueError(
                f"AI draft subtopic count exceeds detected template slots for {section['section_number']}."
            )
        for index, drafted_subtopic in enumerate(drafted_subtopics):
            drafted_subtopic_title = normalize_space(drafted_subtopic.get("title", ""))
            if drafted_subtopic_title and index >= len(expected_subtopics):
                raise ValueError(
                    f"AI draft has more subtopics than detected template slots for {section['section_number']}."
                )


class PreflightError(ValueError):
    """Raised when report_content.md fails preflight checks.

    Attributes:
        errors: list of error strings describing all failures.
    """
    def __init__(self, errors: list[str], result: dict | None = None) -> None:
        self.errors = errors
        self.result = result or {"status": "failed", "errors": errors, "warnings": [], "checks": []}
        super().__init__("PREFLIGHT_FAILED:\n" + "\n".join(f"- {e}" for e in errors))


def _parse_preflight_key_issue_refs(raw: object) -> list[str]:
    if isinstance(raw, list):
        candidates = [str(item).strip() for item in raw]
    else:
        ref_text = str(raw or "").strip()
        if ref_text.startswith("["):
            candidates = json.loads(ref_text)
        else:
            candidates = [r.strip() for r in ref_text.split(",") if r.strip()]

    normalized = []
    for candidate in candidates:
        text = str(candidate).strip()
        if re.fullmatch(r"\d+", text):
            text = f"q{int(text):02d}"
        elif re.fullmatch(r"[qQ]\d+", text):
            text = f"q{int(text[1:]):02d}"
        normalized.append(text)
    return normalized


def _closest_theme_candidates(theme: str, candidates: list[str], limit: int = 5) -> list[str]:
    theme_norm = normalize_space(theme)
    direct = [
        candidate for candidate in candidates
        if theme_norm and (theme_norm in candidate or candidate in theme_norm)
    ]
    fuzzy = difflib.get_close_matches(theme_norm, candidates, n=limit, cutoff=0.15)
    merged = []
    for candidate in direct + fuzzy:
        if candidate and candidate not in merged:
            merged.append(candidate)
        if len(merged) >= limit:
            break
    return merged


def preflight_report_content(
    meta: dict,
    content: dict,
    *,
    library: dict | None = None,
    questionnaire: dict | None = None,
) -> dict:
    """Verify report_content.md completeness before build_payload.

    Checks metadata fields, chapter presence, 4.x analysis paragraphs, and 5.x content.
    Raises PreflightError with all errors listed if validation fails.
    """
    errors: list[str] = []
    warnings: list[str] = []
    checks: list[dict] = []

    def record(name: str, passed: bool, message: str = "") -> None:
        checks.append({"name": name, "status": "passed" if passed else "failed", "message": message})
        if not passed and message:
            errors.append(message)

    # ── Front matter checks ──
    survey_period = meta.get("survey_period") or meta.get("时间")
    record(
        "survey_period",
        bool(survey_period),
        "缺少 survey_period（front matter 中需提供 survey_period 或 时间）",
    )

    ki_refs = meta.get("key_issue_question_refs")
    parsed_refs: list[str] = []
    if not ki_refs:
        record("key_issue_question_refs", False, "缺少 key_issue_question_refs（front matter 中需提供 2 道重点题号）")
    else:
        try:
            parsed_refs = _parse_preflight_key_issue_refs(ki_refs)
            record(
                "key_issue_question_refs",
                len(parsed_refs) == 2 and len(set(parsed_refs)) == 2,
                f"key_issue_question_refs 必须恰好 2 个，当前 {len(parsed_refs)} 个",
            )
        except (json.JSONDecodeError, TypeError):
            record("key_issue_question_refs", False, "key_issue_question_refs 格式错误，期望 JSON 数组如 '[\"q02\", \"q05\"]'")

    # ── Theme / fixed dimension library match ──
    theme_input = meta.get("theme") or meta.get("主题")
    theme_entry = None
    if theme_input and library:
        theme_normalized = normalize_space(theme_input)
        matched = False
        candidates = []
        for entry in library.get("themes", []):
            entry_name = normalize_space(entry.get("theme_name", ""))
            candidates.append(entry_name)
            if entry_name == theme_normalized:
                matched = True
                theme_entry = entry
                break
        if not matched:
            closest = _closest_theme_candidates(str(theme_input), candidates)
            record(
                "theme",
                False,
                f"主题 '{theme_input}' 未命中固定维度表。最接近的候选: {closest}",
            )
        else:
            record("theme", True)

    # ── Chapter presence checks ──
    required_chapters = {
        "preface": "前言",
        "project_background": "项目背景",
    }
    for key, label in required_chapters.items():
        paragraphs = content.get(key, [])
        record(
            key,
            bool(paragraphs and any(str(p).strip() for p in paragraphs)),
            f"缺少 {label} 章节（{key}）正文",
        )

    result_analysis = content.get("result_analysis", [])
    record(
        "result_analysis",
        bool(result_analysis),
        "缺少 问卷结果分析(4.x) 章节正文",
    )

    grouped = None
    if questionnaire:
        try:
            ai_dimensions = None
            if theme_entry:
                ai_dimensions = fixed_dimensions_to_ai(theme_entry, questionnaire)
            elif meta:
                ai_dimensions = parse_dimensions_from_meta(meta)
            grouped = cluster_dimensions(questionnaire, ai_dimensions=ai_dimensions)
        except ValueError as exc:
            record("dimension_grouping", False, f"维度结构解析失败: {exc}")

    if result_analysis and grouped:
        try:
            validate_content_structure(content, grouped)
            record("result_analysis_structure", True)
        except ValueError as exc:
            record("result_analysis_structure", False, str(exc))

        drafted_by_sn = {
            section.get("section_number"): section
            for section in result_analysis
        }
        for expected_section in grouped.get("sections", []):
            sn = expected_section.get("section_number", "?")
            drafted_section = drafted_by_sn.get(sn)
            if not drafted_section:
                record(f"{sn}_section", False, f"缺少 {sn} {expected_section.get('section_title', '')} 章节")
                continue
            drafted_subtopics = drafted_section.get("subtopics", [])
            for index, expected_subtopic in enumerate(expected_section.get("subtopics", [])):
                subtitle = expected_subtopic.get("subtitle", "")
                question_ref = next(iter(expected_subtopic.get("question_refs", [])), "")
                if index >= len(drafted_subtopics):
                    record(
                        f"{sn}_{question_ref}",
                        False,
                        f"{sn} / {question_ref} / {subtitle} 缺少 AI 分析正文",
                    )
                    continue
                try:
                    require_ai_analysis_paragraphs(
                        drafted_subtopics[index].get("paragraphs", []),
                        section_number=sn,
                        question_ref=question_ref,
                        subtitle=subtitle,
                    )
                    record(f"{sn}_{question_ref}", True)
                except ValueError as exc:
                    record(f"{sn}_{question_ref}", False, str(exc))
    elif result_analysis:
        for section in result_analysis:
            sn = section.get("section_number", "?")
            st_title = section.get("section_title", "")
            subtopics = section.get("subtopics", [])
            if not subtopics:
                record(f"{sn}_section", False, f"{sn} {st_title} 缺少小标题和分析正文")
            for subtopic in subtopics:
                subtitle = subtopic.get("subtitle", subtopic.get("title", ""))
                paragraphs = subtopic.get("paragraphs", [])
                if not paragraphs or not any(str(p).strip() for p in paragraphs):
                    record(f"{sn}_{subtitle}", False, f"{sn} / {subtitle} 缺少 AI 分析正文")

    summary = content.get("summary", {})
    key_issue = summary.get("key_issue_analysis", [])
    record(
        "key_issue_analysis",
        bool(key_issue and any(str(p).strip() for p in key_issue)),
        "缺少 5.1 问卷重点问题分析正文",
    )

    overall = summary.get("overall_analysis", [])
    record(
        "overall_analysis",
        bool(overall and any(str(p).strip() for p in overall)),
        "缺少 5.2 调研结果总结正文",
    )

    recs = summary.get("recommendations", [])
    recs_present = bool(recs and any(str(p).strip() for p in recs))
    record("recommendations", recs_present, "缺少 5.3 建议正文")
    if recs_present and not any(re.match(r"^\s*\d+\.", str(item).strip()) for item in recs):
        record("recommendations_numbered_items", False, "5.3 建议缺少编号条目")

    # ── Cross-check key_issue_question_refs against actual sections ──
    if parsed_refs and grouped:
        assigned_refs = {
            ref
            for section in grouped.get("sections", [])
            for subtopic in section.get("subtopics", [])
            for ref in subtopic.get("question_refs", [])
        }
        for ref in parsed_refs:
            record(
                f"key_issue_ref_{ref}",
                ref in assigned_refs,
                f"key_issue_question_refs 中的 '{ref}' 未在 4.x 真实分组中找到对应分析",
            )
    elif parsed_refs and result_analysis:
        assigned_refs = {
                ref
                for section in result_analysis
                for subtopic in section.get("subtopics", [])
                for ref in subtopic.get("question_refs", [])
        }
        for ref in parsed_refs:
            record(
                f"key_issue_ref_{ref}",
                ref in assigned_refs,
                f"key_issue_question_refs 中的 '{ref}' 未出现在 4.x 分析章节中",
            )

    result = {
        "status": "failed" if errors else "passed",
        "errors": errors,
        "warnings": warnings,
        "checks": checks,
    }
    if errors:
        raise PreflightError(errors, result)
    return result


def build_programmatic_recommendations(product: str, region: str) -> list[str]:
    return [
        normalize_space(
            f"围绕{product}在{region or '当前调研区域'}患者中的真实使用反馈，建议持续强化规律服药、血压监测和复诊沟通等基础教育内容，帮助患者将已有的正向体验稳定转化为长期管理习惯。"
        ),
        normalize_space(
            "针对联合用药确认、信息理解和少数执行薄弱环节，可通过药师提示、随访提醒和场景化问答材料补强关键知识点，减少患者在日常决策中的理解偏差。"
        ),
        normalize_space(
            "后续患者支持可继续围绕重点问题开展分层服务，对反馈积极的维度沉淀正向案例，对存在波动的维度配置更有针对性的提醒与解释机制。"
        ),
    ]


def _question_option_snapshot(question: dict) -> str:
    options = question.get("options", [])
    if not options:
        return "问卷原始分布不足，需结合后续回访进一步确认。"
    ranked = sorted(
        options,
        key=lambda item: float(str(item.get("pct", "0")).rstrip("%") or 0),
        reverse=True,
    )
    lead = ranked[0]
    follow = ranked[1] if len(ranked) > 1 else None
    if follow:
        return f"反馈主要集中在“{lead.get('text', '')}”与“{follow.get('text', '')}”两类选项"
    return f"反馈主要集中在“{lead.get('text', '')}”这一选项"


def build_programmatic_overall_analysis(
    result_sections: list[dict],
    qmap: dict,
    region: str,
    product: str,
    sample_size: str | None,
) -> list[str]:
    section_lookup = {section["section_number"]: section for section in result_sections}

    def first_snapshot(section_number: str) -> str:
        section = section_lookup.get(section_number, {})
        for subtopic in section.get("subtopics", []):
            refs = subtopic.get("question_refs", [])
            if refs and refs[0] in qmap:
                return _question_option_snapshot(qmap[refs[0]])
        return "当前维度的问卷反馈能够形成相对稳定的结论，但仍需结合后续随访持续观察。"

    dimension_names = [sec.get("section_title", "") for sec in result_sections]
    section_numbers = list(section_lookup.keys())

    dim_count = len(result_sections)
    dimensions_text = "、".join(name for name in dimension_names if name)

    opening = (
        f"本次调研基于{region or '目标地区'}患者样本开展，结合{sample_size or '当前收集到的有效问卷'}份有效问卷结果，"
        f"对{product}在真实使用过程中的反馈进行了多维度复盘。"
        "整体来看，患者反馈以正向、稳定为主，说明产品在长期使用场景中已经形成较成熟的使用基础，但部分环节仍存在继续优化空间。"
    )

    snapshot_paragraphs = []
    for sec in result_sections:
        sn = sec["section_number"]
        snap = first_snapshot(sn)
        st = sec.get("section_title", "")
        if snap and snap != "当前维度的问卷反馈能够形成相对稳定的结论，但仍需结合后续随访持续观察。":
            snapshot_paragraphs.append(f"在{st}维度，{snap}。")

    if len(snapshot_paragraphs) >= 3:
        mid_para = "".join(snapshot_paragraphs[:3])
        detail_paras = "".join(snapshot_paragraphs[3:])
        closing = (
            f"综合判断，{product}在{region or '当前调研区域'}已经具备较完整的正向使用基础，"
            f"后续重点应放在加强行为执行、提升细分解释能力，以及补充关键支持服务等动作上。"
        )
        return [normalize_space(opening), normalize_space(mid_para), normalize_space(detail_paras + closing)]
    elif snapshot_paragraphs:
        body = "".join(snapshot_paragraphs)
        closing = (
            f"综合判断，{product}在{region or '当前调研区域'}已经具备较完整的正向使用基础，"
            f"后续重点应放在加强行为执行、提升细分解释能力，以及补充关键支持服务等动作上。"
        )
        return [normalize_space(opening), normalize_space(body), normalize_space(closing)]
    else:
        closing = (
            f"综合各项反馈，{product}在{region or '当前调研区域'}已经具备较完整的正向使用基础，"
            f"后续重点应放在加强行为执行、提升细分解释能力，以及补充关键支持服务等动作上。"
        )
        return [normalize_space(opening), normalize_space(closing)]


def choose_overall_analysis(
    ai_paragraphs: list[str],
    programmatic_reference: list[str],
    product: str,
    region: str,
) -> list[str]:
    normalized = choose_body_paragraphs(ai_paragraphs, [])
    total_len = sum(len(paragraph) for paragraph in normalized)
    if not normalized:
        raise ValueError("5.2调研结果总结 must be provided by AI draft.")
    if normalized == choose_body_paragraphs(programmatic_reference, []):
        raise ValueError("5.2调研结果总结 must not use programmatic fallback text.")
    if not (3 <= len(normalized) <= 5):
        raise ValueError("5.2调研结果总结 must contain 3-5 AI paragraphs.")
    if total_len > 700:
        raise ValueError("5.2调研结果总结 must not exceed 700 Chinese characters.")
    joined = "".join(normalized)
    if product and product not in joined and region and region not in joined:
        raise ValueError("5.2调研结果总结 must mention the product or region.")
    if not any(marker in joined for marker in ["说明", "表明", "反映", "提示", "判断"]):
        raise ValueError("5.2调研结果总结 lacks analytical judgment.")
    return normalized


def choose_recommendations(ai_paragraphs: list[str], fallback: list[str]) -> list[str]:
    normalized = choose_body_paragraphs(ai_paragraphs, [])
    if not normalized:
        raise ValueError("5.3建议 must be provided by AI draft.")
    if normalized == choose_body_paragraphs(fallback, []):
        raise ValueError("5.3建议 must not use programmatic fallback text.")
    if any("药企方面" in paragraph or "临床层面：" in paragraph or "临床层面:" in paragraph for paragraph in normalized):
        raise ValueError("5.3建议 contains forbidden template subject wording.")

    total_len = sum(len(paragraph) for paragraph in normalized)
    numbered_items = [paragraph for paragraph in normalized if re.match(r"^\d+\.\s*\S+", paragraph)]
    has_intro = bool(normalized and normalized[0] not in numbered_items)
    intro_valid = not has_intro or (
        40 <= len(normalized[0]) <= 120
        and any(keyword in normalized[0] for keyword in ("基于", "结合"))
        and "建议" in normalized[0]
    )
    target_keywords = ("针对", "围绕", "聚焦", "面向", "建议")
    carrier_keywords = (
        "提醒卡", "药盒", "二维码", "随访表", "患者手册", "记录表", "短视频", "沟通群",
        "宣传册", "流程单", "闹钟", "药师", "门诊", "药店", "台账", "贴",
    )
    item_lengths_valid = all(80 <= len(item) <= 180 for item in numbered_items)
    item_targets_valid = all(any(keyword in item for keyword in target_keywords) for item in numbered_items)
    item_carriers_valid = all(any(keyword in item for keyword in carrier_keywords) for item in numbered_items)

    if not intro_valid:
        raise ValueError("5.3建议 intro is invalid.")
    if not (2 <= len(numbered_items) <= 4):
        raise ValueError("5.3建议 must contain 2-4 numbered recommendation items.")
    if not (300 <= total_len <= 600):
        raise ValueError("5.3建议 total length must be 300-600 Chinese characters.")
    if not item_lengths_valid:
        raise ValueError("5.3建议 numbered items must be 80-180 Chinese characters each.")
    if not item_targets_valid:
        raise ValueError("5.3建议 numbered items must describe target problems or groups.")
    if not item_carriers_valid:
        raise ValueError("5.3建议 numbered items must include concrete tools or carriers.")
    return normalized


def build_payload(questionnaire: dict, meta: dict, content: dict, cli_args: argparse.Namespace) -> dict:
    # Fixed dimension library takes priority when a theme matches
    library = load_dimension_library()
    theme_entry = resolve_theme(questionnaire, meta if meta else {}, cli_args, library) if library else None
    if theme_entry:
        ai_dimensions = fixed_dimensions_to_ai(theme_entry, questionnaire)
    else:
        ai_dimensions = parse_dimensions_from_meta(meta) if meta else None
    grouped = cluster_dimensions(questionnaire, ai_dimensions=ai_dimensions)
    validate_content_structure(content, grouped)
    attachment_questions = build_attachment_questions(questionnaire)
    qmap = {item["question_ref"]: item for item in attachment_questions}
    sample_size = _valid_sample_value(cli_args.sample_size) or first_sample_size(questionnaire)
    survey_period_raw = cli_args.survey_period or meta.get("survey_period")
    if not survey_period_raw:
        raise ValueError("survey_period is required.")
    survey_period = normalize_survey_period(survey_period_raw)
    survey_period_display = format_survey_period_display(survey_period)
    product = cli_args.product or meta.get("product") or meta.get("品种")
    region = cli_args.region or meta.get("region") or meta.get("地区")
    question_count = questionnaire.get("question_count", len(questionnaire.get("questions", [])))
    theme = getattr(cli_args, "theme", None) or meta.get("theme") or meta.get("主题")
    report_title = derive_report_title(theme)

    ai_sections = content.get("result_analysis", [])
    ai_by_sn = {}
    for item in ai_sections:
        sn = item.get("section_number")
        if sn:
            ai_by_sn[sn] = item

    dimension_names = grouped.get("project_dimensions", [])

    # Build result_intro from template
    result_intro_template = grouped.get("result_intro_template", grouped.get("result_intro", ""))
    result_intro = result_intro_template.format(
        question_count=question_count,
        dimensions_list="、".join(dimension_names),
        dimension_count=len(dimension_names),
    )

    result_sections = []
    chart_map = {}
    analysis_style_index = 0
    for planned in grouped["sections"]:
        section_number = planned["section_number"]
        drafted = ai_by_sn.get(section_number, {})

        section_title = planned["section_title"]
        section_intro = [planned["section_intro"]]

        ai_subtopics = drafted.get("subtopics", [])
        ai_st_by_idx = {}
        for idx, st in enumerate(ai_subtopics):
            ai_st_by_idx[idx] = st

        subtopics = []
        for st in planned["subtopics"]:
            refs = st["question_refs"]
            st_idx = st["subtopic_index"]
            ai_st = ai_st_by_idx.get(st_idx, {})

            subtitle = ai_st.get("subtitle") or st.get("subtitle", "")
            question_ref_label = refs[0] if refs else "unknown"
            analysis = require_ai_analysis_paragraphs(
                ai_st.get("paragraphs", []),
                section_number=section_number,
                question_ref=question_ref_label,
                subtitle=subtitle,
            )
            analysis_style_index += 1

            subtopics.append({
                "subtitle": subtitle,
                "question_refs": refs,
                "paragraphs": analysis,
            })

        # Visual groups
        visuals = []
        for visual in planned["visual_groups"]:
            question = qmap[visual["question_ref"]]
            chart_map[visual["chart_ref"]] = question
            visuals.append({
                "question_ref": visual["question_ref"],
                "chart_ref": visual["chart_ref"],
                "chart_type": visual["chart_type"],
                "chart_style_profile": visual["chart_style_profile"],
                "table_data": question,
            })

        result_sections.append({
            "section_number": section_number,
            "section_title": section_title,
            "section_intro": section_intro if section_intro else [],
            "visual_groups": visuals,
            "subtopics": subtopics,
        })

    key_issue_question_refs = _parse_key_issue_question_refs(meta, qmap, result_sections)
    subtitle_by_ref = {
        ref: subtopic.get("subtitle", "")
        for section in result_sections
        for subtopic in section.get("subtopics", [])
        for ref in subtopic.get("question_refs", [])
    }
    key_issue_questions = select_key_issue_questions_by_refs(key_issue_question_refs, qmap, subtitle_by_ref)
    key_issue_items = [
        {
            "question_ref": item["question_ref"],
            "heading": item["heading"],
            "chart_title": item["chart_title"],
            "chart_type": "pie",
            "paragraph": "",
            "categories": [opt.get("text", "") for opt in item["question"].get("options", [])],
            "values": [float(str(opt.get("pct", "0")).rstrip("%") or 0) for opt in item["question"].get("options", [])],
        }
        for item in key_issue_questions
    ]
    programmatic_key_issue_analysis = [
        build_key_issue_paragraph(qmap[item["question_ref"]], region, product)
        for item in key_issue_items
    ]
    ai_key_issue_analysis = choose_key_issue_analysis(
        content["summary"]["key_issue_analysis"],
        len(key_issue_items),
    )
    for item, paragraph in zip(key_issue_items, ai_key_issue_analysis):
        item["paragraph"] = paragraph

    programmatic_overall_analysis = build_programmatic_overall_analysis(
        result_sections,
        qmap,
        region,
        product,
        str(sample_size) if sample_size else None,
    )
    ai_overall_analysis = choose_overall_analysis(
        content["summary"]["overall_analysis"],
        programmatic_overall_analysis,
        product,
        region,
    )
    programmatic_recommendations = build_programmatic_recommendations(product, region)
    ai_recommendations = choose_recommendations(
        content["summary"]["recommendations"],
        programmatic_recommendations,
    )
    overview_categories = [section.get("section_title", "") for section in result_sections]
    overview_values = [len(section.get("subtopics", [])) for section in result_sections]
    overview_charts = [
        {
            "chart_ref": "chart_4_overview_pie",
            "title": "问卷结果分析维度占比饼状图",
            "chart_type": "pie",
            "render_mode": "image",
            "categories": overview_categories,
            "values": overview_values,
        },
        {
            "chart_ref": "chart_4_overview_bar",
            "title": "问卷结果分析维度题目数量横向柱形图",
            "chart_type": "bar",
            "render_mode": "image",
            "categories": overview_categories,
            "values": overview_values,
        },
    ]

    return {
        "meta": {
            "product": product,
            "region": region,
            "time": cli_args.time or meta.get("time") or meta.get("时间"),
            "survey_period": survey_period,
            "survey_period_display": survey_period_display,
            "valid_count": _valid_sample_value(cli_args.valid_count) or _valid_sample_value(meta.get("valid_count")) or sample_size,
            "sample_size": sample_size,
            "template_type": grouped["template_type"],
            "template_doc": grouped["template_doc"],
            "report_date": format_today(),
        },
        "red_font_replacements": {
            "drug_name": product,
            "region": region,
            "sample_size": str(sample_size) if sample_size else "",
            "survey_period": survey_period_display or "",
            "report_date": format_today(),
        },
        "header_text": report_title,
        "report_title": report_title,
        "service": {
            "unit": cli_args.disclaimer_unit or meta.get("disclaimer_unit") or "北京玖麟空科技有限公司",
            "date": derive_service_date(survey_period),
            "settlement": build_settlement(sample_size),
        },
        "preface": choose_two_paragraphs(content["preface"], derive_preface(product, region, str(sample_size) if sample_size else "")),
        "project_background": choose_two_paragraphs(content["project_background"], derive_project_background(product, region)),
        "project_execution": build_project_execution(
            region,
            sample_size,
            survey_period_display,
            question_count,
            dimension_names,
        ),
        "questionnaire_note": build_questionnaire_note(question_count),
        "result_analysis": {
            "intro": [result_intro],
            "overview_charts": overview_charts,
            "sections": result_sections,
        },
        "summary": {
            "key_issue_analysis": ai_key_issue_analysis,
            "key_issue_analysis_programmatic": programmatic_key_issue_analysis,
            "key_issue_items": key_issue_items,
            "overall_analysis": ai_overall_analysis,
            "overall_analysis_programmatic": programmatic_overall_analysis,
            "recommendations": ai_recommendations,
            "recommendations_programmatic": programmatic_recommendations,
        },
        "attachments": {
            "attachment1_name": cli_args.attachment_name or meta.get("attachment_name") or theme or "问卷调查附件",
            "attachment1_questions": attachment_questions,
            "attachment2_name": "问卷调查明细表",
        },
        "disclaimer": {
            "title": "免责申明",
            "items": [
                "（1）本次调研项目以随机选取对象进行面对面调研，本次调研只对本次样本数据负责。",
                f"（2）承接单位调研项目，是针对{product}这一品种调研，并非指定厂家指定品种。",
                "（3）本次调研只针对调研区域数据负责，不代表全国调研数据。",
            ],
            "unit": cli_args.disclaimer_unit or meta.get("disclaimer_unit") or "北京玖麟空科技有限公司",
            "date": derive_service_date(survey_period),
        },
        "chart_map": chart_map,
    }


def validate_payload(payload: dict) -> None:
    for key in ["meta", "header_text", "report_title", "preface", "project_background", "project_execution", "questionnaire_note", "result_analysis", "summary", "attachments", "disclaimer"]:
        if key not in payload:
            raise ValueError(f"Missing payload key: {key}")
    if len(payload["preface"]) != 2:
        raise ValueError("Preface must contain exactly 2 paragraphs")
    if len(payload["project_background"]) != 2:
        raise ValueError("Project background must contain exactly 2 paragraphs")
    region = payload.get("meta", {}).get("region", "")
    if region and not any(region in paragraph for paragraph in payload["project_background"]):
        raise ValueError("Project background must mention the region")
    if payload["project_background"] == payload["preface"]:
        raise ValueError("Project background must not substantially repeat the preface")
    overview_charts = payload["result_analysis"].get("overview_charts", [])
    if len(overview_charts) != 2:
        raise ValueError("Result analysis overview charts must contain exactly 2 charts.")
    if overview_charts[0].get("chart_type") != "pie":
        raise ValueError("First overview chart must be pie.")
    if overview_charts[0].get("render_mode") != "image":
        raise ValueError("First overview chart must use image render mode.")
    if overview_charts[1].get("chart_type") != "bar":
        raise ValueError("Second overview chart must be bar.")
    if overview_charts[1].get("render_mode") != "image":
        raise ValueError("Second overview chart must use image render mode.")
    if not all(isinstance(value, int) for value in overview_charts[1].get("values", [])):
        raise ValueError("Overview chart values must be integer question counts.")
    if not payload["result_analysis"]["sections"]:
        raise ValueError("Result analysis sections must not be empty.")
    for section in payload["result_analysis"]["sections"]:
        if not section["subtopics"]:
            raise ValueError(f"Section {section['section_number']}{section['section_title']} must contain subtopics.")
    key_issue_items = payload.get("summary", {}).get("key_issue_items", [])
    key_issue_analysis = payload.get("summary", {}).get("key_issue_analysis", [])
    if len(key_issue_items) != 2:
        raise ValueError("5.1 key_issue_question_refs must resolve to exactly 2 key issue items.")
    choose_key_issue_analysis(key_issue_analysis, len(key_issue_items))
    for item, paragraph in zip(key_issue_items, key_issue_analysis):
        if item.get("paragraph") != paragraph:
            raise ValueError("5.1 key issue item paragraph must match AI key issue analysis.")
    overall_analysis = payload.get("summary", {}).get("overall_analysis", [])
    choose_overall_analysis(
        overall_analysis,
        payload.get("summary", {}).get("overall_analysis_programmatic", []),
        payload.get("meta", {}).get("product", ""),
        payload.get("meta", {}).get("region", ""),
    )
    recommendations = payload.get("summary", {}).get("recommendations", [])
    choose_recommendations(
        recommendations,
        payload.get("summary", {}).get("recommendations_programmatic", build_programmatic_recommendations(
            payload.get("meta", {}).get("product", ""),
            payload.get("meta", {}).get("region", ""),
        )),
    )
    settlement = payload.get("service", {}).get("settlement", {})
    if settlement:
        expected_sample_amount = int(settlement.get("sample_count", 0)) * int(settlement.get("sample_unit_price", 0))
        expected_report_amount = int(settlement.get("report_count", 0)) * int(settlement.get("report_unit_price", 0))
        if int(settlement.get("sample_amount", -1)) != expected_sample_amount:
            raise ValueError("Settlement sample amount is incorrect.")
        if int(settlement.get("report_amount", -1)) != expected_report_amount:
            raise ValueError("Settlement report amount is incorrect.")
        if int(settlement.get("total_amount", -1)) != expected_sample_amount + expected_report_amount:
            raise ValueError("Settlement total amount is incorrect.")
    service_unit = payload.get("service", {}).get("unit", "")
    disclaimer_unit = payload.get("disclaimer", {}).get("unit", "")
    if service_unit and disclaimer_unit and service_unit != disclaimer_unit:
        raise ValueError("Service unit and disclaimer unit must be identical.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build template-aligned patient report payload.")
    parser.add_argument("questionnaire_json")
    parser.add_argument("report_content")
    parser.add_argument("-o", "--output", required=True)
    parser.add_argument("--product")
    parser.add_argument("--region")
    parser.add_argument("--time")
    parser.add_argument("--theme")
    parser.add_argument("--attachment-name")
    parser.add_argument("--survey-period")
    parser.add_argument("--sample-size")
    parser.add_argument("--valid-count")
    parser.add_argument("--disclaimer-unit")
    args = parser.parse_args()

    questionnaire = json.loads(Path(args.questionnaire_json).read_text(encoding="utf-8"))
    meta, content = parse_markdown_content(Path(args.report_content))
    payload = build_payload(questionnaire, meta, content, args)
    validate_payload(payload)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
