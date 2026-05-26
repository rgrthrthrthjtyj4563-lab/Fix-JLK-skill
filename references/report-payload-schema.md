# Report Payload Schema

```json
{
  "meta": {
    "product": "厄贝沙坦氢氯噻嗪片",
    "region": "北京市",
    "time": "2025.10",
    "template_type": "用药体验与疗效反馈"
  },
  "project_background": ["..."],
  "project_execution": ["..."],
  "questionnaire_note": ["..."],
  "result_analysis": {
    "intro": ["本次调查采用问卷调查方式，共有14个问题，本报告从药品疗效、药品安全性、用药行为与习惯、用药便利性、药品经济性、药品可及性、用药指导信息评价等7个维度展开统计分析。"],
    "overview_charts": [
      {
        "chart_ref": "chart_4_overview_pie",
        "chart_type": "pie",
        "render_mode": "office",
        "title": "问卷结果分析维度占比饼状图",
        "categories": ["药品疗效", "药品安全性", "用药行为与习惯", "用药便利性", "药品经济性", "药品可及性", "用药指导信息评价"],
        "values": [1, 2, 5, 2, 1, 1, 2]
      },
      {
        "chart_ref": "chart_4_overview_bar",
        "chart_type": "bar",
        "render_mode": "image",
        "title": "问卷结果分析维度题目数量横向柱形图",
        "categories": ["药品疗效", "药品安全性", "用药行为与习惯", "用药便利性", "药品经济性", "药品可及性", "用药指导信息评价"],
        "values": [1, 2, 5, 2, 1, 1, 2]
      }
    ],
    "sections": [
      {
        "section_number": "4.1",
        "section_title": "药品疗效",
        "section_intro": ["..."],
        "question_refs": ["q01"],
        "visual_groups": [
          {
            "question_ref": "q01",
            "chart_ref": "chart_01",
            "chart_type": "pie",
            "chart_style_profile": "efficacy_pie"
          }
        ],
        "subtopics": [
          {
            "subtitle": "血压控制效果分析",
            "question_refs": ["q01"],
            "paragraphs": ["..."]
          }
        ]
      }
    ]
  },
  "summary": {
    "key_issue_analysis": ["..."],
    "key_issue_items": [
      {
        "question_ref": "q01",
        "heading": "1. 血压控制现状与特征",
        "chart_ref": "chart_key_issue_1",
        "chart_title": "患者血压控制效果",
        "chart_type": "pie",
        "table_data": {},
        "paragraph": "..."
      }
    ],
    "overall_analysis": ["..."],
    "recommendations": ["..."]
  },
  "attachments": {
    "attachment1_name": "厄贝沙坦氢氯噻嗪片用药体验与疗效反馈患者调查问卷",
    "attachment1_questions": [],
    "attachment2_name": "问卷调查明细表"
  },
  "disclaimer": {
    "title": "免责申明",
    "items": [],
    "unit": "北京玖麟空科技有限公司"
  }
}
```

Final docx validation uses this payload as the source of truth for expected `4.x` headings, subtitle analysis paragraphs, attachment question order, and chart counts. A rendered docx that diverges from these payload expectations must be treated as a failed run.
