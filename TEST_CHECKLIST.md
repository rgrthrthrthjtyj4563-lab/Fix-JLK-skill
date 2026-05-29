# JLK-Pt-FixDim 测试清单

> **测试对象**：`JLK-Pt-skill_副本`（固定维度表机制的增量改动）
> **测试路径**：`/Users/lee/Library/Mobile Documents/com~apple~CloudDocs/打工项目/爱诺模版测试集合/爱诺skill合集/JLK-Pt-skill_副本`
> **改动文件**：
> - `scripts/build_payload.py` — 新增 3 个函数 + 改 1 处调用链
> - `data/dimension_library.json` — 新建
> - `SKILL.md` — 补充说明
> - `scripts/cluster_dimensions.py` — **零改动（必须验证）**

---

## T1：文件结构完整性

| 编号 | 测试项 | 命令 | 预期结果 |
|------|--------|------|----------|
| T1.1 | JSON 文件存在 | `ls data/dimension_library.json` | 文件存在 |
| T1.2 | JSON 合法 | `python3 -c "import json; json.load(open('data/dimension_library.json'))"` | 无报错 |
| T1.3 | cluster_dimensions.py 无改动 | `git diff scripts/cluster_dimensions.py` | 无输出（空 diff） |
| T1.4 | build_payload.py 语法正确 | `python3 -c "import ast; ast.parse(open('scripts/build_payload.py').read()); print('SYNTAX OK')"` | 输出 `SYNTAX OK` |
| T1.5 | 函数存在性 | `python3 -c "from scripts.build_payload import load_dimension_library, resolve_theme, fixed_dimensions_to_ai, _unique_pattern_for_question; print('ALL OK')"` | 输出 `ALL OK` |
| T1.6 | 无重复函数定义 | `grep -c 'def fixed_dimensions_to_ai' scripts/build_payload.py` | 输出 `1` |
| T1.7 | 无重复函数定义 | `grep -c 'def load_dimension_library' scripts/build_payload.py` | 输出 `1` |

---

## T2：load_dimension_library()

| 编号 | 测试项 | 命令 | 预期结果 |
|------|--------|------|----------|
| T2.1 | 正常加载 | `python3 -c "from scripts.build_payload import load_dimension_library; lib=load_dimension_library(); print(type(lib), len(lib['themes']))"` | `<class 'dict'> 17` |
| T2.2 | 缓存生效 | `python3 -c "from scripts.build_payload import load_dimension_library; a=load_dimension_library(); b=load_dimension_library(); print(a is b)"` | `True`（同一对象） |
| T2.3 | 文件不存在时回退 | 先备份 JSON → 删除 → 调用 → 恢复。`python3 -c "import shutil, os; src='data/dimension_library.json'; dst='/tmp/_backup_dim.json'; shutil.copy(src,dst); os.remove(src); from scripts.build_payload import load_dimension_library; result=load_dimension_library(); shutil.move(dst,src); print(result)"` | `None` |
| T2.4 | 主题名列表 | `python3 -c "from scripts.build_payload import load_dimension_library; lib=load_dimension_library(); print([t['theme_name'] for t in lib['themes']])"` | 包含源表中的 17 个主题 |

---

## T3：resolve_theme() 匹配逻辑

```python
# 以下测试用 Python 脚本执行，工作目录为 skill 根目录
```

| 编号 | 测试输入 | 预期结果 |
|------|----------|----------|
| T3.1 | `meta={"theme": "心达康胶囊的患者依从性调研问卷"}` | 命中第 1 个主题 |
| T3.2 | `cli_args=Namespace(theme="心达康胶囊-药品可及性与价格敏感度调查（患者）")` | 命中第 2 个主题 |
| T3.3 | `meta={"主题": "心达康胶囊的患者依从性调研问卷"}`（中文 key） | 命中第 1 个主题 |
| T3.4 | `meta={"theme": "不存在的主题名称"}` | 返回 `None` |
| T3.5 | `meta={}` 空 meta，`cli_args=Namespace(theme=None)` | 返回 `None` |
| T3.6 | `meta={"theme": "心达康胶囊的患者依从性调研问卷"}`，`cli_args=Namespace(theme="心达康胶囊-药品可及性与价格敏感度调查（患者）")` | cli_args 优先，命中第 2 个主题 |
| T3.7 | 主题名前后有空格 | `meta={"theme": "  心达康胶囊的患者依从性调研问卷  "}` | 命中（normalize_space 去空格） |

**执行脚本**：

```bash
cd "/Users/lee/Library/Mobile Documents/com~apple~CloudDocs/打工项目/爱诺模版测试集合/爱诺skill合集/JLK-Pt-skill_副本"

python3 << 'EOF'
import argparse
from scripts.build_payload import load_dimension_library, resolve_theme

lib = load_dimension_library()

tests = [
    ("T3.1", {"theme": "心达康胶囊的患者依从性调研问卷"}, argparse.Namespace(theme=None), "命中第1个主题"),
    ("T3.2", {}, argparse.Namespace(theme="心达康胶囊-药品可及性与价格敏感度调查（患者）"), "命中第2个主题"),
    ("T3.3", {"主题": "心达康胶囊的患者依从性调研问卷"}, argparse.Namespace(theme=None), "命中第1个主题(中文key)"),
    ("T3.4", {"theme": "不存在的主题名称"}, argparse.Namespace(theme=None), "None"),
    ("T3.5", {}, argparse.Namespace(theme=None), "None"),
    ("T3.6", {"theme": "心达康胶囊的患者依从性调研问卷"}, argparse.Namespace(theme="心达康胶囊-药品可及性与价格敏感度调查（患者）"), "命中第2个主题(cli优先)"),
    ("T3.7", {"theme": "  心达康胶囊的患者依从性调研问卷  "}, argparse.Namespace(theme=None), "命中第1个主题(去空格)"),
]

for tid, meta, cli_args, expected in tests:
    result = resolve_theme({}, meta, cli_args, lib)
    name = result['theme_name'] if result else None
    status = "PASS" if (expected == "None" and name is None) or (name is not None and expected.split("个主题")[0].replace("命中第","") in str(name)) else "FAIL"
    if expected == "None":
        status = "PASS" if name is None else "FAIL"
    print(f"  {tid}: result={name}, expected={expected}, {status}")
EOF
```

---

## T4：fixed_dimensions_to_ai() 输出格式

| 编号 | 测试项 | 预期结果 |
|------|--------|----------|
| T4.1 | 输出包含 `dimensions` 键 | 是 |
| T4.2 | 维度数量与 JSON 一致（主题1=4, 主题2=4） | 是 |
| T4.3 | 每个维度包含 `name`、`intro`（空串）、`subtopics`、`charts` | 是 |
| T4.4 | `intro` 字段为空字符串 | 是 |
| T4.5 | 每个 subtopic 含 `patterns` 和 `subtitle` | 是 |
| T4.6 | patterns 使用完整题干（`re.escape` 后的文本） | 是 |
| T4.7 | charts 规则：dim_idx=0,st_idx=0 → pie/efficacy_pie | 是 |
| T4.8 | charts 规则：dim_idx=1,st_idx=0 → bar3d/behavior_bar | 是 |
| T4.9 | charts 规则：其他位置 → 无 chart | 是 |

**执行脚本**：

```bash
cd "/Users/lee/Library/Mobile Documents/com~apple~CloudDocs/打工项目/爱诺模版测试集合/爱诺skill合集/JLK-Pt-skill_副本"

python3 << 'EOF'
import argparse, json
from scripts.build_payload import load_dimension_library, resolve_theme, fixed_dimensions_to_ai

lib = load_dimension_library()

# 主题1
mock_q1 = {"questions": [
    {"number": i, "question": f"题目{i}测试心达康胶囊"} for i in range(1, 11)
], "question_count": 10}

entry1 = resolve_theme({}, {"theme": "心达康胶囊的患者依从性调研问卷"}, argparse.Namespace(theme=None), lib)
ai1 = fixed_dimensions_to_ai(entry1, mock_q1)

# T4.1
assert "dimensions" in ai1, "T4.1 FAIL: no dimensions key"
print("  T4.1 PASS")

# T4.2
assert len(ai1["dimensions"]) == 4, f"T4.2 FAIL: got {len(ai1['dimensions'])}"
print("  T4.2 PASS")

# T4.3 + T4.4
for d in ai1["dimensions"]:
    assert "name" in d, "T4.3 FAIL: missing name"
    assert d["intro"] == "", f"T4.4 FAIL: intro not empty, got '{d['intro']}'"
    assert "subtopics" in d, "T4.3 FAIL: missing subtopics"
    assert "charts" in d, "T4.3 FAIL: missing charts"
print("  T4.3 PASS, T4.4 PASS")

# T4.5
for d in ai1["dimensions"]:
    for st in d["subtopics"]:
        assert "patterns" in st, "T4.5 FAIL: missing patterns"
        assert "subtitle" in st, "T4.5 FAIL: missing subtitle"
        assert len(st["patterns"]) > 0, f"T4.5 FAIL: empty patterns for {st['subtitle']}"
print("  T4.5 PASS")

# T4.7-T4.9 charts
d0 = ai1["dimensions"][0]
d1 = ai1["dimensions"][1]
d2 = ai1["dimensions"][2]
assert len(d0["charts"]) >= 1, "T4.7 FAIL: no chart in dim0"
assert d0["charts"][0]["chart_type"] == "pie", f"T4.7 FAIL: expected pie, got {d0['charts'][0]['chart_type']}"
assert len(d1["charts"]) >= 1, "T4.8 FAIL: no chart in dim1"
assert d1["charts"][0]["chart_type"] == "bar3d", f"T4.8 FAIL: expected bar3d, got {d1['charts'][0]['chart_type']}"
assert len(d2["charts"]) == 0, "T4.9 FAIL: dim2 should have no charts"
print("  T4.7 PASS, T4.8 PASS, T4.9 PASS")

print("\n全部 T4 测试通过")
EOF
```

---

## T5：cluster_dimensions() 端到端验证（核心！）

这是最关键的测试——验证固定维度表数据经过 `fixed_dimensions_to_ai()` → `_build_from_ai_dimensions()` 后，题目是否精确分配到指定维度。

### T5.1 主题1：心达康胶囊的患者依从性调研问卷

```bash
cd "/Users/lee/Library/Mobile Documents/com~apple~CloudDocs/打工项目/爱诺模版测试集合/爱诺skill合集/JLK-Pt-skill_副本"

python3 << 'EOF'
import argparse, json
from scripts.build_payload import load_dimension_library, resolve_theme, fixed_dimensions_to_ai
from scripts.cluster_dimensions import cluster_dimensions

mock_q1 = {
    "questions": [
        {"number": 1, "question": "您的教育程度是？"},
        {"number": 2, "question": "您通常在什么时间服用心达康胶囊？"},
        {"number": 3, "question": "您每日服用心达康胶囊的次数是？"},
        {"number": 4, "question": "当忘记服药时，您会怎么做？"},
        {"number": 5, "question": "导致您漏服心达康胶囊的主要原因是？（可多选）"},
        {"number": 6, "question": "在服用心达康胶囊期间，您是否曾自行调整过服药剂量？"},
        {"number": 7, "question": "您获取心达康胶囊功效信息的主要渠道是？（可多选）"},
        {"number": 8, "question": "您认为哪方面改进后能提高您对心达康胶囊的依从性？（多选）"},
        {"number": 9, "question": "您从哪里了解到心达康胶囊的储存方法？（可多选）"},
        {"number": 10, "question": "如果出现药物不良反应，您会怎么做？（可多选）"},
    ],
    "question_count": 10,
}

lib = load_dimension_library()
entry = resolve_theme({}, {"theme": "心达康胶囊的患者依从性调研问卷"}, argparse.Namespace(theme=None), lib)
ai_dims = fixed_dimensions_to_ai(entry, mock_q1)
result = cluster_dimensions(mock_q1, ai_dimensions=ai_dims)

# 预期分配
expected = {
    "q01": "4.1", "q07": "4.1", "q09": "4.1",
    "q02": "4.2", "q03": "4.2", "q04": "4.2",
    "q05": "4.3", "q06": "4.3",
    "q08": "4.4", "q10": "4.4",
}

actual = {}
for sec in result["sections"]:
    for ref in sec.get("question_refs", []):
        actual[ref] = sec["section_number"]

correct = sum(1 for q, s in expected.items() if actual.get(q) == s)
total = len(expected)
all_assigned = len(actual)

print(f"  题目分配正确率: {correct}/{total}")
print(f"  总题目数: {all_assigned}/10")
print(f"  维度数: {result['dimension_count']}")

if correct == total and all_assigned == 10:
    print("\n  ✅ T5.1 全部通过")
else:
    print("\n  ❌ T5.1 存在错误")
    for q in sorted(expected.keys()):
        exp = expected[q]
        act = actual.get(q, "??")
        if exp != act:
            print(f"    {q}: expected={exp} actual={act} ❌")
EOF
```

### T5.2 主题2：心达康胶囊-药品可及性与价格敏感度调查（患者）

```bash
cd "/Users/lee/Library/Mobile Documents/com~apple~CloudDocs/打工项目/爱诺模版测试集合/爱诺skill合集/JLK-Pt-skill_副本"

python3 << 'EOF'
import argparse, json
from scripts.build_payload import load_dimension_library, resolve_theme, fixed_dimensions_to_ai
from scripts.cluster_dimensions import cluster_dimensions

mock_q2 = {
    "questions": [
        {"number": 1, "question": "您的年龄段："},
        {"number": 2, "question": "您通常通过什么渠道获取心达康胶囊？"},
        {"number": 3, "question": "在过去一年中，您是否遇到过心达康胶囊缺货的情况？"},
        {"number": 4, "question": "您目前购买心达康胶囊的主要支付方式是什么？"},
        {"number": 5, "question": "您认为心达康胶囊的价格："},
        {"number": 6, "question": "价格变动对您购买心达康胶囊决策的影响程度如何？"},
        {"number": 7, "question": "如果需要长期服用心达康胶囊，您更愿意选择哪种价格方案？"},
        {"number": 8, "question": "您认为提高心达康胶囊可及性和可负担性的最有效方式是什么？"},
        {"number": 9, "question": "您对改善心达康胶囊价格敏感度有何建议？"},
        {"number": 10, "question": "您认为提高心达康胶囊可及性的最佳途径是？"},
    ],
    "question_count": 10,
}

lib = load_dimension_library()
entry = resolve_theme({}, {"theme": "心达康胶囊-药品可及性与价格敏感度调查（患者）"}, argparse.Namespace(theme=None), lib)
ai_dims = fixed_dimensions_to_ai(entry, mock_q2)
result = cluster_dimensions(mock_q2, ai_dimensions=ai_dims)

expected = {
    "q01": "4.1",
    "q02": "4.2", "q03": "4.2", "q10": "4.2",
    "q04": "4.3", "q05": "4.3", "q06": "4.3", "q07": "4.3",
    "q08": "4.4", "q09": "4.4",
}

actual = {}
for sec in result["sections"]:
    for ref in sec.get("question_refs", []):
        actual[ref] = sec["section_number"]

correct = sum(1 for q, s in expected.items() if actual.get(q) == s)
total = len(expected)

print(f"  题目分配正确率: {correct}/{total}")
print(f"  维度数: {result['dimension_count']}")

if correct == total and len(actual) == 10:
    print("\n  ✅ T5.2 全部通过")
else:
    print("\n  ❌ T5.2 存在错误")
    for q in sorted(expected.keys()):
        exp = expected[q]
        act = actual.get(q, "??")
        if exp != act:
            print(f"    {q}: expected={exp} actual={act} ❌")
EOF
```

---

## T6：回退逻辑

| 编号 | 测试项 | 操作 | 预期结果 |
|------|--------|------|----------|
| T6.1 | JSON 不存在时回退 | 删除/重命名 `data/dimension_library.json`，运行 `build_payload` | 不崩溃，回退到硬编码模板或 AI dimensions_json |
| T6.2 | 主题未匹配时回退 | `theme="不存在的主题"` | `resolve_theme` 返回 `None`，走 `parse_dimensions_from_meta` |
| T6.3 | 同时有 dimensions_json 和固定维度 | `meta.dimensions_json` 有值 + `theme` 匹配固定表 | **固定维度优先**（代码逻辑：`theme_entry` 不为 None 则走 `fixed_dimensions_to_ai`，不走 `parse_dimensions_from_meta`） |

**执行脚本**：

```bash
cd "/Users/lee/Library/Mobile Documents/com~apple~CloudDocs/打工项目/爱诺模版测试集合/爱诺skill合集/JLK-Pt-skill_副本"

python3 << 'EOF'
import argparse, json, os, shutil
from scripts.build_payload import load_dimension_library, resolve_theme, fixed_dimensions_to_ai
from scripts.cluster_dimensions import cluster_dimensions

# T6.2: 主题未匹配
lib = load_dimension_library()
result = resolve_theme({}, {"theme": "厄贝沙坦氢氯噻嗪片用药体验与疗效反馈"}, argparse.Namespace(theme=None), lib)
print(f"  T6.2: 未匹配主题返回 None → {result is None} → {'PASS' if result is None else 'FAIL'}")

# T6.3: 固定维度优先于 dimensions_json
# 当 theme 匹配时，即使 meta 里有 dimensions_json，也应该走固定维度
mock_q = {"questions": [{"number": i, "question": f"题目{i}"} for i in range(1, 11)], "question_count": 10}
entry = resolve_theme({}, {"theme": "心达康胶囊的患者依从性调研问卷"}, argparse.Namespace(theme=None), lib)
override_dims = fixed_dimensions_to_ai(entry, mock_q)
# 用固定维度的结果跑 cluster_dimensions
result = cluster_dimensions(mock_q, ai_dimensions=override_dims)
print(f"  T6.3: 固定维度优先 → 维度数={result['dimension_count']} → {'PASS' if result['dimension_count'] == 4 else 'FAIL'}")

# T6.1: JSON 不存在时的缓存和回退
src = "data/dimension_library.json"
dst = "/tmp/_test_dim_backup.json"
shutil.copy(src, dst)
os.remove(src)

# 清除缓存
import scripts.build_payload as bp
bp._DIMENSION_LIBRARY_CACHE = None

result_none = load_dimension_library()
print(f"  T6.1: JSON 删除后 load 返回 → {result_none} → {'PASS' if result_none is None else 'FAIL'}")

# 恢复
shutil.move(dst, src)
bp._DIMENSION_LIBRARY_CACHE = None  # 清缓存让下次重新加载

result_restored = load_dimension_library()
print(f"  T6.1: JSON 恢复后 load 成功 → {result_restored is not None} → {'PASS' if result_restored is not None else 'FAIL'}")
EOF
```

---

## T7：cluster_dimensions.py 零改动验证

```bash
cd "/Users/lee/Library/Mobile Documents/com~apple~CloudDocs/打工项目/爱诺模版测试集合/爱诺skill合集/JLK-Pt-skill_副本"

# 如果有 git
git diff scripts/cluster_dimensions.py

# 如果没有 git，用文件哈希对比（与原 skill 对比）
md5 scripts/cluster_dimensions.py
md5 "../JLK-Pt-skill/scripts/cluster_dimensions.py"
```

预期：两文件 MD5 相同（或 git diff 无输出）。

---

## T8：维度名称与 JSON 一致性

```bash
cd "/Users/lee/Library/Mobile Documents/com~apple~CloudDocs/打工项目/爱诺模版测试集合/爱诺skill合集/JLK-Pt-skill_副本"

python3 << 'EOF'
import json
from scripts.build_payload import load_dimension_library, resolve_theme, fixed_dimensions_to_ai
from scripts.cluster_dimensions import cluster_dimensions
import argparse

lib = load_dimension_library()

mock_q1 = {
    "questions": [
        {"number": i, "question": f"题目{i}心达康胶囊测试"} for i in range(1, 11)
    ],
    "question_count": 10,
}

# 主题1
entry1 = resolve_theme({}, {"theme": "心达康胶囊的患者依从性调研问卷"}, argparse.Namespace(theme=None), lib)
ai1 = fixed_dimensions_to_ai(entry1, mock_q1)
result1 = cluster_dimensions(mock_q1, ai_dimensions=ai1)

json_dims = [d["name"] for d in entry1["dimensions"]]
actual_dims = result1["project_dimensions"]

print("T8: 维度名称对比")
for j_name, a_name in zip(json_dims, actual_dims):
    match = "✅" if j_name == a_name else "❌"
    print(f"  JSON: {j_name} → 实际: {a_name} {match}")

if json_dims == actual_dims:
    print("\n  ✅ T8 全部通过")
else:
    print("\n  ❌ T8 存在不一致")
EOF
```

---

## T9：边界情况

| 编号 | 测试项 | 操作 | 预期结果 |
|------|--------|------|----------|
| T9.1 | 空问卷 | `questionnaire={"questions": [], "question_count": 0}` | 不崩溃，维度数为 0 |
| T9.2 | 题号不在 JSON 中 | 问卷有第 11 题（超出 JSON 定义的 1-10） | 第 11 题归入最后一个维度的 orphan |
| T9.3 | JSON 中有题号但问卷中不存在 | 删掉第 5 题 | subtopic 的 patterns 匹配不到任何题，该 subtopic 为空，不影响其他 |

**执行脚本**：

```bash
cd "/Users/lee/Library/Mobile Documents/com~apple~CloudDocs/打工项目/爱诺模版测试集合/爱诺skill合集/JLK-Pt-skill_副本"

python3 << 'EOF'
import argparse
from scripts.build_payload import load_dimension_library, resolve_theme, fixed_dimensions_to_ai
from scripts.cluster_dimensions import cluster_dimensions

lib = load_dimension_library()

# T9.1: 空问卷
try:
    mock_empty = {"questions": [], "question_count": 0}
    entry = resolve_theme({}, {"theme": "心达康胶囊的患者依从性调研问卷"}, argparse.Namespace(theme=None), lib)
    ai = fixed_dimensions_to_ai(entry, mock_empty)
    result = cluster_dimensions(mock_empty, ai_dimensions=ai)
    print(f"  T9.1: 空问卷不崩溃，维度数={result['dimension_count']} → PASS")
except Exception as e:
    print(f"  T9.1: 空问卷崩溃 → {e} → FAIL")

# T9.2: 额外题目(第11题)
mock_11 = {
    "questions": [{"number": i, "question": f"题目{i}心达康"} for i in range(1, 12)],
    "question_count": 11,
}
entry = resolve_theme({}, {"theme": "心达康胶囊的患者依从性调研问卷"}, argparse.Namespace(theme=None), lib)
ai = fixed_dimensions_to_ai(entry, mock_11)
result = cluster_dimensions(mock_11, ai_dimensions=ai)
all_refs = set()
for sec in result["sections"]:
    for ref in sec.get("question_refs", []):
        all_refs.add(ref)
print(f"  T9.2: 11 题全部被分配={len(all_refs)==11}，第11题归入最后维度={('q11' in [r for sec in result['sections'][-1].get('question_refs',[])])} → PASS")

# T9.3: 缺少第5题
mock_9 = {"questions": [
    {"number": i, "question": f"题目{i}心达康"} for i in [1,2,3,4,6,7,8,9,10]
], "question_count": 9}
entry = resolve_theme({}, {"theme": "心达康胶囊的患者依从性调研问卷"}, argparse.Namespace(theme=None), lib)
ai = fixed_dimensions_to_ai(entry, mock_9)
try:
    result = cluster_dimensions(mock_9, ai_dimensions=ai)
    all_refs = set()
    for sec in result["sections"]:
        for ref in sec.get("question_refs", []):
            all_refs.add(ref)
    print(f"  T9.3: 缺第5题不崩溃，分配 {len(all_refs)}/9 题 → PASS")
except Exception as e:
    print(f"  T9.3: 缺第5题崩溃 → {e} → FAIL")
EOF
```

---

## T10：完整 pipeline 端到端（可选）

如果之前项目有可运行的 `run_report_pipeline.py`，用真实问卷数据跑一次完整流程：

```bash
cd "/Users/lee/Library/Mobile Documents/com~apple~CloudDocs/打工项目/爱诺模版测试集合/爱诺skill合集/JLK-Pt-skill_副本"

python3 scripts/run_report_pipeline.py \
  --questionnaire path/to/questionnaire.json \
  --report-content path/to/report_content.md \
  --theme "心达康胶囊的患者依从性调研问卷" \
  --product "心达康胶囊" \
  --region "北京市" \
  --output /tmp/test_fixdim_output.docx
```

检查：
- 输出 docx 无报错生成
- 4.1-4.4 维度标题与 `dimension_library.json` 一致
- 每维度下题目编号与 JSON 定义一致
- `cluster_dimensions.py` 无报错

---

## 测试结果汇总模板

| 编号 | 状态 | 备注 |
|------|------|------|
| T1.1 | ⬜ | |
| T1.2 | ⬜ | |
| ... | | |
| T2.1-T2.4 | ⬜ | |
| T3.1-T3.7 | ⬜ | |
| T4.1-T4.9 | ⬜ | |
| T5.1 | ⬜ | **核心：题目分配精确度** |
| T5.2 | ⬜ | **核心：题目分配精确度** |
| T6.1-T6.3 | ⬜ | **回退逻辑** |
| T7 | ⬜ | **cluster_dimensions 零改动** |
| T8 | ⬜ | |
| T9.1-T9.3 | ⬜ | **边界情况** |
| T10 | ⬜ | 可选 |
