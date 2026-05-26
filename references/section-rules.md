# Section Rules

## Fixed Structure
1. `问卷调研服务结算`
2. `目录`
3. `前言`
4. 报告大标题
5. `项目背景`
6. `项目开展情况`
7. `问卷说明`
8. `问卷结果分析`
9. `调研结果`
10. `附件1`
11. `附件2`
12. `免责申明`

## Preface
- Must be exactly `2` paragraphs.
- Total length must be tightly controlled around `400` Chinese characters; reject loose `320-520` style ranges.
- Information order is fixed: `疾病/品类背景 -> 产品价值 -> 区域与对象 -> 调研目的 -> 应用价值`.
- Must mention the region and patient audience.
- Must use formal report prose; do not use marketing language, empty套话, or unrelated generic antihypertensive fallback text.

## Project Background
- Must be exactly `2` paragraphs.
- Paragraph 1 covers `宏观背景/区域特征`.
- Paragraph 2 covers `现有数据缺口或问题` and `本次调研必要性`.
- Must mention the region and explain why this project is needed now.
- Must not substantially repeat the preface.

## Result Analysis
- Use fixed sample-aligned `4.x` sections.
- The result-intro dimension names and the stated dimension count must match the actual `4.x` sections exactly.
- The final rendered docx must contain exactly the `4.x` headings from payload, in order; extra template sections must be removed before delivery.
- `用药体验与疗效反馈` must expose exactly `7` dimensions in `4.1-4.7`.
- `问卷结果分析` must include two overview charts before `4.1`: `维度占比饼状图` and `维度横向柱形图`.
- Both overview charts must use the same ordered categories and values, derived from the number of questions grouped into each `4.x` dimension.
- The first overview chart must remain an Office-native pie chart.
- The second overview chart must render as a PNG horizontal bar chart with integer dimension question counts, not percentages.
- The second overview chart must not display a legend or percentage labels; show only dimension names, integer axis ticks, and bar-end count labels.
- Each `4.x` section must contain: section intro, then for each question: subtitle (no index prefix like `(1)`), result table, and one analysis paragraph.
- Subtitles have NO `(1)`/`(2)` numbering prefixes — just the topic name, e.g. "用药原因分析" not "（1）用药原因分析".
- `4.x` heading format: number immediately followed by title with no space, e.g. "4.1用药基础信息" not "4.1 用药基础信息".
- Table format: full page width (pct), header/first-col background `4684D3`, data cells `D9EAF7`, Hanyi Zhongsong 10pt, single line spacing.
- All chapter 4 elements (section headings, subtitles, analysis paragraphs) must have `pageBreakBefore`; subtitles must also have `keepNext`.
- Each subtitle corresponds to exactly 1 question (cluster_dimensions auto-splits multi-question subtopics). Analysis paragraph must be a single paragraph between `250-300` Chinese characters.
- Analysis logic must follow `主结论 -> 解释/风险 -> 收束`; avoid rigid procedural connectors.
- Analysis body must not contain percentages, `占比`, `A/B/C/D`, `选项A/选项B`, `逐项分布`, `从共性特征看`, `建议`, or mechanical option-by-option enumeration.
- `5.1问卷重点问题分析` must keep two native `3D` pie charts for the selected key issues.
- `5.1` and the `问卷结果分析` overview charts must coexist; restoring `5.1` charts must not delete or repurpose the two overview chart slots.
- Do not output the old `引言 / 数据信息分析 / 反馈意见分析 / 综合分析与建议 / 附件-问卷题目内容` system.
- `用药体验与疗效反馈` template uses 7 `4.x` sections and fixed subtitle names.
- `依从性与用药习惯` template uses 4 `4.x` sections and fixed subtitle names.

## Attachment 1
- Rebuild `附件1` as complete question blocks between `附件1` and `附件2`; do not line-scan and partially overwrite old template rows.
- Question headings must use `（1） （2） ...` only.
- Strip the source question's raw numeric prefix such as `1.` `6.` `11.` from the attachment heading text.
- Option rows must preserve the original `A. / B. / C. / D.` order for that question and must not bleed across question blocks.

## Final Validation Gate
- `run_report_pipeline.py` must run final docx validation after rendering.
- Validation failure is a hard failure: do not leave a deliverable docx in the requested output path.
- Final validation must check section headings, analysis forbidden terms, attachment order, and visible Word text font.
