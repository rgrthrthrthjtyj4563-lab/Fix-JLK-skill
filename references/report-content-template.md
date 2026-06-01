# report_content.md 草稿模板

AI 生成 `report_content.md` 时必须严格按此模板结构填充。
程序只负责维度骨架、校验、渲染和 Word 模板继承；正文必须全部由 AI 提供。

---

## 模板

```markdown
---
product: （品种名）
region: （地区名）
survey_period: （如 2025年03月01日——2025年03月31日）
theme: （固定维度表中的 theme_name，或留空）
valid_count: （有效问卷数）
key_issue_question_refs: '["q02", "q05"]'
---

## 前言

（AI 写：第 1 段，约 200 字，疾病/品类背景 → 产品价值 → 区域与对象 → 调研目的）

（AI 写：第 2 段，约 200 字，分析层面说明 → 应用价值落点）

## 项目背景

（AI 写：第 1 段，宏观背景/区域特征）

（AI 写：第 2 段，数据缺口/本次调研必要性）

## 项目开展情况

（AI 写或程序生成：项目工具、样本采集范围、数量、时间）

## 问卷说明

（AI 写或程序生成：标准化统计处理方法说明）

## 问卷结果分析

（AI 写：导语段，程序整合维度名称与数量后拼接）

### 4.1（维度名称）

#### （小标题）

（AI 写：250-300 字单题分析，必须包含数字百分比，不得出现 A/B/C/D 或"选项A"等字母选项列举）

#### （小标题）

（AI 写：同上格式）

### 4.2（维度名称）

#### （小标题）

（AI 写：同上格式）

...（按实际维度数量继续）

## 调研结果

### 5.1 问卷重点问题分析

（AI 写：第 1 段，250-350 字，对应 key_issue_question_refs[0]）

（AI 写：第 2 段，250-350 字，对应 key_issue_question_refs[1]）

### 5.2 调研结果总结

（AI 写：3-5 段，总字数不超过 700 字，必须点名品种或地区，覆盖主要维度与管理含义）

### 5.3 建议

（AI 写：1 段导语 50-80 字，以"基于/结合调研结果"开头，必须点名品种和核心问题方向）

1. （AI 写：80-150 字，靶子层 → 手段层 → 目的层）

2. （AI 写：同上格式）

3. （AI 写：同上格式，可选 2-4 条）
```

## 关键校验规则

| 检查项 | 要求 | 失败后果 |
|--------|------|----------|
| `survey_period` | 必须存在 | preflight 失败 |
| `key_issue_question_refs` | JSON 数组，恰好 2 个题号 | preflight 失败 |
| `theme` | 如果提供，必须精确命中 dimension_library.json | preflight 失败 + 列出候选 |
| 前言 | 2 段 | build_payload 失败 |
| 项目背景 | 2 段 | build_payload 失败 |
| `4.x` 每道题分析 | 1 段，250-300 字，含百分比 | build_payload 失败 |
| `5.1` | 2 段，每段 250-350 字 | build_payload 失败 |
| `5.2` | 3-5 段，总计 ≤700 字 | build_payload 失败 |
| `5.3` | 1 段导语 + 2-4 条编号建议 | build_payload 失败 |

## 两阶段模式

- **一键模式**：`python3 scripts/run_report_pipeline.py questionnaire.xlsx report_content.md --output-docx report.docx`
- **两阶段模式**：
  1. AI 生成 `report_content.md` 并保存到 `tmp/runs/{timestamp}-{slug}/report_content.md`
  2. 运行 `python3 scripts/run_report_pipeline.py questionnaire.xlsx report_content.md --output-docx report.docx`
  - 如果 preflight 失败，会输出 `PREFLIGHT_FAILED` 及具体错误列表，并保留 `preflight.json` 诊断文件
  - AI 可以基于错误信息修改草稿后重新运行，无需重写整份报告