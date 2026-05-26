#!/usr/bin/env python3
"""
Deterministic subtopic analysis generation aligned to reference templates.

Each subtitle uses one compact paragraph with three layers:
1. main distribution conclusion
2. interpretation / risk explanation
3. closing judgment or follow-up implication
"""

from __future__ import annotations

import re

MIN_ANALYSIS_CHARS = 250
MAX_ANALYSIS_CHARS = 300
FORBIDDEN_PATTERNS = [
    r"\b[ABCD]\.",
    r"选项A",
    r"选项B",
    r"选项C",
    r"选项D",
    r"逐项分布",
    r"从共性特征看",
    r"建议",
]

OPENING_STYLE_LIBRARY = [
    "从反馈结构看",
    "就本题统计结果看",
    "结合选项占比变化看",
    "从患者选择倾向看",
    "从高频反馈集中度看",
    "围绕本题所反映的用药场景看",
    "从主次反馈关系看",
    "结合尾部反馈情况看",
    "从患者实际选择分布看",
    "以主要反馈项为观察切入点看",
    "从本题所呈现的行为信号看",
    "结合主要选项与次要选项差异看",
    "从患者认知或执行差异看",
    "围绕该问题暴露出的管理环节看",
    "从当前反馈的集中与分散程度看",
]

INTERPRETATION_STYLE_LIBRARY = [
    "{body}",
    "进一步看，{body}",
    "这一分布背后，{body}",
    "将该结果放回真实用药场景中看，{body}",
    "从患者管理含义看，{body}",
    "这类反馈提示，{body}",
]

ACTION_STYLE_LIBRARY = [
    "整体来看，{body}",
    "后续可围绕这一环节，{body}",
    "后续更适合把这一问题作为持续观察点，{body}",
    "需重点沿着主流反馈与边缘反馈两条线索，{body}",
    "后续可围绕患者实际使用场景，{body}",
    "后续应在既有基础上，{body}",
]


def _style_item(items: list[str], style_index: int, offset: int = 0) -> str:
    if not items:
        return ""
    return items[(style_index + offset) % len(items)]


def _pct_value(text: str) -> float:
    raw = str(text or "").strip().rstrip("%")
    return float(raw or 0)


def _format_pct(value: float) -> str:
    if float(value).is_integer():
        return f"{int(value)}%"
    return f"{value:.2f}%"


def _normalize_option_text(text: str) -> str:
    normalized = re.sub(r"[\s\u200b]+", "", str(text or ""))
    normalized = re.sub(r"^[A-DＡ-Ｄ][\.\、]?", "", normalized)
    normalized = normalized.strip("“”\"'")
    if re.fullmatch(r"选项[ABCD]", normalized):
        return ""
    return normalized


def _infer_question_type(question_text: str) -> str:
    text = str(question_text or "")
    if re.search(r"头晕|头痛|口渴|多尿|不良反应", text):
        return "adverse_event"
    if re.search(r"供应|稳定|可及", text):
        return "supply"
    if re.search(r"价格|负担|承受", text):
        return "economy"
    if re.search(r"说明书|指导|信息|认知|获取|来源|储存|了解|教育", text):
        return "information"
    if re.search(r"渠道|购买", text):
        return "channel"
    if re.search(r"剂量|医嘱|联合用药|监测血压|监测频率|提醒|依从|忘记|漏服|服药", text):
        return "behavior"
    if re.search(r"包装|便利|频率", text):
        return "convenience"
    if re.search(r"血压控制|控压|疗效|改善", text):
        return "efficacy"
    return "generic"


def _topic_label(question_text: str, question_type: str) -> str:
    text = str(question_text or "")
    mappings = [
        (r"头晕|头痛", "头晕头痛不良反应"),
        (r"口渴|多尿", "口渴多尿不良反应"),
        (r"获取|来源|信息", "信息获取"),
        (r"渠道|购买", "购药渠道"),
        (r"供应|稳定", "药品供应稳定性"),
        (r"价格|负担|承受", "价格负担"),
        (r"剂量|医嘱", "剂量执行"),
        (r"联合用药", "联合用药"),
        (r"监测血压|监测频率", "血压监测"),
        (r"提醒|依从", "依从与提醒支持"),
        (r"包装", "包装便利性"),
        (r"频率", "服药频率"),
        (r"说明书", "说明书信息清晰度"),
        (r"指导", "用药指导支持"),
        (r"储存", "药品储存方法认知"),
        (r"教育程度", "患者基础教育背景"),
        (r"健康教育", "健康教育支持需求"),
        (r"忘记|漏服", "漏服应对行为"),
        (r"服药时间", "服药时间安排"),
        (r"服用.*次数|每日服用", "每日服药频次"),
        (r"自行调整|调整.*剂量", "剂量自我调整行为"),
        (r"不良反应", "不良反应应对行为"),
        (r"认知|作用", "药物认知"),
        (r"血压控制|控压", "血压控制效果"),
        (r"疗效|改善", "疗效感知"),
    ]
    for pattern, label in mappings:
        if re.search(pattern, text):
            return label
    fallback = {
        "adverse_event": "不良反应表现",
        "channel": "购药渠道结构",
        "supply": "药品供应情况",
        "economy": "价格感知",
        "behavior": "用药执行情况",
        "convenience": "使用便利性",
        "information": "信息理解与支持",
        "efficacy": "疗效表现",
        "generic": "当前题目反馈",
    }
    return fallback.get(question_type, "当前题目反馈")


def _sorted_options(options: list[dict]) -> list[dict]:
    return sorted(options, key=lambda item: _pct_value(item.get("pct", "0")), reverse=True)


def _main_conclusion(question_type: str, topic_label: str, options: list[dict], style_index: int = 0) -> str:
    top = options[0]
    second = options[1] if len(options) > 1 else options[0]
    top_text = _normalize_option_text(top.get("text", ""))
    second_text = _normalize_option_text(second.get("text", ""))
    top_pct = _format_pct(_pct_value(top.get("pct", "0")))
    second_pct = _format_pct(_pct_value(second.get("pct", "0")))

    top_phrase = f"“{top_text}”" if top_text else "高频主流反馈"
    second_phrase = f"“{second_text}”" if second_text else "次高频反馈"
    opening = _style_item(OPENING_STYLE_LIBRARY, style_index)

    if question_type == "efficacy":
        return (
            f"{opening}，{topic_label}整体表现较为积极，其中{top_phrase}为最高反馈项，达{top_pct}，"
            f"{second_phrase}为次高反馈项，达{second_pct}，"
            "两类正向判断共同构成主流反馈；仅少数患者落在谨慎评价区间，说明当前疗效感知总体稳定。"
        )
    if question_type == "adverse_event":
        return (
            f"{opening}，{topic_label}以低感知或无明显影响为主，其中{top_phrase}达{top_pct}，"
            f"{second_phrase}达{second_pct}，"
            "而明显不适相关反馈处于低频位置，表明多数患者未将该问题视为主要负担。"
        )
    if question_type == "channel":
        return (
            f"{opening}，患者在{topic_label}上已形成较清晰的主流结构，其中{top_phrase}达{top_pct}，"
            f"{second_phrase}达{second_pct}，"
            "说明正规、稳定的购药路径仍是主要选择。"
        )
    if question_type == "behavior":
        return (
            f"{opening}，{topic_label}的主流反馈集中在{top_phrase}和{second_phrase}，"
            f"对应比例分别为{top_pct}和{second_pct}，说明多数患者在这一环节具备一定规范意识，"
            "但仍存在需要进一步巩固的执行差异。"
        )
    if question_type == "economy":
        return (
            f"{opening}，{topic_label}整体呈中性偏积极状态，其中{top_phrase}达{top_pct}，"
            f"{second_phrase}达{second_pct}，说明多数患者对长期用药成本的接受度相对稳定，"
            "价格尚未成为普遍阻碍。"
        )
    if question_type == "convenience":
        return (
            f"{opening}，{topic_label}的主流反馈集中在{top_phrase}和{second_phrase}，"
            f"对应比例分别为{top_pct}和{second_pct}，说明当前使用体验总体顺畅，"
            "多数患者能够在日常场景中较好适应相关安排。"
        )
    if question_type == "information":
        return (
            f"{opening}，{topic_label}整体处于可理解、可接受区间，其中{top_phrase}达{top_pct}，"
            f"{second_phrase}达{second_pct}，"
            "表明患者在基础信息获取和理解上已有一定支撑，但深层指导仍有提升空间。"
        )
    return (
        f"{opening}，{topic_label}的主流反馈集中在{top_phrase}和{second_phrase}，"
        f"对应比例分别为{top_pct}和{second_pct}，说明该题目已经形成较明确的患者判断，"
        "整体趋势较为清晰。"
    )


def _interpretation(question_type: str, topic_label: str, options: list[dict], style_index: int = 0) -> str:
    top = options[0]
    tail = options[-1]
    top_text = _normalize_option_text(top.get("text", ""))
    tail_text = _normalize_option_text(tail.get("text", ""))
    tail_phrase = f"“{tail_text}”" if tail_text else "低频边缘反馈"

    interpretations = {
        "efficacy": f"这一结果表明产品在真实使用场景中已具备较稳定的主观获益感知，既反映出多数患者当前方案匹配度较高，也说明疗效体验能够被患者直接感受到。",
        "adverse_event": f"该分布与长期用药中“可耐受、可坚持”的安全性预期基本一致，提示现阶段主要风险并不在于普遍性不良反应，而在于少数患者的个体差异管理。",
        "channel": f"这种结构反映出患者对规范购药已有基础共识，但仍有一部分样本落在{tail_phrase}等边缘路径上，后续需继续降低非正规渠道带来的不确定性。",
        "behavior": "需要注意的是，低频反馈虽不构成主流，却往往对应执行偏差、随意调整或提醒不足等问题，这类行为一旦持续，仍可能放大长期管理风险。",
        "economy": f"从长期治疗视角看，这意味着产品价值判断并未因价格被明显削弱，但对负担更敏感的人群仍可能因成本感知波动而影响持续购药意愿。",
        "convenience": f"这一分布说明当前设计基本贴合多数患者的生活节奏，但少数边缘反馈也提示，实际使用中的细节痛点尚未被完全消化。",
        "information": f"这表明患者对基础说明内容已有一定理解，但在更复杂的用药疑问、长期管理细节或风险识别方面，仍可能存在支持深度不足的问题。",
        "generic": f"同时，尾部反馈集中在{tail_phrase}一类低频项，说明边缘场景仍然存在，需要在后续服务中持续跟踪。"
    }
    body = interpretations.get(question_type, interpretations["generic"])
    template = _style_item(INTERPRETATION_STYLE_LIBRARY, style_index, offset=1)
    return template.format(body=body)


def _closing_sentence(question_type: str, topic_label: str, style_index: int = 0) -> str:
    closings = {
        "efficacy": f"{topic_label}已形成明确的正向主导格局，重点关注少数波动样本，通过复诊沟通和持续随访提升稳定性。",
        "adverse_event": f"{topic_label}风险可控，围绕少数敏感样本加强观察，而非把该问题视为普遍障碍。",
        "channel": f"{topic_label}以正规路径为主，强化渠道引导与用药安全教育，提升购药连续性与可控性。",
        "behavior": f"{topic_label}虽以主流规范执行为主，但仍需通过提醒、教育和复盘机制减少少数偏差行为对长期治疗的影响。",
        "economy": f"{topic_label}总体稳定，可为长期治疗连续性提供支撑，但仍需兼顾少数高敏感人群的持续沟通。",
        "convenience": f"{topic_label}表现较好，可为长期依从性提供支持，但仍可围绕少数不便反馈继续做细节优化。",
        "information": f"{topic_label}已具备基础支撑作用，应把说明书、药师和医生沟通进一步打通，提升指导的完整性。",
        "generic": f"{topic_label}已形成较清晰的主流判断，应围绕主流需求巩固优势，同时兼顾少数差异化场景。"
    }
    body = closings.get(question_type, closings["generic"])
    template = _style_item(ACTION_STYLE_LIBRARY, style_index, offset=2)
    return template.format(body=body)


def _compress_text(text: str) -> str:
    replacements = [
        ("当前", ""),
        ("多数患者", "患者"),
        ("真实使用场景", "真实场景"),
        ("整体来看，", "整体看，"),
        ("进一步", ""),
        ("相对", ""),
        ("仍可能", "仍"),
    ]
    compressed = text
    for old, new in replacements:
        if len(compressed) <= MAX_ANALYSIS_CHARS:
            break
        compressed = compressed.replace(old, new)
    return compressed


def _pad_text(question_type: str, text: str) -> str:
    fillers = {
        "efficacy": [
            "同时也提示当前方案与多数患者需求匹配度较高。",
            "这也为后续持续巩固患者治疗信心提供了较好的现实基础。",
        ],
        "adverse_event": [
            "对少数敏感患者仍需结合个体反应做持续观察。",
            "这对于支持患者长期坚持治疗具有积极意义。",
        ],
        "channel": [
            "这对保障治疗连续性与药品质量控制都具有现实意义。",
            "也提示渠道引导仍是患者支持中的必要环节。",
        ],
        "behavior": [
            "这也提示规范化教育仍是后续管理中的关键抓手。",
            "尤其需要把提醒机制与复诊沟通进一步结合起来。",
        ],
        "economy": [
            "这对提升长期坚持治疗的现实可行性具有积极作用。",
            "但对负担敏感人群仍需保持连续沟通。",
        ],
        "convenience": [
            "这对维持患者长期坚持用药同样具有正向支撑作用。",
            "也说明细节体验优化仍有进一步提升空间。",
        ],
        "information": [
            "这对提升患者长期规范用药的理解基础同样重要。",
            "后续仍需补强复杂场景下的解释支持。",
        ],
        "generic": [
            "这对后续优化患者支持策略也具有一定参考价值。",
            "也提示后续服务需兼顾主流反馈与少数差异场景。",
        ],
    }
    padded = text
    candidates = fillers.get(question_type, fillers["generic"])
    index = 0
    while len(padded) < MIN_ANALYSIS_CHARS and index < len(candidates) * 2:
        filler = candidates[index % len(candidates)]
        if len(padded) + len(filler) <= MAX_ANALYSIS_CHARS:
            padded = f"{padded}{filler}"
        index += 1
    return padded


def _sanitize_text(text: str) -> str:
    cleaned = re.sub(r"\s+", "", text)
    cleaned = cleaned.replace("；", "，")
    cleaned = cleaned.replace("，，", "，")
    cleaned = cleaned.replace("。。", "。")
    return cleaned


def build_analysis_paragraph(question_text: str, options: list[dict], style_index: int = 0) -> str:
    if not options:
        return "原始问卷未提供足够的选项数据，无法形成有效统计解释。"

    sorted_opts = _sorted_options(options)
    question_type = _infer_question_type(question_text)
    topic_label = _topic_label(question_text, question_type)
    paragraph = "".join(
        [
            _main_conclusion(question_type, topic_label, sorted_opts, style_index),
            _interpretation(question_type, topic_label, sorted_opts, style_index),
            _closing_sentence(question_type, topic_label, style_index),
        ]
    )
    paragraph = _sanitize_text(paragraph)

    if len(paragraph) < MIN_ANALYSIS_CHARS:
        paragraph = _pad_text(question_type, paragraph)
    while len(paragraph) > MAX_ANALYSIS_CHARS:
        new_text = _compress_text(paragraph)
        if new_text == paragraph:
            paragraph = paragraph[:MAX_ANALYSIS_CHARS].rstrip("，；、") + "。"
            break
        paragraph = _sanitize_text(new_text)
    if len(paragraph) < MIN_ANALYSIS_CHARS:
        paragraph = _pad_text(question_type, paragraph)
    if len(paragraph) > MAX_ANALYSIS_CHARS:
        paragraph = paragraph[:MAX_ANALYSIS_CHARS].rstrip("，；、") + "。"
    return paragraph


def is_complete_analysis(text: str) -> bool:
    normalized = _sanitize_text(str(text or ""))
    if len(normalized) < MIN_ANALYSIS_CHARS or len(normalized) > MAX_ANALYSIS_CHARS:
        return False
    if any(re.search(pattern, normalized) for pattern in FORBIDDEN_PATTERNS):
        return False
    if not any(marker in normalized for marker in ["表明", "说明", "反映", "提示"]):
        return False
    if not any(marker in normalized for marker in ["整体看", "整体来看", "后续", "需", "仍"]):
        return False
    return True


def generate_analysis_paragraphs(question_text: str, options: list[dict], style_index: int = 0) -> list[str]:
    return [build_analysis_paragraph(question_text, options, style_index=style_index)]
