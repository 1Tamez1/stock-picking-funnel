from __future__ import annotations

import unittest
from pathlib import Path

from funnel_app.template_parser import parse_markdown_template


ROOT = Path(__file__).resolve().parents[1]
SOURCE_TEMPLATE_V4 = (
    ROOT.parent
    / "Source_Candidates"
    / "approved_version"
    / "stock_candidate_screening_questionnaire_v4.md"
)
SOURCE_TEMPLATE = (
    ROOT.parent
    / "Source_Candidates"
    / "approved_version"
    / "stock_candidate_screening_questionnaire_v5.md"
)
MANAGEMENT_TEMPLATE = (
    ROOT.parent
    / "Source_Candidates"
    / "approved_version"
    / "stock_candidate_management_underwriting_questionnaire_v1.md"
)
BUSINESS_TEMPLATE = (
    ROOT.parent
    / "Source_Candidates"
    / "approved_version"
    / "stock_candidate_business_underwriting_questionnaire_v2.md"
)
FINANCIAL_TEMPLATE = (
    ROOT.parent
    / "Source_Candidates"
    / "approved_version"
    / "stock_candidate_financial_underwriting_questionnaire_v1.md"
)
VALUATION_TEMPLATE = ROOT / "config" / "templates" / "stock_candidate_valuation_and_position_size_questionnaire_v2.md"
EXECUTION_TEMPLATE = ROOT / "config" / "templates" / "stock_candidate_execution_rules_questionnaire_v1.md"
DATA_COLLECTION_TEMPLATE = ROOT / "config" / "templates" / "data_collection.md"


class TemplateParserTest(unittest.TestCase):
    def normalize_screening_schema(self, schema: dict) -> list[tuple[str, tuple[tuple[str, str, tuple[str, ...]], ...]]]:
        normalized = []
        for section in schema["sections"]:
            if section["title"] == "If It Is Redirected":
                continue
            title = section["title"]
            if title.startswith("Stock Candidate Screening Questionnaire v"):
                title = "Stock Candidate Screening Questionnaire"
            fields = []
            for field in section["fields"]:
                label = field["label"].replace("If Archive or Redirect, primary reason", "If Archive, primary reason")
                options = tuple(option for option in field.get("options", []) if option != "Redirect")
                fields.append((label, field["kind"], options))
            normalized.append((title, tuple(fields)))
        return normalized

    def test_source_screening_template_extracts_sections_and_fields(self) -> None:
        schema = parse_markdown_template(SOURCE_TEMPLATE.read_text(encoding="utf-8"))

        self.assertGreaterEqual(schema["section_count"], 25)
        self.assertGreaterEqual(schema["field_count"], 200)
        titles = [section["title"] for section in schema["sections"]]
        self.assertIn("Part I. Fast Kill Screen", titles)
        self.assertIn("Part X. Decision Sheet", titles)

    def test_parser_extracts_table_questions_from_v5(self) -> None:
        schema = parse_markdown_template(SOURCE_TEMPLATE.read_text(encoding="utf-8"))
        labels = {field["label"]: field for field in schema["fields"]}

        fast_kill = "Can I explain the business in two plain-language sentences?"
        self.assertIn(fast_kill, labels)
        self.assertEqual(labels[fast_kill]["kind"], "select")
        self.assertEqual(labels[fast_kill]["options"], ["Yes", "No", "Unknown"])
        self.assertIn("Business quality - Rating", labels)
        self.assertNotIn("If It Is Redirected", [section["title"] for section in schema["sections"]])
        result_fields = [field for field in schema["fields"] if field["label"] == "Result"]
        self.assertTrue(result_fields)
        self.assertTrue(all("Redirect" not in field.get("options", []) for field in result_fields))

    def test_v5_matches_v4_screening_shape_after_redirect_cleanup(self) -> None:
        if not SOURCE_TEMPLATE_V4.exists():
            self.skipTest("Historical v4 screening questionnaire is not present in this workspace.")
        v4_schema = parse_markdown_template(SOURCE_TEMPLATE_V4.read_text(encoding="utf-8"))
        v5_schema = parse_markdown_template(SOURCE_TEMPLATE.read_text(encoding="utf-8"))

        self.assertEqual(
            self.normalize_screening_schema(v4_schema),
            self.normalize_screening_schema(v5_schema),
        )

    def test_parser_infers_field_types(self) -> None:
        markdown = """
# Demo Template

## Basic Inputs

- Current share price:
- Review date:

## Decision

**Result**: Pass / Watchlist / Archive

- Explain the business.

**Answer**:
"""
        schema = parse_markdown_template(markdown)
        fields = {field["label"]: field for field in schema["fields"]}

        self.assertEqual(fields["Current share price"]["kind"], "metric")
        self.assertEqual(fields["Review date"]["kind"], "date")
        self.assertEqual(fields["Result"]["kind"], "select")
        self.assertEqual(fields["Result"]["options"], ["Pass", "Watchlist", "Archive"])
        self.assertEqual(fields["Explain the business."]["kind"], "textarea")

    def test_parser_only_splits_real_slash_delimited_option_lists(self) -> None:
        markdown = """
# Demo Template

## Methods

- Primary valuation method: Owner earnings / FCFE / earning power
- Cross-check basis: Peak-year P/E or peak margin DCF
- Reserve cross-check: Reserve / credit / capital adequacy cross-check
"""
        schema = parse_markdown_template(markdown)
        fields = {field["label"]: field for field in schema["fields"]}

        self.assertEqual(fields["Primary valuation method"]["kind"], "select")
        self.assertEqual(fields["Primary valuation method"]["options"], ["Owner earnings", "FCFE", "earning power"])
        self.assertEqual(fields["Cross-check basis"]["kind"], "text")
        self.assertEqual(fields["Reserve cross-check"]["kind"], "select")
        self.assertEqual(
            fields["Reserve cross-check"]["options"],
            ["Reserve", "credit", "capital adequacy cross-check"],
        )

    def test_table_parser_does_not_break_finance_tokens_with_inline_slashes(self) -> None:
        markdown = """
# Demo Template

## Cross-Check Table

| Check | Value |
| --- | --- |
| Multiple basis | Peak-year P/E or peak margin DCF |
| Method set | Owner earnings / FCFE / earning power |
"""
        schema = parse_markdown_template(markdown)
        fields = {field["label"]: field for field in schema["fields"]}

        self.assertEqual(fields["Multiple basis - Value"]["kind"], "textarea")
        self.assertEqual(fields["Method set - Value"]["kind"], "select")
        self.assertEqual(fields["Method set - Value"]["options"], ["Owner earnings", "FCFE", "earning power"])

    def test_management_template_extracts_sections_and_fields(self) -> None:
        schema = parse_markdown_template(MANAGEMENT_TEMPLATE.read_text(encoding="utf-8"))

        self.assertGreaterEqual(schema["section_count"], 25)
        self.assertGreaterEqual(schema["field_count"], 250)
        titles = [section["title"] for section in schema["sections"]]
        self.assertIn("Inherited From Business Underwriting", titles)
        self.assertIn("Part I. Business Handoff And Delta Thesis", titles)
        self.assertIn("Part XI. Decision Sheet", titles)

    def test_management_template_parser_extracts_table_questions(self) -> None:
        schema = parse_markdown_template(MANAGEMENT_TEMPLATE.read_text(encoding="utf-8"))
        labels = {field["label"]: field for field in schema["fields"]}

        fast_kill = "Is there clear evidence of honesty, candor, and owner orientation?"
        self.assertIn(fast_kill, labels)
        self.assertEqual(labels[fast_kill]["kind"], "select")
        self.assertEqual(labels[fast_kill]["options"], ["Yes", "No", "Unknown"])
        self.assertIn("Business Underwriting document reviewed", labels)
        self.assertIn("Proxy or remuneration years reviewed", labels)
        self.assertEqual(labels["Proxy or remuneration years reviewed"]["kind"], "text")
        self.assertIn("Owner orientation - Rating", labels)
        self.assertIn("Fast Kill Result", labels)
        self.assertEqual(labels["Fast Kill Result"]["kind"], "select")
        self.assertEqual(labels["Fast Kill Result"]["options"], ["Continue", "Watchlist", "Archive"])
        self.assertEqual(labels["Evidence Result"]["kind"], "select")
        self.assertEqual(labels["Evidence Result"]["options"], ["Adequate", "Thin", "One-Sided", "Promotional"])
        self.assertEqual(labels["Capital-intensity read inherited from Business Underwriting"]["kind"], "text")
        self.assertEqual(labels["Capital-allocation quick read"]["kind"], "text")

    def test_business_underwriting_template_extracts_sections_and_fields(self) -> None:
        schema = parse_markdown_template(BUSINESS_TEMPLATE.read_text(encoding="utf-8"))

        self.assertGreaterEqual(schema["section_count"], 30)
        self.assertGreaterEqual(schema["field_count"], 330)
        titles = [section["title"] for section in schema["sections"]]
        self.assertIn("Inherited From Screening", titles)
        self.assertIn("Part XII. Decision Sheet", titles)

    def test_business_underwriting_template_parser_extracts_key_questionnaire_fields(self) -> None:
        schema = parse_markdown_template(BUSINESS_TEMPLATE.read_text(encoding="utf-8"))
        labels = {field["label"]: field for field in schema["fields"]}
        final_decision_section = next(section for section in schema["sections"] if section["title"] == "Final Decision")
        final_decision_field = next(field for field in final_decision_section["fields"] if field["label"] == "Decision")

        self.assertIn("Customer or end-user evidence obtained?", labels)
        self.assertEqual(labels["Customer or end-user evidence obtained?"]["kind"], "select")
        self.assertEqual(labels["Customer or end-user evidence obtained?"]["options"], ["Yes", "No"])
        self.assertIn("Business claim that must be true 1 - Thesis condition", labels)
        self.assertEqual(labels["Business claim that must be true 1 - Thesis condition"]["kind"], "textarea")
        self.assertIn("Pass Business Underwriting", final_decision_field["options"])

    def test_financial_underwriting_template_extracts_sections_and_fields(self) -> None:
        schema = parse_markdown_template(FINANCIAL_TEMPLATE.read_text(encoding="utf-8"))

        self.assertGreaterEqual(schema["section_count"], 35)
        self.assertGreaterEqual(schema["field_count"], 560)
        titles = [section["title"] for section in schema["sections"]]
        self.assertIn("Inherited From Management Underwriting", titles)
        self.assertIn("Part VI. Core Financial Worksheets", titles)
        self.assertIn("Part XI. Decision Sheet", titles)

    def test_financial_underwriting_template_parser_extracts_key_questionnaire_fields(self) -> None:
        schema = parse_markdown_template(FINANCIAL_TEMPLATE.read_text(encoding="utf-8"))
        labels = {field["label"]: field for field in schema["fields"]}
        final_decision_section = next(section for section in schema["sections"] if section["title"] == "Final Decision")
        final_decision_field = next(field for field in final_decision_section["fields"] if field["label"] == "Decision")

        self.assertIn("Can owner earnings be approximated without heroic assumptions?", labels)
        self.assertEqual(labels["Can owner earnings be approximated without heroic assumptions?"]["kind"], "select")
        self.assertEqual(labels["Can owner earnings be approximated without heroic assumptions?"]["options"], ["Yes", "No", "Unknown"])
        self.assertIn("Reported earnings", labels)
        self.assertEqual(labels["Reported earnings"]["kind"], "metric")
        self.assertIn("Owner earnings yield on enterprise value", labels)
        self.assertEqual(labels["Owner earnings yield on enterprise value"]["kind"], "metric")
        self.assertIn("Debt / lease / pension / reserve roll-forwards built", labels)
        self.assertEqual(labels["Debt / lease / pension / reserve roll-forwards built"]["kind"], "text")
        self.assertEqual(labels["Owner earnings view"]["kind"], "text")
        self.assertEqual(labels["Returns on capital view"]["kind"], "text")
        self.assertEqual(labels["Per-share value-creation view"]["kind"], "text")
        self.assertIn("Return to Business Underwriting", final_decision_field["options"])
        self.assertIn("Return to Management Underwriting", final_decision_field["options"])

    def test_valuation_template_extracts_sections_and_fields(self) -> None:
        schema = parse_markdown_template(VALUATION_TEMPLATE.read_text(encoding="utf-8"))

        self.assertGreaterEqual(schema["section_count"], 35)
        self.assertGreaterEqual(schema["field_count"], 520)
        titles = [section["title"] for section in schema["sections"]]
        self.assertIn("Inherited From Financial Underwriting", titles)
        self.assertIn("Part VIII. Position Size Decision", titles)
        self.assertIn("Part XI. Decision Sheet", titles)

    def test_valuation_template_parser_extracts_key_questionnaire_fields(self) -> None:
        schema = parse_markdown_template(VALUATION_TEMPLATE.read_text(encoding="utf-8"))
        labels = {field["label"]: field for field in schema["fields"]}
        final_decision_section = next(section for section in schema["sections"] if section["title"] == "Final Decision")
        final_decision_field = next(field for field in final_decision_section["fields"] if field["label"] == "Decision")

        self.assertIn("Is Financial Underwriting complete enough to support valuation?", labels)
        self.assertEqual(labels["Is Financial Underwriting complete enough to support valuation?"]["kind"], "select")
        self.assertEqual(labels["Is Financial Underwriting complete enough to support valuation?"]["options"], ["Yes", "No", "Unknown"])
        self.assertIn("If one of the above is true, what must I do about it?", labels)
        self.assertEqual(labels["If one of the above is true, what must I do about it?"]["kind"], "textarea")
        self.assertIn("I am anchoring to a past high or low instead of value.", labels)
        self.assertEqual(labels["I am anchoring to a past high or low instead of value."]["kind"], "checkbox")
        self.assertEqual(labels["Retained-capital read inherited"]["kind"], "text")
        self.assertEqual(labels["Current best alternative use of capital"]["kind"], "text")
        self.assertEqual(labels["Enterprise-first or equity-first"]["kind"], "text")
        self.assertIn("Approve For Execution", final_decision_field["options"])
        self.assertIn("Return To Underwriting", final_decision_field["options"])

    def test_execution_template_extracts_sections_and_fields(self) -> None:
        schema = parse_markdown_template(EXECUTION_TEMPLATE.read_text(encoding="utf-8"))

        self.assertGreaterEqual(schema["section_count"], 50)
        self.assertGreaterEqual(schema["field_count"], 360)
        titles = [section["title"] for section in schema["sections"]]
        self.assertIn("Part I. Valuation Handoff And Execution Delta Thesis", titles)
        self.assertIn("Part VII. Monitoring And Return-To-Underwriting Triggers", titles)
        self.assertIn("Part XI. Decision Sheet", titles)

    def test_execution_template_parser_extracts_key_questionnaire_fields(self) -> None:
        schema = parse_markdown_template(EXECUTION_TEMPLATE.read_text(encoding="utf-8"))
        labels = {field["label"]: field for field in schema["fields"]}
        final_decision_section = next(section for section in schema["sections"] if section["title"] == "Final Decision")
        final_decision_field = next(field for field in final_decision_section["fields"] if field["label"] == "Decision")

        self.assertIn("Is the prior underwriting still current enough to act on?", labels)
        self.assertEqual(labels["Is the prior underwriting still current enough to act on?"]["kind"], "select")
        self.assertEqual(labels["Is the prior underwriting still current enough to act on?"]["options"], ["Yes", "No", "Unknown"])
        self.assertIn("Company - Value", labels)
        self.assertEqual(labels["Company - Value"]["kind"], "textarea")
        self.assertIn("Business - Correct stage", labels)
        self.assertEqual(labels["Business - Correct stage"]["kind"], "select")
        self.assertEqual(labels["Business - Correct stage"]["options"], ["Business Underwriting", "Valuation", "Execution"])
        self.assertEqual(labels["Fast Kill Result"]["kind"], "select")
        self.assertIn("Buy Small Only", labels["Fast Kill Result"]["options"])
        self.assertEqual(labels["Re-entry allowed later?"]["kind"], "select")
        self.assertEqual(labels["Re-entry allowed later?"]["options"], ["Yes", "No"])
        self.assertIn("Execute Starter Now", final_decision_field["options"])
        self.assertIn("Enter Staged Orders", final_decision_field["options"])
        self.assertIn("Hold Existing", final_decision_field["options"])
        self.assertIn("Trim", final_decision_field["options"])
        self.assertIn("Exit", final_decision_field["options"])
        self.assertIn("Return To Underwriting", final_decision_field["options"])

    def test_data_collection_template_exposes_screening_handoff_fields(self) -> None:
        schema = parse_markdown_template(DATA_COLLECTION_TEMPLATE.read_text(encoding="utf-8"))
        labels = {field["label"]: field for field in schema["fields"]}

        self.assertIn("Next action", labels)
        self.assertIn("Main missing input", labels)
        self.assertIn("Verify manually against original source", labels)
        self.assertIn("Revisit if better sources appear", labels)
        self.assertIn("Summary", labels)
        self.assertEqual(labels["Reporting currency"]["kind"], "text")
        self.assertEqual(labels["Summary"]["kind"], "textarea")

    def test_screening_template_exposes_agent_fillable_fields(self) -> None:
        schema = parse_markdown_template(SOURCE_TEMPLATE.read_text(encoding="utf-8"))
        labels = {field["label"]: field for field in schema["fields"]}

        self.assertIn("Can the business be explained without jargon?", labels)
        self.assertEqual(labels["Can the business be explained without jargon?"]["kind"], "select")
        self.assertEqual(labels["Can the business be explained without jargon?"]["id"].startswith("custom-"), True)
        self.assertIn("Business Underwriting handoff 1", labels)
        self.assertEqual(labels["Business Underwriting handoff 1"]["kind"], "textarea")
        self.assertIn("Most important bias risk", labels)
        self.assertEqual(labels["Most important bias risk"]["kind"], "textarea")
        self.assertIn("What must be true? 1 - Thesis condition", labels)
        self.assertEqual(labels["What must be true? 1 - Thesis condition"]["kind"], "textarea")
        self.assertIn("What would need to change before revisiting?", labels)
        self.assertEqual(labels["Review date, if Watchlist"]["kind"], "date")


if __name__ == "__main__":
    unittest.main()
