---
name: "JLK-Pt-skill"
description: "Use when generating patient questionnaire analysis reports for pharmaceutical clients from uploaded survey spreadsheets or questionnaire tables, especially when the output must inherit the original Word template, including TOC, preface, header, title hierarchy, tables, and chart styles."
---

# JLK Patient Report Skill

## When To Use
- 输入是患者问卷数据或问卷统计表。
- 输出必须是 `Word 报告`。
- 报告对外标题统一使用通用名称 `问卷调研分析报告`，不直接暴露内部模板分类名。
- 文档必须继承原模板的页面组件：
  - `问卷调研服务结算`
  - `目录`
  - `前言`
  - 报告大标题
  - 页眉
- 正文结构必须贴合真实模板：
  - `项目背景`
  - `项目开展情况`
  - `问卷说明`
  - `问卷结果分析`
  - `调研结果`
  - `附件1`
  - `附件2`
  - `免责申明`
- `问卷结果分析` 必须使用模板固定 `4.x + 小标题 + 表格 + 分析` 结构，每道题独立为一个分析单元：`小标题 → 统计表 → 分析正文`。多题不得合并在同一小标题下。

## Workflow
1. 用 `scripts/parse_questionnaire.py` 解析附件为 `questionnaire.json`。
2. 用 `scripts/cluster_dimensions.py` 识别问卷属于哪类模板，并生成唯一允许的 `4.x / 标题 / 引言 / 小标题 / 图表点位 / 5.1重点题目` 骨架。
3. AI 按模板章节撰写 `report_content.md`，但只允许提供：
   - `前言` 正文
   - `项目背景` 正文
   - 各 `4.x` 小节的分析正文
   - `5.2 调研结果分析` 正文
   不能决定模板分类、`4.x` 标题、`4.x` 引言、小标题、`5.1` 重点题目或图表点位。
   - `前言` 必须强制为 `2` 段，总字数强制收敛在约 `400` 字区间内，写作顺序固定为：`疾病/品类背景 -> 产品价值 -> 区域与对象 -> 调研目的 -> 应用价值`。
   - `项目背景` 必须为 `2` 段，第一段写 `宏观背景/区域特征`，第二段写 `现有数据缺口/问题` 与 `本次调研必要性`。
   - `前言` 与 `项目背景` 必须采用正式、客观的报告文风，不得写成营销文案、空泛套话或与模板无关的通用降压药兜底表述。
   - `前言` 与 `项目背景` 不得大面积重复；缺少区域、对象、目的或价值落点时，视为不合格草稿。
   - `问卷结果分析` 下每个小标题对应 `1` 道题，分析正文必须为 `1` 段，严格控制在 `250-300` 字之间。`cluster_dimensions.py` 会自动将多题 subtopic 拆分为每题一个 subtopic。
   - 单题分析必须采用 `主结论 -> 解释/风险 -> 收束` 的报告式逻辑，不得写成程序化套话拼接。
   - 单题分析正文不得出现 `A/B/C/D`、`选项A/选项B` 等字母选项列举，应直接使用选项语义或归纳表达。
4. 用 `scripts/build_payload.py` 构建 `report_payload.json`。如果 AI 草稿中的 `4.x` 章节集合、标题或小标题与 `cluster_dimensions` 骨架冲突，必须直接报错，不做兼容。
   - `问卷结果分析` 导语中的维度名称和维度数量必须与 `4.x` 实际章节完全一致。
   - `用药体验与疗效反馈` 模板的 `问卷结果分析` 固定包含 `2` 张概览图：`维度占比饼状图` 与 `维度横向柱形图`。
   - 两张概览图的统计口径统一为各 `4.x` 维度归入的题目数量，维度顺序必须与 `4.1-4.7` 顺序一致。
   - 第一张概览图必须保持原生 Office 饼图；第二张概览图必须改为 PNG 图片形式的“横向柱状图 + 维度题目数量”输出，不能退化为饼图、占比图或依赖 `chart2.xml + Workbook2.xlsx` 的重算结果。
   - `5.1 问卷重点问题分析` 必须保留 `2` 张原生 `3D` 饼图，并与第 `4` 部分的两张概览图并存，不能因为修第 `4` 部分图表而删除 `5.1` 双图。
5. 用 `scripts/render_from_template.py` 基于模板底稿做**对象级替换**输出最终 `docx`。
     - 这是主渲染器，在模板文档中定位锚点并替换内容，不清空正文。
     - 保留模板所有样式：section 断点、页眉、表格、图表、字体。
     - `scripts/render_report.py` 是旧版「清空重写」方案，已弃用。
     - `04_outputs/` 中若存在旧版 `report_content.md / report_final.md / render_report.py` 等文件，只能视为历史脏产物，不能作为当前结构参考。
     - `附件1` 必须按题目块整体重建：题干使用 `（1）（2）...` 顺序号，去掉原题号前缀如 `1.` `6.` `11.`，选项仍保留 `A./B./C./D.` 且必须按原始问卷顺序逐题展开。
6. 运行时优先使用 `scripts/run_report_pipeline.py`，它会为每次生成创建独立运行目录，避免复用固定的 `tmp/docs/content.md` 或 `generated.docx`。
7. `scripts/run_report_pipeline.py` 必须在渲染后调用 `scripts/final_validate_docx.py` 做最终 Word 验收；验收失败时必须直接失败并移除最终交付 docx，只保留运行目录诊断文件。
8. 检查输出必须保留目录、前言、页眉、标题层级、蓝底表格和模板图表风格。
9. `scripts/build_payload.py` 会对 `前言`、`项目背景` 和 `问卷结果分析` 单题正文执行硬校验；段数、字数、区域信息、结构或旧式百分比分析不达标时，pipeline 必须直接失败，不得静默降级。
10. 如果模板底稿缺少第 `4` 部分的第二张概览图位，或维度配置数量与实际 `4.x` 章节不一致，pipeline 必须直接失败。

## Supported Templates
- `用药体验与疗效反馈`
- `依从性与用药习惯`

## Chapter 4 Format Rules (must match reference template)
- `4.x` heading format: `4.1Title` (no space between number and title), font Hanyi Zhongsong 16pt Bold, `pageBreakBefore=true`, `keepNext=true`, line spacing `line=480`.
- Subtitle format: plain text only (no `(1)` index prefix), font Hanyi Zhongsong 12pt Bold, `pageBreakBefore=true`, `keepNext=true`, line spacing `line=600`, `firstLineChars=0` (no first-line indent).
- Analysis paragraph: Hanyi Zhongsong 12pt, justified alignment, first-line indent 2 chars (`firstLineChars=200`), line spacing `line=600`, `pageBreakBefore=true`, `keepNext=true`.
- Table style: `tblW=5000 pct` (full page width), header/first-column bg `4684D3`, data-cell bg `D9EAF7`, row height `atLeast 567 dxa`, font Hanyi Zhongsong 10pt, line spacing `line=240` (single), border color `FFFFFF`.
- Each question follows the fixed pattern: `Subtitle -> Statistics Table -> Analysis Paragraph`. One subtopic contains exactly one question; multi-question stacking under one subtitle is prohibited.

## Output Notes
- 图表必须按模板定义的点位和风格生成，不接受“近似即可”的退化方案。
- 正文版式、目录、页眉、标题层级和表格样式必须继承模板底稿，不沿用旧绿色标题系统。
