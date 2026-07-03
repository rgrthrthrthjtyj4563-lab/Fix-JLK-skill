"""Internal-ref guard tests.

Covers the shared `_internal_ref_guard` module plus the preflight + final
validation hookups that enforce "no q\\d+ / 第N段 in body text". Front matter
is exempt because it never reaches the Word document.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts._internal_ref_guard import (
    INTERNAL_REF_PATTERN,
    INTERNAL_SECTION_REF_PATTERN,
    assert_clean_body_text,
    find_internal_ref_violations,
)


class TestInternalRefPattern(unittest.TestCase):
    """Pattern must hit Chinese-adjacent refs; must not over-fire on clean text."""

    def test_chinese_adjacent_q07_hits(self):
        # The exact wording that previously leaked through.
        text = "与q07反馈形成相互印证"
        self.assertTrue(INTERNAL_REF_PATTERN.search(text))

    def test_chinese_adjacent_q14_hits(self):
        text = "q14的改进方向反馈"
        self.assertTrue(INTERNAL_REF_PATTERN.search(text))

    def test_uppercase_q03_hits(self):
        text = "Q03统计结果"
        self.assertIsNotNone(INTERNAL_REF_PATTERN.search(text))

    def test_clean_text_does_not_hit(self):
        text = "本次统计显示，46.99%的患者在服药后症状改善。"
        self.assertIsNone(INTERNAL_REF_PATTERN.search(text))

    def test_letter_options_dont_hit(self):
        # "A. 全文" must NOT trigger — different forbidden pattern.
        text = "A. 体检时偶然发现"
        self.assertIsNone(INTERNAL_REF_PATTERN.search(text))

    def test_empty_and_whitespace(self):
        self.assertIsNone(INTERNAL_REF_PATTERN.search(""))
        self.assertIsNone(INTERNAL_REF_PATTERN.search("   "))


class TestSectionOrchestrationPattern(unittest.TestCase):
    """`第N段` / `第 N 段对应qXX` must be caught."""

    def test_section_marker_hits(self):
        text = "第1段对应q02治疗范围认知"
        self.assertTrue(INTERNAL_SECTION_REF_PATTERN.search(text))

    def test_ordinal_one_month_does_not_hit(self):
        # "第一个月" is a reader-facing ordinal, not internal section.
        text = "患者在第一个月内复诊"
        self.assertIsNone(INTERNAL_SECTION_REF_PATTERN.search(text))


class TestFindInternalRefViolations(unittest.TestCase):
    def test_multiple_violations_in_one_text(self):
        text = "第1段对应q02范围；与q07反馈相互印证；第2段对应q05。"
        issues = find_internal_ref_violations(text)
        # Expect at least: 2 internal_refs (q02, q07, q05 → 3) + 2 section
        # orchestrations (第1段, 第2段). Order not asserted.
        rules = [i.rule for i in issues]
        self.assertGreaterEqual(rules.count("internal_ref"), 3)
        self.assertGreaterEqual(rules.count("section_orchestration"), 2)

    def test_clean_text_returns_empty(self):
        text = "本次反馈显示，46.99%的患者认为改善挺明显。"
        self.assertEqual(find_internal_ref_violations(text), [])

    def test_assert_clean_raises_with_location(self):
        with self.assertRaises(ValueError) as ctx:
            assert_clean_body_text(
                "与q07反馈形成相互印证",
                location="4.2 / q07 / 服药频次便捷度分析",
            )
        msg = str(ctx.exception)
        self.assertIn("4.2 / q07 / 服药频次便捷度分析", msg)
        self.assertIn("q07", msg)

    def test_assert_clean_passes_on_clean_text(self):
        # Should not raise.
        assert_clean_body_text(
            "本次统计显示，46.99%的患者认为改善挺明显。",
            location="4.2 / q05 / 复查项目认知分析",
        )


class TestPreflightIntegration(unittest.TestCase):
    """4.x / 5.1 / 5.2 / 5.3 must reject internal refs at the preflight stage."""

    def _build_args(self, theme=None):
        class Args:
            pass
        args = Args()
        args.theme = theme
        args.product = "厄贝沙坦氢氯噻嗪片"
        args.region = "新疆"
        args.time = "2026年05月19日-06月10日"
        args.attachment_name = "03-2.问卷选项统计-厄贝疾病患者-新疆.xlsx"
        args.survey_period = "2026年05月19日-06月10日"
        args.sample_size = 2651
        args.valid_count = 2651
        args.disclaimer_unit = "北京玖麟空科技有限公司"
        args.output_docx = None
        args.run_dir = None
        return args

    def test_4x_subtopic_with_q07_ref_is_rejected(self):
        from scripts.build_payload import require_ai_analysis_paragraphs
        bad_text = (
            "本次统计显示，30.97%的患者能正确识别。提示与q07反馈形成相互印证。"
            "整体看，应在复诊沟通中前置预期管理。"
        )
        with self.assertRaises(ValueError) as ctx:
            require_ai_analysis_paragraphs(
                [bad_text],
                section_number="4.2",
                question_ref="q02",
                subtitle="药物治疗范围认知分析",
            )
        self.assertIn("q07", str(ctx.exception))

    def test_5_1_section_orchestration_is_rejected(self):
        from scripts.build_payload import choose_key_issue_analysis
        bad_para = (
            "第1段对应q02治疗范围认知：本次统计显示，30.97%的患者能正确识别。说明产品在适应证定位上需强化。表明在临床端应同步推进适应证沟通。整体看，应将适应证教育纳入复诊标准化流程作为差异化定位抓手。后续建议在产品沟通话术与复诊问询中主动提及该维度。"
        )
        with self.assertRaises(ValueError) as ctx:
            choose_key_issue_analysis([bad_para], expected_count=1)
        msg = str(ctx.exception)
        self.assertIn("5.1", msg)
        # Must catch either q02 leak or 第1段 leak.
        self.assertTrue("q02" in msg or "第" in msg)

    def test_5_2_internal_ref_is_rejected(self):
        from scripts.build_payload import choose_overall_analysis
        bad_paras = [
            "本次调研覆盖新疆地区，厄贝沙坦氢氯噻嗪片使用情况整体良好。表明产品在适应证识别与不良反应耐受层面获得多数患者正向反馈。",
            "用药规范方面，仅35.04%的患者能正确识别减停药须经医生评估，提示应加强门诊端红线告知。说明在复诊沟通中需要前置减停药红线。",
            "复查项目认知整体偏弱，三项关键指标认知度均未过半。表明后续应通过复查清单与随访表将血钾、肾功能纳入标准化必查项以提升监测覆盖率。",
        ]
        # Inject q07 leak into the second paragraph.
        bad_paras[1] += "反映与q07反馈形成相互印证。"
        with self.assertRaises(ValueError) as ctx:
            choose_overall_analysis(bad_paras, programmatic_reference=[], product="厄贝沙坦氢氯噻嗪片", region="新疆")
        self.assertIn("q07", str(ctx.exception))

    def test_5_3_internal_ref_is_rejected(self):
        from scripts.build_payload import choose_recommendations
        # 导语 ≥40 字
        intro = (
            "基于本次新疆地区厄贝沙坦氢氯噻嗪片患者认知调研结果，"
            "为系统提升疾病认知、规范用药与长期健康管理能力，提出以下建议："
        )
        # 3 numbered items, each 80-180 字
        items = [
            "1. 围绕减少每日服药次数这一诉求，建议在产品研发端加快推进缓释或长效剂型探索。在过渡期内通过医患沟通群、药店药师口头交代引导患者采用服药提醒卡与闹钟等辅助工具帮助其在现有方案下降低漏服与记忆负担。",
            "2. 聚焦疗效显著改善案例的口碑价值挖掘，应在复诊沟通中主动收集活动自如、睡眠改善、晨起僵硬减轻等典型场景下的患者证言。后续将证言整理为短视频与患者手册，依托医患沟通群与社区健康服务点开展本地化口碑传播。",
            "3. 针对复查项目认知偏窄问题，建议在复诊端提供血压+血钾+肾功能的三位一体复查清单与随访表，联动基层医院电子提醒系统将必查项结构化推送，药师在发药交代环节同步口头提示以巩固监测依从性。",
        ]
        # Inject q14 leak into the third item.
        items[2] += "与q14的改进方向相互呼应。"
        with self.assertRaises(ValueError) as ctx:
            choose_recommendations([intro] + items, fallback=[])
        self.assertIn("q14", str(ctx.exception))

    def test_front_matter_key_issue_refs_passes_preflight(self):
        """The key_issue_question_refs field uses q\\d+ as a data contract; it
        must not be caught by the guard because preflight only scans body
        text after parse_markdown_content strips front matter."""
        # The guard is applied per-paragraph, not on the raw front matter.
        # So a value like '["q02","q05"]' inside the front-matter string is
        # never fed to the guard. We verify the helper itself works on a
        # body-paragraph that legitimately contains no internal refs.
        from scripts.build_payload import require_ai_analysis_paragraphs
        # ≥250 字, 包含数字百分比, 判断词, 收束词
        clean_text = (
            "本次统计显示，30.97%的患者能正确识别厄贝沙坦氢氯噻嗪片适用于原发性高血压，"
            "但28.97%选择难治性高血压，26.97%选择继发性高血压，仅13.09%选择单纯收缩期高血压。"
            "表明患者对厄贝沙坦氢氯噻嗪片的适应证认知存在明显混淆，三类非首选适应证的合计"
            "占比超过六成。提示在复诊宣教、药店发药交代与药品说明书表达上，应进一步强化"
            "原发性高血压这一核心适应定位，减少跨适应证使用的认知偏差。整体看，认知分散度"
            "较高反映临床端需加强标准传递，后续可通过药师发药与医生复诊共同强化适应证沟通以提升认知一致性路径。"
        )
        # Should not raise on q\d+ leak.
        result = require_ai_analysis_paragraphs(
            [clean_text],
            section_number="4.2",
            question_ref="q02",
            subtitle="药物治疗范围认知分析",
        )
        self.assertEqual(result, [clean_text])


class TestFinalValidatorIntegration(unittest.TestCase):
    """The final docx must contain zero q\\d+ strings in any visible node."""

    def test_clean_docx_passes(self):
        """If no fixture docx with clean text is at hand, validate the
        guard against a synthetic list of node texts instead — that is
        exactly what the validator function does."""
        from scripts.final_validate_docx import _validate_no_internal_refs_leaked
        # Should not raise.
        _validate_no_internal_refs_leaked([
            "厄贝沙坦氢氯噻嗪片治疗范围认知方面，30.97%的患者……",
            "本次统计显示，46.99%的患者认为改善明显。",
            "随访表与口服提醒卡的组合可有效提升复诊依从性。",
        ])

    def test_leaked_q07_fails(self):
        from scripts.final_validate_docx import (
            FinalValidationError,
            _validate_no_internal_refs_leaked,
        )
        with self.assertRaises(FinalValidationError) as ctx:
            _validate_no_internal_refs_leaked([
                "厄贝沙坦氢氯噻嗪片治疗范围认知方面，30.97%的患者……",
                "本次统计显示，46.99%的患者……，与q07反馈形成相互印证。",
            ])
        self.assertIn("q07", str(ctx.exception))
        self.assertIn("node #2", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
