# Skill 内置 Word 模板与占位符渲染改造规格

## 1. 文档用途

本文档是以下项目的唯一改造范围：

`/Users/lee/Library/Mobile Documents/com~apple~CloudDocs/打工项目/爱诺模版测试集合/爱诺skill合集/Fix-JLK-skill`

目标读者是后续负责分析、实现、测试或审核此改造的 AI/工程师。实施者必须先阅读：

1. `SKILL.md`
2. `references/report-payload-schema.md`
3. `scripts/run_report_pipeline.py`
4. `scripts/build_payload.py`
5. `scripts/render_from_template.py`
6. `scripts/final_validate_docx.py`
7. `tests/test_jlk_pipeline.py`

本文档定义目标架构和验收边界，不代表当前代码已经实现全部能力。任何实施必须以当前工作树代码为准，不得覆盖用户已有改动。

---

## 2. 决策结论

本阶段采用：

> **Skill 内置最终版 Word 模板 + 结构化 payload + 显式占位符/块锚点渲染**

本阶段不开发独立模板管理系统，不引入数据库，不制作可视化模板编辑器，也不改变报告内容生成规则。

职责边界：

| 层 | 职责 |
| --- | --- |
| AI 内容层 | 生成 `report_content.md` 中允许由 AI 撰写的正文 |
| 问卷与 payload 层 | 解析问卷、聚类维度、校验内容、构建 `report_payload.json` |
| 模板层 | 保存封面、页眉页脚、分页、字体、表格、图表样式和插入锚点 |
| 渲染层 | 按 manifest 将 payload 写入模板，不重新设计内容 |
| 验收层 | 校验内容完整性、锚点消费情况、图表/表格数量及 docx 结构 |

最终数据流：

```text
questionnaire.xlsx
        |
        v
parse_questionnaire.py
        |
        v
questionnaire.json + report_content.md
        |
        v
build_payload.py
        |
        v
report_payload.json
        |
        v
template.docx + template_manifest.json
        |
        v
TemplateRenderer
        |
        v
final_validate_docx.py
        |
        v
可交付 report.docx
```

---

## 3. 当前状态

当前仓库已经不是纯粹的“新建空白 Word”方案：

- `scripts/run_report_pipeline.py` 已使用 `TemplateRenderer`。
- `scripts/render_from_template.py` 已具备对象级替换、段落/表格克隆、图片插入、Office 图表 XML 修改和页眉页脚保留能力。
- `templates/efficacy-report-template.docx` 已作为模板底稿。
- `scripts/render_report.py` 是旧版清空正文后重建文档的遗留实现，不是生产主路径。
- `scripts/final_validate_docx.py` 已承担最终内容和结构验收。

当前主要技术债：

1. 大量逻辑依赖模板中的旧业务文字，例如旧产品名、旧地区、固定章节文字。
2. 部分定位依赖正文顺序和元素索引，模板被人工修改后容易静默错位。
3. 模板本身没有机器可读的版本和能力声明。
4. 渲染前没有独立、完整的模板契约校验。
5. 当前渲染器职责过多，文本替换、动态块渲染、图表 OOXML 和最终清理集中在一个大文件。
6. 现有流程尚未用阶段计时证明 30 分钟耗时具体分布，不能直接假定 60% 时间都在 Word 渲染。

因此，本改造是对现有模板渲染路径的收敛，不是推倒重写。

---

## 4. 改造目标

### 4.1 功能目标

1. 模板随 skill 交付，运行时不依赖外部模板路径。
2. 模板中的动态位置使用明确且唯一的占位符或块锚点。
3. payload 继续作为渲染唯一数据源，不让模板直接消费 AI 原始 Markdown。
4. 固定字段、正文块、重复块、表格和图表均有明确协议。
5. 模板或 payload 不符合契约时，在写出最终 docx 前失败。
6. 输出不得残留占位符、旧产品名、旧地区或空值泄漏。
7. 保留现有报告结构、字体、分页、页眉页脚、表格和图表要求。
8. 保持当前一键命令兼容：

```bash
python3 scripts/run_report_pipeline.py questionnaire.xlsx report_content.md --output-docx report.docx
```

### 4.2 性能目标

先测量，再承诺。实施完成后的硬指标建议为：

- payload 已存在时，纯模板预检和 docx 渲染的本机 P95 小于 60 秒。
- 相同输入连续执行 3 次，不出现明显线性增长或临时文件累积。
- 总流程是否能控制在 5 分钟以内，必须根据 AI 内容生成耗时单独评估。

### 4.3 非目标

本阶段明确不做：

- 独立模板管理后台。
- 在线模板上传、审批和版本发布。
- 数据库模板存储。
- 任意用户自定义模板。
- 通用 Jinja/docxtpl 兼容层。
- 批量任务调度系统。
- 所有 Word 功能的抽象封装。
- 改写问卷解析、内容规范、维度聚类或合规规则。

---

## 5. 目录与文件规划

建议目标结构：

```text
templates/
  efficacy/
    template.docx
    manifest.json
  adherence/
    template.docx
    manifest.json

scripts/
  template_contract.py
  template_preflight.py
  template_engine.py
  render_from_template.py
  final_validate_docx.py
  run_report_pipeline.py

tests/
  fixtures/
    templates/
  test_template_contract.py
  test_template_engine.py
  test_jlk_pipeline.py
```

文件职责：

| 文件 | 职责 |
| --- | --- |
| `template_contract.py` | manifest 数据结构、占位符语法、payload 路径解析 |
| `template_preflight.py` | 渲染前检查模板包、占位符、动态块和 payload |
| `template_engine.py` | 通用文本、块、表格、图片替换原语 |
| `render_from_template.py` | 本报告结构的编排和现有 OOXML 图表处理 |
| `final_validate_docx.py` | 渲染后业务验收和残留检查 |
| `run_report_pipeline.py` | 阶段编排、计时、诊断文件和失败策略 |

不要在第一轮就拆分全部现有代码。先用测试锁定行为，再把可独立验证的原语从 `render_from_template.py` 提取出来。

---

## 6. 模板包契约

每个模板必须由同目录下的 `.docx` 和 `manifest.json` 共同组成。禁止仅凭文件名或模板内旧正文猜测模板类型。

建议 manifest 第一版：

```json
{
  "schema_version": 1,
  "template_id": "patient-efficacy-v1",
  "template_type": "用药体验与疗效反馈",
  "template_file": "template.docx",
  "renderer": "patient_report_v1",
  "required_payload_paths": [
    "meta.product",
    "meta.region",
    "meta.survey_period_display",
    "report_title",
    "preface",
    "project_background",
    "project_execution.lines",
    "questionnaire_note",
    "result_analysis.sections",
    "summary.key_issue_items",
    "summary.overall_analysis",
    "summary.recommendations",
    "attachments.attachment1_questions",
    "disclaimer.items"
  ],
  "required_singletons": [
    "field.meta.product",
    "field.meta.region",
    "field.report_title",
    "block.preface",
    "block.project_background",
    "repeat.result_sections",
    "repeat.key_issue_items",
    "repeat.attachment_questions"
  ],
  "optional_singletons": [],
  "allowed_chart_modes": [
    "office",
    "image"
  ]
}
```

规则：

1. `schema_version` 不支持时直接失败。
2. `template_file` 必须位于 manifest 同目录，禁止 `..` 路径逃逸。
3. `template_type` 必须与 payload 的 `meta.template_type` 一致。
4. `required_payload_paths` 缺失、值为 `None` 或类型错误时直接失败。
5. `required_singletons` 在模板中必须且只能出现一次。
6. 模板哈希写入 `run_manifest.json`，保证结果可追溯。

---

## 7. 占位符协议

### 7.1 语法

统一使用：

```text
{{kind.path}}
```

支持四类：

```text
{{field.meta.product}}
{{block.preface}}
{{repeat.result_sections}}
{{media.chart_4_overview_bar}}
```

含义：

| 类型 | 用途 | 是否允许重复 |
| --- | --- | --- |
| `field` | 单个短文本字段 | 由 manifest 决定，默认单例 |
| `block` | 固定位置的一个或多个正文段落 | 默认单例 |
| `repeat` | 根据数组克隆模板原型块 | 必须单例 |
| `media` | 图片或图表插入点 | 默认单例 |

占位符名称必须匹配：

```regex
\{\{(field|block|repeat|media)\.[a-zA-Z0-9_.-]+\}\}
```

禁止在占位符中加入表达式、条件判断或 Python 代码。第一版不实现模板语言。

### 7.2 Word run 拆分

Word 可能把一个占位符拆成多个 `w:r/w:t`。预检和替换必须基于段落或单元格的拼接文本识别，不得只遍历单个 run 执行 `run.text.replace()`。

替换时应遵循：

1. 计算所有文本节点及字符偏移。
2. 定位占位符跨越的文本节点。
3. 将替换内容写入首个命中文本节点。
4. 清空其余被占用文本节点。
5. 保留首个命中 run 的字符样式。
6. 不得删除同段落中的 drawing、bookmark、field 或其他非文本节点。

### 7.3 文本字段

示例：

```text
报告产品：{{field.meta.product}}
调研地区：{{field.meta.region}}
```

字段值只能是字符串、数字或可安全转为字符串的标量。列表和对象必须使用 `block` 或 `repeat`。

### 7.4 固定正文块

示例：

```text
{{block.preface}}
```

约定：

- 占位符所在段落是原型段落。
- 数组第一项替换原型段落。
- 后续项克隆原型段落并插入其后。
- 空数组是否允许由 manifest 决定；必需块为空时失败。
- 克隆后保留原型段落样式、分页和段落属性。

### 7.5 动态重复块

动态块不能仅靠一个普通段落表达原型边界。推荐使用 Word bookmark 标记：

```text
bookmark start: tpl_result_section
...一个完整的 4.x 章节原型...
bookmark end: tpl_result_section
```

正文中同时保留可见锚点：

```text
{{repeat.result_sections}}
```

渲染过程：

1. 根据 bookmark 确定原型块边界。
2. 从模板正文移除可见占位符。
3. 对 payload 数组逐项深拷贝原型 OOXML。
4. 在每个副本中替换局部字段、表格、分析正文和媒体。
5. 删除原始原型或把第一项写入原型，二者必须固定一种策略。
6. 完成后重建锚点映射。

禁止继续依赖“扫描到下一个 `4.x` 标题”为唯一边界判断。迁移期可保留旧逻辑作为受控 fallback，但必须记录 warning，最终删除。

### 7.6 表格和图表

建议占位符：

```text
{{media.overview_pie}}
{{media.overview_bar}}
{{media.question_table}}
{{media.key_issue_chart}}
```

具体数据绑定由重复块当前上下文决定，不把动态索引硬编码进模板。

图表策略保持现有要求：

- 第一张概览图：Office 原生饼图。
- 第二张概览图：PNG 横向柱形图。
- `5.1`：两张 Office 原生 3D 饼图，顺序为“正文1 → 图1 → 正文2 → 图2”。
- 问卷结果分析中的统计表继续继承模板表格样式。

不要在第一版引入任意 chart DSL。

---

## 8. Payload 约束

现有 `report_payload.json` 是唯一数据源。占位符改造不得绕过 `build_payload.py`，也不得让模板直接读取 `report_content.md`。

第一阶段原则：

1. 尽量不修改现有 payload 结构。
2. 模板 manifest 的 `required_payload_paths` 与当前 schema 对齐。
3. 动态重复块使用现有数组：
   - `result_analysis.sections`
   - `section.subtopics`
   - `summary.key_issue_items`
   - `attachments.attachment1_questions`
4. 图表继续使用现有 `chart_ref`、`chart_type`、`render_mode` 和数据字段。
5. 若确实需要新增字段，先修改 schema 文档和 `validate_payload()`，再修改渲染器。

禁止在渲染器中根据正文文字重新推导业务数据。

---

## 9. 渲染前预检

新增模板预检应在 `TemplateRenderer` 修改文档之前执行。

预检顺序：

1. manifest JSON 可解析。
2. manifest schema 版本受支持。
3. 模板文件存在且可由 `python-docx`/zipfile 打开。
4. payload 模板类型匹配。
5. 必需 payload 路径存在且类型正确。
6. 扫描正文、表格、页眉和页脚中的占位符。
7. 必需单例占位符出现且仅出现一次。
8. 不存在未知 `kind` 或非法名称。
9. 重复块 bookmark 边界完整且不交叉。
10. 必需 Office 图表部件、关系文件和原型表格存在。

预检结果写入运行目录：

```text
template_preflight.json
```

建议结构：

```json
{
  "ok": false,
  "template_id": "patient-efficacy-v1",
  "errors": [
    {
      "code": "MISSING_PLACEHOLDER",
      "path": "repeat.key_issue_items",
      "location": "document.xml"
    }
  ],
  "warnings": []
}
```

错误必须使用稳定 code，便于 AI 定位，不能只返回模糊自然语言。

---

## 10. 渲染器迁移策略

采用渐进迁移，禁止一次性重写 `TemplateRenderer`。

### 阶段 A：建立性能与行为基线

在 `run_report_pipeline.py` 为以下阶段记录耗时：

- `parse_questionnaire`
- `preflight_content`
- `build_payload`
- `template_preflight`
- `render_docx`
- `final_validate_docx`
- `total`

写入 `run_manifest.json`：

```json
{
  "timings_seconds": {
    "parse_questionnaire": 0.42,
    "preflight_content": 0.03,
    "build_payload": 0.08,
    "template_preflight": 0.10,
    "render_docx": 4.20,
    "final_validate_docx": 0.61,
    "total": 5.44
  }
}
```

没有基线数据前，不删除任何看似冗余但可能承担兼容功能的步骤。

### 阶段 B：引入 manifest 和只读预检

先让 manifest 描述现有模板，不改变输出。预检初期可只报警，测试稳定后改为 fail-fast。

### 阶段 C：迁移固定字段

优先迁移：

- 产品
- 地区
- 调研时间
- 服务单位
- 报告标题
- 样本量

每迁移一个字段：

1. 在模板中加入显式 `field` 占位符。
2. 增加失败测试。
3. 实现替换。
4. 删除对应旧值猜测逻辑。
5. 运行全量测试。

禁止长期同时保留“占位符替换”和“旧产品名全局替换”两套生产逻辑，否则可能误替换正文中的合法文本。

### 阶段 D：迁移固定正文块

依次迁移：

- `preface`
- `project_background`
- `project_execution`
- `questionnaire_note`
- `summary.overall_analysis`
- `summary.recommendations`
- `disclaimer`

### 阶段 E：迁移动态块

推荐顺序：

1. `attachments.attachment1_questions`
2. `summary.key_issue_items`
3. `result_analysis.sections/subtopics`

第 4 章最后迁移，因为它同时涉及动态章节、表格、正文、分页和媒体对象，风险最高。

### 阶段 F：清理旧锚点

只有在以下条件同时成立后，才能删除旧锚点代码：

- 新占位符路径有单元测试。
- 当前两类模板样本都通过端到端测试。
- 最终 docx 验收通过。
- 输出视觉对比无明显回归。
- 连续运行性能无退化。

---

## 11. 失败与回滚策略

遵循 fail-fast：

- 模板预检失败：不进入渲染。
- payload 缺失：不进入渲染。
- 动态块数量不匹配：不产出最终交付文件。
- 图表插入失败：不使用空白占位符降级。
- 最终验证失败：移除最终交付路径中的 docx，只保留 run directory 诊断文件。

诊断目录至少保留：

```text
questionnaire.json
report_payload.json
preflight.json
template_preflight.json
run_manifest.json
rendered-debug.docx
```

注意：当前 `run_report_pipeline.py` 对 `FinalValidationError` 的处理可能仍是 warning 并保留输出。实施者必须先用测试确认实际行为，再按 `SKILL.md` 的“失败并移除最终交付 docx”要求修正。

模板升级必须保留上一版本，直到新版本完成回归。不要直接覆盖唯一可用模板后再调试。

---

## 12. 测试方案

### 12.1 占位符解析单元测试

至少覆盖：

1. 单个 run 中的占位符。
2. 被拆成 2-4 个 run 的占位符。
3. 同一段多个占位符。
4. 表格单元格中的占位符。
5. 页眉页脚中的占位符。
6. 含 drawing 的段落，替换文本但保留 drawing。
7. 未知占位符类型。
8. 必需单例缺失。
9. 必需单例重复。
10. 替换后不残留大括号。

### 12.2 manifest 测试

至少覆盖：

- schema 版本不支持。
- 模板类型不匹配。
- 模板文件路径逃逸。
- payload 路径缺失。
- payload 类型错误。
- bookmark 起止不完整。
- Office 图表原型缺失。

### 12.3 动态块测试

分别测试数组长度：

- 0：必需块失败。
- 1：只保留一个原型。
- 2：正确克隆一次。
- 大于模板原型数量：继续克隆且顺序正确。

第 4 章必须验证：

- 每题一个 subtopic。
- 顺序为“小标题 → 统计表 → 分析正文”。
- 章节数和 payload 一致。
- 表格题目顺序和 payload 一致。

### 12.4 端到端回归

继续使用 `tests/test_jlk_pipeline.py` 中现有患者疗效和依从性样本，验证：

- 模板类型。
- 目录和页眉存在。
- 标题、地区、时间和服务商正确。
- 第 4 章结构完整。
- 5.1 文图交错正确。
- 附件题目和选项顺序正确。
- 不出现 `None/nan/null/N/A/undefined`。
- 不残留任何 `{{...}}`。
- docx 可以被 `python-docx` 和 `zipfile` 重新打开。

### 12.5 视觉回归

自动结构测试不能代替视觉检查。每次模板版本变更至少渲染：

- 1 份疗效主题报告。
- 1 份依从性主题报告。
- 1 份题目数不同的报告。

检查：

- 封面和结算页。
- 目录页。
- 页眉页脚和页码。
- 第 4 章分页。
- 表格是否越界。
- 图表是否空白、拉伸或遮挡文字。
- 附件长文本是否溢出。

---

## 13. 推荐实施任务

### Task 1：记录性能基线

**修改：**

- `scripts/run_report_pipeline.py`
- `tests/test_jlk_pipeline.py`

**完成标准：**

- `run_manifest.json` 包含各阶段耗时。
- 单次流程和连续三次流程都有可比较记录。
- 不改变报告内容和版式。

### Task 2：建立模板 manifest

**新增：**

- `templates/efficacy/manifest.json`
- `templates/adherence/manifest.json`，若当前实际仍共用模板，则先只建立一个 manifest 并明确声明。
- `scripts/template_contract.py`
- `tests/test_template_contract.py`

**完成标准：**

- manifest 可加载、可校验、可绑定模板。
- 模板类型不匹配时稳定失败。

### Task 3：实现模板预检

**新增：**

- `scripts/template_preflight.py`
- `tests/test_template_preflight.py`

**修改：**

- `scripts/run_report_pipeline.py`

**完成标准：**

- 渲染前生成 `template_preflight.json`。
- 缺少必需锚点时不进入渲染。
- 错误包含稳定 code 和位置。

### Task 4：实现跨 run 占位符替换原语

**新增：**

- `scripts/template_engine.py`
- `tests/test_template_engine.py`

**完成标准：**

- 支持正文、表格、页眉页脚。
- 保留首个 run 样式和非文本 OOXML。
- 支持同段多个占位符。

### Task 5：迁移固定字段

**修改：**

- `templates/.../template.docx`
- `scripts/render_from_template.py`
- `scripts/final_validate_docx.py`
- `tests/test_jlk_pipeline.py`

**完成标准：**

- 固定字段全部通过显式占位符写入。
- 删除对应旧值全局猜测逻辑。
- 输出不残留旧业务数据。

### Task 6：迁移固定正文块

**修改：**

- 模板文件
- `scripts/render_from_template.py`
- `tests/test_template_engine.py`
- `tests/test_jlk_pipeline.py`

**完成标准：**

- 正文数组按模板原型段落克隆。
- 段落数变化不依赖固定索引。

### Task 7：迁移附件和重点问题动态块

**修改：**

- 模板文件
- `scripts/render_from_template.py`
- `scripts/final_validate_docx.py`
- 对应测试

**完成标准：**

- 附件题目数可变且顺序正确。
- 5.1 保持两段正文和两张原生图表交错。

### Task 8：迁移第 4 章动态章节

**修改：**

- 模板文件
- `scripts/render_from_template.py`
- `scripts/final_validate_docx.py`
- 对应测试

**完成标准：**

- 不再以旧标题文字和相邻 `4.x` 扫描作为主定位方法。
- 任意合法章节数和题目数都能按原型块渲染。

### Task 9：清理旧渲染路径

**修改：**

- `scripts/render_from_template.py`
- `scripts/render_report.py`
- `SKILL.md`
- 测试

**完成标准：**

- 生产入口只有模板驱动路径。
- 若保留 `render_report.py`，文件顶部明确标记为非生产 fallback，且没有主流程调用。
- 删除已被占位符替代的旧值猜测和固定索引逻辑。

### Task 10：最终回归与性能验收

**执行：**

```bash
python3 -m unittest tests.test_jlk_pipeline
```

若新增测试文件使用 unittest：

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```

**完成标准：**

- 所有测试通过。
- 三份视觉样本通过检查。
- `template_preflight.json` 无错误。
- 最终文档无残留占位符。
- 记录迁移前后各阶段耗时。

---

## 14. 审核门禁

其他 AI 完成改造后，最终审核必须逐项确认：

### 范围

- [ ] 所有改动只针对本仓库。
- [ ] 未改变问卷解析和 AI 内容写作职责。
- [ ] 未引入独立模板管理系统。
- [ ] 未修改无关文件或覆盖用户改动。

### 架构

- [ ] payload 仍是唯一渲染数据源。
- [ ] 模板和 manifest 成对存在。
- [ ] 不再把旧产品名/旧地区作为主要锚点。
- [ ] 动态块有明确边界，不依赖脆弱索引。

### 正确性

- [ ] 模板预检在渲染前运行。
- [ ] 最终验证失败时没有留下可误交付的 docx。
- [ ] 输出无 `{{...}}`、旧业务数据和空值泄漏。
- [ ] 第 4 章、5.1、附件和图表顺序符合 `SKILL.md`。

### 测试

- [ ] 跨 run 替换有独立测试。
- [ ] manifest 错误路径有独立测试。
- [ ] 动态数组长度变化有测试。
- [ ] 两种现有主题端到端通过。
- [ ] Word/WPS 视觉检查完成。

### 性能

- [ ] `run_manifest.json` 包含阶段耗时。
- [ ] 有迁移前后数据对比。
- [ ] 没有把 AI 内容生成时间错误归因于 Word 渲染。

任一门禁未通过，不能宣称改造完成。

---

## 15. 给实施 AI 的限制

1. 不要看到“占位符”就引入 `docxtpl`。先证明现有 `python-docx + OOXML` 无法满足需求。
2. 不要重写整个 `TemplateRenderer`。先补测试，再逐项迁移。
3. 不要把复杂业务逻辑塞进 manifest。manifest 只描述模板契约。
4. 不要让模板直接解析 Markdown。
5. 不要用字符串正则直接修改整个 `document.xml` 来处理动态块。
6. 不要为了通过测试降低 `final_validate_docx.py` 的验收强度。
7. 不要以“能打开 docx”作为完成标准，必须验证业务结构和视觉结果。
8. 不要删除 Office 原生图表能力，除非需求明确改为全部 PNG。
9. 不要承诺总耗时降到 5 分钟，除非阶段计时已经证明。
10. 每个阶段应形成独立、可评审、可回滚的提交。

---

## 16. 最终完成定义

只有同时满足以下条件，才算完成：

1. Skill 内置模板包可独立运行。
2. 模板具有版本化 manifest。
3. 固定字段和主要动态块使用显式占位符/块锚点。
4. 渲染前模板预检可阻断错误。
5. 渲染后最终验证可阻断错误交付。
6. 当前患者疗效与依从性报告回归通过。
7. 输出视觉效果不低于现有模板。
8. 性能计时证明渲染链路达到目标或明确指出剩余瓶颈。
9. `SKILL.md`、schema 和实际实现保持一致。
