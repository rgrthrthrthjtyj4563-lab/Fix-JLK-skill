#!/usr/bin/env python3
"""
Question grouping engine — matches questions to dimension/subtopic slots.

Design principle: this module does NOT generate display text.
It only groups questions by regex patterns and assigns chart config.
Dimension names, subtitles, intros, and analysis text are AI-generated
and supplied via build_payload.py from the report_content/markdown draft.

When ai_dimensions is provided (from report_content.md front matter),
it takes precedence over the hardcoded grouping templates. The hardcoded
templates serve as fallback for backward compatibility.
"""

from __future__ import annotations

import argparse
import json
import re
from copy import deepcopy
from pathlib import Path

try:
    from .expression_data import _topic_label, _infer_question_type
except ImportError:
    from expression_data import _topic_label, _infer_question_type


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = ROOT / "templates"


# ─── Grouping Templates (patterns only, NO display text) ────────────────────
# These serve as FALLBACK when ai_dimensions is not provided.

EFFICACY_GROUPING = {
    "template_type": "用药体验与疗效反馈",
    "template_doc": str(TEMPLATE_DIR / "efficacy-report-template.docx"),
    "header_title_suffix": "用药体验与疗效反馈患者调查问卷分析报告",
    "report_title_suffix": "用药体验与疗效反馈患者调查问卷分析报告",
    "dimension_count": 7,
    "project_dimensions": [
        "药品疗效",
        "药品安全性",
        "用药行为与习惯",
        "用药便利性",
        "药品经济性",
        "药品可及性",
        "用药指导信息评价",
    ],
    "key_issue_preferred_sections": ["4.1", "4.2", "4.5", "4.3"],
    "result_intro_template": (
        "本次调查采用问卷调查方式，共有{question_count}个问题，"
        "本报告从{dimensions_list}等{dimension_count}个维度展开统计分析。"
    ),
    "sections": [
        {
            "section_number": "4.1",
            "section_title": "药品疗效",
            "section_intro": "本维度用于观察患者对控压效果的主观感知。",
            "subtopics": [
                {
                    "patterns": [r"血压控制", r"控压"],
                    "subtitle": "血压控制效果分析",
                    "chart_type": "pie",
                    "chart_style_profile": "efficacy_pie",
                    "include_chart": True,
                }
            ],
        },
        {
            "section_number": "4.2",
            "section_title": "药品安全性",
            "section_intro": "本维度用于观察患者对常见不适反应的主观感知。",
            "subtopics": [
                {
                    "patterns": [r"头晕", r"头痛"],
                    "subtitle": "头晕头痛不良反应分析",
                    "chart_type": "pie",
                    "chart_style_profile": "safety_pie",
                    "include_chart": True,
                },
                {
                    "patterns": [r"口渴", r"多尿"],
                    "subtitle": "口渴多尿不良反应分析",
                    "chart_type": None,
                    "chart_style_profile": None,
                    "include_chart": False,
                },
            ],
        },
        {
            "section_number": "4.3",
            "section_title": "用药行为与习惯",
            "section_intro": "本维度用于观察患者的长期行为执行情况。",
            "subtopics": [
                {
                    "patterns": [r"渠道", r"购买"],
                    "subtitle": "购药渠道分析",
                    "chart_type": None,
                    "chart_style_profile": None,
                    "include_chart": False,
                },
                {
                    "patterns": [r"剂量", r"医嘱"],
                    "subtitle": "剂量遵循情况分析",
                    "chart_type": "bar3d",
                    "chart_style_profile": "behavior_bar",
                    "include_chart": True,
                },
                {
                    "patterns": [r"同时服用", r"联合用药"],
                    "subtitle": "联合用药情况分析",
                    "chart_type": None,
                    "chart_style_profile": None,
                    "include_chart": False,
                },
                {
                    "patterns": [r"咨询过医生", r"确认", r"冲突"],
                    "subtitle": "联合用药咨询情况分析",
                    "chart_type": None,
                    "chart_style_profile": None,
                    "include_chart": False,
                },
                {
                    "patterns": [r"监测血压", r"监测频率"],
                    "subtitle": "血压监测频率分析",
                    "chart_type": None,
                    "chart_style_profile": None,
                    "include_chart": False,
                },
            ],
        },
        {
            "section_number": "4.4",
            "section_title": "用药便利性",
            "section_intro": "本维度用于观察频率与包装体验。",
            "subtopics": [
                {
                    "patterns": [r"频率"],
                    "subtitle": "服药频率满意度分析",
                    "chart_type": None,
                    "chart_style_profile": None,
                    "include_chart": False,
                },
                {
                    "patterns": [r"包装", r"取用", r"便利"],
                    "subtitle": "药品包装便利性分析",
                    "chart_type": None,
                    "chart_style_profile": None,
                    "include_chart": False,
                },
            ],
        },
        {
            "section_number": "4.5",
            "section_title": "药品经济性",
            "section_intro": "本维度用于观察价格感知。",
            "subtopics": [
                {
                    "patterns": [r"价格", r"负担", r"承受"],
                    "subtitle": "价格负担影响分析",
                    "chart_type": None,
                    "chart_style_profile": None,
                    "include_chart": False,
                }
            ],
        },
        {
            "section_number": "4.6",
            "section_title": "药品可及性",
            "section_intro": "本维度用于观察供应稳定性。",
            "subtopics": [
                {
                    "patterns": [r"供应", r"缺货", r"买到"],
                    "subtitle": "药品供应稳定性分析",
                    "chart_type": None,
                    "chart_style_profile": None,
                    "include_chart": False,
                }
            ],
        },
        {
            "section_number": "4.7",
            "section_title": "用药指导信息评价",
            "section_intro": "本维度用于观察说明信息和指导支持。",
            "subtopics": [
                {
                    "patterns": [r"说明书", r"用法用量", r"不良反应"],
                    "subtitle": "说明书信息清晰度分析",
                    "chart_type": None,
                    "chart_style_profile": None,
                    "include_chart": False,
                },
                {
                    "patterns": [r"指导", r"详细", r"准确"],
                    "subtitle": "用药指导详细准确性分析",
                    "chart_type": None,
                    "chart_style_profile": None,
                    "include_chart": False,
                },
            ],
        },
    ],
}


ADHERENCE_GROUPING = {
    "template_type": "依从性与用药习惯",
    "template_doc": str(TEMPLATE_DIR / "efficacy-report-template.docx"),
    "header_title_suffix": "依从性与用药习惯患者调查问卷分析报告",
    "report_title_suffix": "依从性与用药习惯患者调查问卷分析报告",
    "dimension_count": 4,
    "project_dimensions": [
        "药物认知与信息获取",
        "用药行为与自我管理",
        "依从性与提醒支持",
        "健康教育与支持需求",
    ],
    "key_issue_preferred_sections": ["4.2", "4.3", "4.1", "4.4"],
    "result_intro_template": (
        "本次调查采用问卷调查方式，共有{question_count}个问题，"
        "本报告从{dimensions_list}等{dimension_count}个维度展开统计分析。"
    ),
    "sections": [
        {
            "section_number": "4.1",
            "subtopics": [
                {
                    "patterns": [r"作用", r"了解", r"认知"],
                    "subtitle": "药物认知情况分析",
                    "chart_type": "pie",
                    "chart_style_profile": "efficacy_pie",
                    "include_chart": True,
                },
                {
                    "patterns": [r"获取", r"来源", r"说明书"],
                    "subtitle": "信息获取来源分析",
                    "chart_type": None,
                    "chart_style_profile": None,
                    "include_chart": False,
                },
            ],
            "section_title": "药物认知与信息获取",
            "section_intro": "本维度用于观察患者对药物作用的了解程度及信息来源结构。",
        },
        {
            "section_number": "4.2",
            "subtopics": [
                {
                    "patterns": [r"剂量", r"服药"],
                    "subtitle": "剂量执行情况分析",
                    "chart_type": "bar3d",
                    "chart_style_profile": "behavior_bar",
                    "include_chart": True,
                },
                {
                    "patterns": [r"监测", r"饮食", r"饮酒"],
                    "subtitle": "自我管理行为分析",
                    "chart_type": None,
                    "chart_style_profile": None,
                    "include_chart": False,
                },
            ],
            "section_title": "用药行为与自我管理",
            "section_intro": "本维度用于观察患者在服药执行与日常管理中的行为表现。",
        },
        {
            "section_number": "4.3",
            "subtopics": [
                {
                    "patterns": [r"提醒"],
                    "subtitle": "服药提醒方式分析",
                    "chart_type": "pie",
                    "chart_style_profile": "safety_pie",
                    "include_chart": True,
                },
                {
                    "patterns": [r"依从", r"坚持规律"],
                    "subtitle": "规律服药坚持性分析",
                    "chart_type": None,
                    "chart_style_profile": None,
                    "include_chart": False,
                },
            ],
            "section_title": "依从性与提醒支持",
            "section_intro": "本维度用于观察患者的规律服药意识及提醒支持需求。",
        },
        {
            "section_number": "4.4",
            "subtopics": [
                {
                    "patterns": [r"讲座", r"培训", r"参加", r"兴趣"],
                    "subtitle": "健康教育参与意愿分析",
                    "chart_type": None,
                    "chart_style_profile": None,
                    "include_chart": False,
                },
            ],
            "section_title": "健康教育与支持需求",
            "section_intro": "本维度用于观察患者对健康教育活动和后续支持方式的接受度。",
        },
    ],
}


# ─── Helpers ─────────────────────────────────────────────────────────────────

def question_ref(number: int) -> str:
    return f"q{number:02d}"


def detect_template_type(questionnaire: dict) -> str:
    corpus = " ".join(str(item.get("question", "")) for item in questionnaire.get("questions", []))
    efficacy_hits = len(re.findall(r"血压控制|头晕|头痛|口渴|多尿|价格|供应|说明书|包装|购药渠道", corpus))
    adherence_hits = len(re.findall(r"依从|漏服|自行调整|储存方法|忘记服药|记录每日服药|提醒自己服药|坚持规律|健康教育", corpus))
    if adherence_hits > efficacy_hits:
        return ADHERENCE_GROUPING["template_type"]
    if efficacy_hits:
        return EFFICACY_GROUPING["template_type"]
    return ADHERENCE_GROUPING["template_type"]


def _grouping_config(template_type: str) -> dict:
    base = EFFICACY_GROUPING if template_type == EFFICACY_GROUPING["template_type"] else ADHERENCE_GROUPING
    return deepcopy(base)


def _validate_no_duplicate_refs(sections: list[dict]) -> None:
    """Ensure each question_ref appears in at most one subtopic."""
    seen = {}
    for sec in sections:
        for st in sec.get("subtopics", []):
            for ref in st.get("question_refs", []):
                if ref in seen:
                    prev_sec = seen[ref]["section_number"]
                    prev_st = seen[ref]["subtopic_index"]
                    cur_sec = sec["section_number"]
                    raise ValueError(
                        f"Duplicate question_ref: {ref} appears in both "
                        f"section {prev_sec} subtopic[{prev_st}] and "
                        f"section {cur_sec} subtopic[{st['subtopic_index']}]"
                    )
                seen[ref] = {
                    "section_number": sec["section_number"],
                    "subtopic_index": st["subtopic_index"],
                }


def _validate_grouping_config(config: dict, sections_out: list[dict]) -> None:
    project_dimensions = config.get("project_dimensions", [])
    configured_dimension_count = config.get("dimension_count")
    if len(project_dimensions) != len(sections_out):
        raise ValueError(
            "Grouping config is inconsistent: project_dimensions count does not match output sections count."
        )
    if configured_dimension_count != len(project_dimensions):
        raise ValueError(
            "Grouping config is inconsistent: dimension_count does not match project_dimensions count."
        )


def _build_from_ai_dimensions(ai_dimensions: dict, questionnaire: dict) -> list[dict]:
    """Build sections from ai_dimensions front matter.

    ai_dimensions format:
    {
        "dimensions": [
            {
                "name": "药物认知与信息获取",
                "intro": "本维度用于观察患者对药物作用的了解程度及信息来源结构。",
                "subtopics": [
                    {"patterns": ["作用", "了解", "认知"], "subtitle": "药物认知情况分析"},
                    {"patterns": ["获取", "来源", "说明书"], "subtitle": "信息获取来源分析"},
                ],
                "charts": [
                    {"patterns": ["作用", "认知"], "chart_type": "pie", "chart_style_profile": "efficacy_pie"}
                ]
            },
            ...
        ]
    }
    """
    dimensions = ai_dimensions.get("dimensions", [])
    all_questions = questionnaire.get("questions", [])
    global_matched_refs = set()
    sections_out = []
    chart_index = 1

    for dim_idx, dimension in enumerate(dimensions):
        section_number = f"4.{dim_idx + 1}"
        section_question_refs = []
        active_subtopics = []
        visual_groups = []
        st_idx = 0

        chart_specs = dimension.get("charts", [])

        for st_def in dimension.get("subtopics", []):
            patterns = st_def.get("patterns", [])
            subtitle = st_def.get("subtitle", "")

            matched_refs = []
            for question in all_questions:
                ref = question_ref(int(question["number"]))
                if ref in global_matched_refs:
                    continue
                text = str(question.get("question", ""))
                match = any(re.search(pattern, text) for pattern in patterns)
                if match:
                    matched_refs.append(ref)
                    global_matched_refs.add(ref)

            if not matched_refs:
                continue

            section_question_refs.extend(matched_refs)

            for qi, ref in enumerate(matched_refs):
                question_obj = next(
                    (q for q in all_questions if question_ref(int(q["number"])) == ref),
                    None,
                )
                chart_type = None
                chart_style_profile = None
                include_chart = False
                for cs in chart_specs:
                    if any(re.search(p, str(question_obj.get("question", ""))) for p in cs.get("patterns", [])):
                        chart_type = cs.get("chart_type")
                        chart_style_profile = cs.get("chart_style_profile")
                        include_chart = True
                        break

                if len(matched_refs) == 1:
                    derived_subtitle = subtitle
                else:
                    if question_obj and question_obj.get("question"):
                        question_text = str(question_obj["question"])
                        question_type = _infer_question_type(question_text)
                        mapped_label = _topic_label(question_text, question_type)
                        derived_subtitle = f"{mapped_label}分析"
                    else:
                        derived_subtitle = f"{subtitle}（{qi + 1}）"

                chart_ref = None
                if include_chart and qi == 0:
                    chart_ref = f"chart_{chart_index:02d}"
                    chart_index += 1

                visual_groups.append({
                    "question_ref": ref,
                    "chart_ref": chart_ref,
                    "chart_type": chart_type if qi == 0 else None,
                    "chart_style_profile": chart_style_profile if qi == 0 else None,
                })
                active_subtopics.append({
                    "subtopic_index": st_idx,
                    "subtitle": derived_subtitle,
                    "question_refs": [ref],
                    "chart_type": chart_type if qi == 0 else None,
                    "chart_style_profile": chart_style_profile if qi == 0 else None,
                })
                st_idx += 1

        sections_out.append({
            "section_number": section_number,
            "section_title": dimension.get("name", ""),
            "section_intro": dimension.get("intro", ""),
            "question_refs": section_question_refs,
            "subtopics": active_subtopics,
            "visual_groups": visual_groups,
        })

    # Orphan questions go to the last dimension
    if sections_out:
        orphan_refs = []
        for question in all_questions:
            ref = question_ref(int(question["number"]))
            if ref not in global_matched_refs:
                orphan_refs.append(ref)
                global_matched_refs.add(ref)

        last_section = sections_out[-1]
        for ref in orphan_refs:
            last_section["question_refs"].append(ref)
            question_obj = next(
                (q for q in all_questions if question_ref(int(q["number"])) == ref),
                None,
            )
            if question_obj and question_obj.get("question"):
                question_text = str(question_obj["question"])
                question_type = _infer_question_type(question_text)
                mapped_label = _topic_label(question_text, question_type)
                derived_subtitle = f"{mapped_label}分析"
            else:
                derived_subtitle = "其他问题分析"
            last_section["subtopics"].append({
                "subtopic_index": len(last_section["subtopics"]),
                "subtitle": derived_subtitle,
                "question_refs": [ref],
                "chart_type": None,
                "chart_style_profile": None,
            })
            last_section["visual_groups"].append({
                "question_ref": ref,
                "chart_ref": None,
                "chart_type": None,
                "chart_style_profile": None,
            })

    return sections_out


# ─── Core: cluster questions into dimension/subtopic slots ──────────────────

def cluster_dimensions(questionnaire: dict, ai_dimensions: dict | None = None) -> dict:
    """Group questions into dimension sections and subtopic slots.

    When ai_dimensions is provided (from report_content.md front matter),
    it takes precedence over the hardcoded grouping templates.

    Returns a dict with:
      - template_type, template_doc, header_title_suffix, report_title_suffix
      - result_intro_template (with {question_count}, {dimensions_list}, {dimension_count})
      - dimension_count
      - sections: list of {section_number, question_refs, subtopics, visual_groups}
        where subtopics have {subtopic_index, question_refs, chart_type, chart_style_profile}
        and visual_groups have {question_ref, chart_ref, chart_type, chart_style_profile}

    Display text is part of the grouping contract and is supplied by program
    rules, not by AI drafts.
    """
    template_type = detect_template_type(questionnaire)
    config = _grouping_config(template_type)

    if ai_dimensions:
        sections_out = _build_from_ai_dimensions(ai_dimensions, questionnaire)
        dimension_names = [sec["section_title"] for sec in sections_out]
        dimension_count = len(sections_out)
        key_issue_preferred = [f"4.{i+1}" for i in range(min(2, dimension_count))]
    else:
        # Phase 1: match questions to subtopic slots (legacy path)
        for question in questionnaire.get("questions", []):
            ref = question_ref(int(question["number"]))
            text = str(question.get("question", ""))
            matched = False
            for section in config["sections"]:
                for subtopic in section["subtopics"]:
                    if any(re.search(pattern, text) for pattern in subtopic["patterns"]):
                        subtopic.setdefault("question_refs", []).append(ref)
                        matched = True
                        break
                if matched:
                    break
            if not matched:
                config["sections"][-1]["subtopics"][-1].setdefault("question_refs", []).append(ref)

        # Phase 2: build output sections
        chart_index = 1
        sections_out = []
        for section in config["sections"]:
            section_question_refs = []
            active_subtopics = []
            visual_groups = []
            st_idx = 0
            for subtopic in section["subtopics"]:
                refs = subtopic.get("question_refs", [])
                if not refs:
                    continue
                section_question_refs.extend(refs)
                if len(refs) == 1:
                    chart_ref = None
                    if subtopic.get("include_chart"):
                        chart_ref = f"chart_{chart_index:02d}"
                        chart_index += 1
                    visual_groups.append({
                        "question_ref": refs[0],
                        "chart_ref": chart_ref,
                        "chart_type": subtopic["chart_type"],
                        "chart_style_profile": subtopic["chart_style_profile"],
                    })
                    active_subtopics.append({
                        "subtopic_index": st_idx,
                        "subtitle": subtopic["subtitle"],
                        "question_refs": refs,
                        "chart_type": subtopic.get("chart_type"),
                        "chart_style_profile": subtopic.get("chart_style_profile"),
                    })
                    st_idx += 1
                else:
                    for qi, ref in enumerate(refs):
                        chart_ref = None
                        if qi == 0 and subtopic.get("include_chart"):
                            chart_ref = f"chart_{chart_index:02d}"
                            chart_index += 1
                        visual_groups.append({
                            "question_ref": ref,
                            "chart_ref": chart_ref,
                            "chart_type": subtopic["chart_type"] if qi == 0 else None,
                            "chart_style_profile": subtopic["chart_style_profile"] if qi == 0 else None,
                        })
                        question_obj = next(
                            (q for q in questionnaire.get("questions", [])
                             if question_ref(int(q["number"])) == ref),
                            None,
                        )
                        if question_obj and question_obj.get("question"):
                            question_text = str(question_obj["question"])
                            question_type = _infer_question_type(question_text)
                            mapped_label = _topic_label(question_text, question_type)
                            derived_subtitle = f"{mapped_label}分析"
                        else:
                            derived_subtitle = f"{subtopic['subtitle']}（{qi + 1}）"
                        active_subtopics.append({
                            "subtopic_index": st_idx,
                            "subtitle": derived_subtitle,
                            "question_refs": [ref],
                            "chart_type": subtopic.get("chart_type") if qi == 0 else None,
                            "chart_style_profile": subtopic.get("chart_style_profile") if qi == 0 else None,
                        })
                        st_idx += 1
            sections_out.append({
                "section_number": section["section_number"],
                "section_title": section["section_title"],
                "section_intro": section["section_intro"],
                "question_refs": section_question_refs,
                "subtopics": active_subtopics,
                "visual_groups": visual_groups,
            })

        _validate_no_duplicate_refs(sections_out)
        _validate_grouping_config(config, sections_out)
        dimension_names = config["project_dimensions"]
        dimension_count = config["dimension_count"]
        key_issue_preferred = config["key_issue_preferred_sections"]

    if ai_dimensions:
        _validate_no_duplicate_refs(sections_out)

    result_intro_template = (
        "本次调查采用问卷调查方式，共有{question_count}个问题，"
        "本报告从{dimensions_list}等{dimension_count}个维度展开统计分析。"
    )

    return {
        "template_type": config["template_type"],
        "template_doc": config["template_doc"],
        "header_title_suffix": config["header_title_suffix"],
        "report_title_suffix": config["report_title_suffix"],
        "dimension_count": dimension_count,
        "project_dimensions": dimension_names,
        "key_issue_preferred_sections": key_issue_preferred,
        "result_intro_template": result_intro_template,
        "sections": sections_out,
    }


# ─── CLI ────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Group questionnaire questions into dimension slots.")
    parser.add_argument("questionnaire_json")
    parser.add_argument("-o", "--output", required=True)
    parser.add_argument("--ai-dimensions", default=None, help="Path to ai_dimensions JSON file (optional)")
    args = parser.parse_args()
    questionnaire = json.loads(Path(args.questionnaire_json).read_text(encoding="utf-8"))
    ai_dimensions = None
    if args.ai_dimensions:
        ai_dimensions = json.loads(Path(args.ai_dimensions).read_text(encoding="utf-8"))
    result = cluster_dimensions(questionnaire, ai_dimensions=ai_dimensions)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
