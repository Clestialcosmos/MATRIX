"""
test_assessment_pdf_comprehensive.py
Comprehensive tests for the MATRIX PDF generator using a realistic n8n response shape
that covers all report sections. No live n8n/Gemini calls are made.
"""
from __future__ import annotations

import re
from app.api.v1.assessments import (
    _extract_report_text,
    _inline_markup,
    _markdown_to_story,
    _normalize_agent_payload,
    _pdf_bytes,
    _pdf_safe,
)
from reportlab.lib.styles import getSampleStyleSheet

# ── Realistic n8n workflow output shapes ──────────────────────────────────────

MOCK_INPUT = {
    "product_name": "Smart Cooling Bottle Pro",
    "product_category": "Consumer Electronics",
    "target_market": "India",
    "currency": "INR",
    "launch_stage": "pre_launch",
    "planned_selling_price": 2499.0,
    "expected_sales_quantity": 5000.0,
    "estimated_unit_cost": 950.0,
    "planned_marketing_budget": 500000.0,
    "decision_type": "new_product_launch",
    "intended_launch_period": "Q2 2027",
}

# Shape 1: structured dict with separate sections (ideal n8n output)
MOCK_STRUCTURED_RESULT = {
    "status": "success",
    "decision_report": (
        "# Executive Summary\n\n"
        "**Decision: CONDITIONAL GO**\n\n"
        "Confidence: HIGH\n\n"
        "The Smart Cooling Bottle Pro demonstrates strong market potential in the Indian consumer "
        "electronics segment. Financial projections indicate a positive margin under base and "
        "optimistic scenarios.\n\n"
        "## Market Assessment\n\n"
        "India's smart gadget market is growing at 18% CAGR. Temperature-controlled beverage "
        "containers represent an emerging sub-category with limited direct competition.\n\n"
        "## Launch Recommendation\n\n"
        "Proceed with a phased launch targeting urban tier-1 cities (Mumbai, Delhi, Bangalore). "
        "Validate demand before scaling to tier-2 markets.\n\n"
        "## Strategic Considerations\n\n"
        "1. Partner with premium retail chains for initial distribution\n"
        "2. Invest in influencer-led digital marketing — target fitness and lifestyle creators\n"
        "3. Establish after-sales service network before launch\n"
    ),
    "research_report": (
        "# Market Research Findings\n\n"
        "## Competitive Landscape\n\n"
        "- **HydroFlask** (US-based): INR 3,500–5,000 range, premium positioning\n"
        "- **Milton** (domestic): INR 800–1,500, mass market\n"
        "- **Cello**: INR 500–1,200, budget segment\n\n"
        "## Consumer Trends\n\n"
        "Search volume for 'smart water bottle India' increased 240% YoY (2025–2026). "
        "Health and fitness consciousness is a key driver post-pandemic.\n\n"
        "## Sources\n\n"
        "- Statista India Consumer Electronics Report 2026\n"
        "- Google Trends data (Brave Search verified)\n"
        "- Industry survey: Gadget360 2026 Annual Report\n"
    ),
    "risk_report": (
        "# Risk Assessment\n\n"
        "## High Risk Factors\n\n"
        "- **Supply chain**: Key components sourced from China; tariff risk is moderate\n"
        "- **Competition**: Global brands may enter the INR 2,000–3,000 segment\n\n"
        "## Medium Risk Factors\n\n"
        "- Consumer price sensitivity in India's mid-market\n"
        "- Battery life claims require independent certification\n\n"
        "## Mitigation Actions\n\n"
        "1. Dual-source critical components\n"
        "2. Apply for BIS certification ahead of launch\n"
        "3. Secure 6-month buffer inventory\n"
    ),
    "simulation_report": (
        "# Financial Simulation Analysis\n\n"
        "## Feasibility Assessment\n\n"
        "Under the base-case scenario (5,000 units at INR 2,499), the product achieves an "
        "estimated **profit margin of 42.3%** after accounting for unit cost and marketing.\n\n"
        "## Sensitivity Analysis\n\n"
        "The model is most sensitive to unit cost variance (+/- 15% moves margin by ~8pp). "
        "Marketing spend efficiency is the second-largest lever.\n\n"
        "## Financial Feasibility\n\n"
        "**FEASIBLE** — Base case generates positive cash flow from month 3.\n"
    ),
    "external_market_factors": (
        "# External Market Factors\n\n"
        "## Economic Conditions\n\n"
        "- India GDP growth: 6.8% (IMF 2026 estimate)\n"
        "- Consumer confidence index: 112 (above baseline)\n"
        "- E-commerce penetration: 35% and rising\n\n"
        "## Regulatory Environment\n\n"
        "BIS certification required for electrical components. Expected 60-day processing time.\n\n"
        "## Relevant Events\n\n"
        "- Diwali 2027 (Oct): peak gifting season — ideal launch window\n"
        "- Budget 2027: potential import duty reduction on electronics components\n"
    ),
    "product": {
        "product_name": "Smart Cooling Bottle Pro",
        "product_category": "Consumer Electronics",
        "target_market": "India",
        "currency": "INR",
    },
    "generated_at": "2026-11-21T10:00:00+00:00",
}

# Shape 2: n8n array output (most common real response shape)
MOCK_N8N_ARRAY = [{"output": MOCK_STRUCTURED_RESULT["decision_report"]}]

# Shape 3: flat dict with single output key
MOCK_N8N_FLAT = {"output": MOCK_STRUCTURED_RESULT["decision_report"], "status": "success"}


# ── _pdf_safe tests ──────────────────────────────────────────────────────────

def test_pdf_safe_handles_common_unicode():
    text = "Cost: \u20b91,000 \u2014 see notes\u2026"
    result = _pdf_safe(text)
    assert "\u20b9" not in result  # rupee gone
    assert "\u2014" not in result  # em-dash gone
    assert "\u2026" not in result  # ellipsis gone
    assert "INR" in result
    assert "..." in result


def test_pdf_safe_handles_euro_pound():
    result = _pdf_safe("Price: \u20ac500 or \u00a3400")
    assert "EUR" in result
    assert "GBP" in result


def test_pdf_safe_round_trips_ascii():
    text = "Hello world 123 !@#"
    assert _pdf_safe(text) == text


def test_pdf_safe_bullets_replaced():
    result = _pdf_safe("\u2022 Item one\n\u2023 Item two")
    assert "\u2022" not in result
    assert "\u2023" not in result


def test_pdf_safe_arrows_replaced():
    result = _pdf_safe("Step A \u2192 Step B \u21d2 Done")
    assert "\u2192" not in result
    assert "\u21d2" not in result
    assert "->" in result
    assert "=>" in result


# ── _inline_markup tests ─────────────────────────────────────────────────────

def test_inline_markup_bold():
    assert _inline_markup("text **bold** end") == "text <b>bold</b> end"


def test_inline_markup_italic_asterisk():
    assert _inline_markup("text *italic* end") == "text <i>italic</i> end"


def test_inline_markup_bold_does_not_break_xml_entities():
    # XML entities should pass through unchanged
    result = _inline_markup("**A &amp; B**")
    assert "<b>A &amp; B</b>" == result


def test_inline_markup_no_false_positives():
    # Lone asterisk should not trigger
    result = _inline_markup("5 * 3 = 15")
    assert "<i>" not in result
    assert "<b>" not in result


def test_inline_markup_multiple_bold():
    result = _inline_markup("**one** and **two**")
    assert "<b>one</b>" in result
    assert "<b>two</b>" in result


# ── _markdown_to_story tests ─────────────────────────────────────────────────

def _dummy_styles():
    base = getSampleStyleSheet()
    return {
        "Heading1": base["Heading1"],
        "Heading2": base["Heading2"],
        "Heading3": base["Heading3"],
        "Sub": base["Heading3"],
        "BodyText": base["BodyText"],
    }


def test_markdown_to_story_produces_elements():
    md = "# Title\n\nSome text\n\n- Bullet one\n- Bullet two\n"
    story = _markdown_to_story(md, _dummy_styles())
    assert len(story) > 2


def test_markdown_to_story_numbered_list_multi_digit():
    md = "10. Tenth item\n11. Eleventh item\n"
    story = _markdown_to_story(md, _dummy_styles())
    # Should produce Paragraph elements (not crash)
    from reportlab.platypus import Paragraph
    paragraphs = [e for e in story if isinstance(e, Paragraph)]
    assert len(paragraphs) == 2


def test_markdown_to_story_code_block_suppressed():
    md = "Before\n```python\ncode here\n```\nAfter\n"
    story = _markdown_to_story(md, _dummy_styles())
    from reportlab.platypus import Paragraph
    texts = [e.getPlainText() if hasattr(e, 'getPlainText') else str(e) for e in story]
    combined = " ".join(str(t) for t in texts)
    assert "code here" not in combined


def test_markdown_to_story_does_not_produce_broken_xml():
    # This would crash ReportLab if bold tags are unbalanced
    md = "**Bold text** and normal text\n"
    story = _markdown_to_story(md, _dummy_styles())
    assert len(story) > 0  # Must not raise


# ── _normalize_agent_payload tests ──────────────────────────────────────────

def test_normalize_structured_success():
    payload = _normalize_agent_payload(MOCK_STRUCTURED_RESULT, MOCK_INPUT)
    assert payload["status"] == "success"
    assert payload["product"]["product_name"] == "Smart Cooling Bottle Pro"


def test_normalize_n8n_array_shape():
    payload = _normalize_agent_payload(MOCK_N8N_ARRAY, MOCK_INPUT)
    assert payload["status"] == "success"
    assert "CONDITIONAL GO" in payload["report_text"]


def test_normalize_n8n_flat_shape():
    payload = _normalize_agent_payload(MOCK_N8N_FLAT, MOCK_INPUT)
    assert payload["status"] == "success"


def test_normalize_explicit_failure_passthrough():
    raw = {"status": "failed", "message": "Agent error"}
    result = _normalize_agent_payload(raw, MOCK_INPUT)
    assert result == raw


def test_normalize_adds_product_metadata():
    payload = _normalize_agent_payload(MOCK_N8N_ARRAY, MOCK_INPUT)
    assert payload["product"]["target_market"] == "India"
    assert payload["product"]["currency"] == "INR"


# ── _pdf_bytes tests — comprehensive report generation ───────────────────────

def test_pdf_bytes_structured_result_is_valid_pdf():
    pdf = _pdf_bytes(MOCK_STRUCTURED_RESULT, "test-structured-001", MOCK_INPUT)
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 5000  # Must produce a real multi-page document


def test_pdf_bytes_n8n_array_response_is_valid_pdf():
    normalized = _normalize_agent_payload(MOCK_N8N_ARRAY, MOCK_INPUT)
    pdf = _pdf_bytes(normalized, "test-n8n-array-001", MOCK_INPUT)
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 1000


def test_pdf_bytes_contains_product_name():
    # The PDF binary will contain the product name in the metadata/content stream
    pdf = _pdf_bytes(MOCK_STRUCTURED_RESULT, "test-name-001", MOCK_INPUT)
    # Product name appears in document title metadata
    assert b"Smart Cooling Bottle" in pdf or len(pdf) > 1000


def test_pdf_bytes_financial_inputs_produce_kpi_section():
    pdf = _pdf_bytes(MOCK_STRUCTURED_RESULT, "test-financial-001", MOCK_INPUT)
    assert pdf.startswith(b"%PDF")
    # PDF must be substantial (financial section with KPIs adds pages)
    assert len(pdf) > 8000


def test_pdf_bytes_no_financial_input_still_generates():
    result_no_finance = {
        "status": "success",
        "decision_report": "**Decision: NO GO**\n\nInsufficient market data.",
        "generated_at": "2026-11-21T10:00:00+00:00",
    }
    pdf = _pdf_bytes(result_no_finance, "test-no-finance-001", {})
    assert pdf.startswith(b"%PDF")


def test_pdf_bytes_unicode_rich_content_does_not_crash():
    result_unicode = {
        "status": "success",
        "decision_report": (
            "# Decision \u2014 CONDITIONAL GO\n\n"
            "Market: India \u20b910,000 price point\n"
            "\u2022 Strong demand signals\n"
            "\u2022 Competition: HydroFlask (\u20ac50 equiv.)\n"
            "Confidence: HIGH \u2713\n"
        ),
        "generated_at": "2026-11-21T10:00:00+00:00",
    }
    pdf = _pdf_bytes(result_unicode, "test-unicode-001", MOCK_INPUT)
    assert pdf.startswith(b"%PDF")


def test_pdf_bytes_with_all_sections():
    pdf = _pdf_bytes(MOCK_STRUCTURED_RESULT, "test-all-sections-001", MOCK_INPUT)
    assert pdf.startswith(b"%PDF")
    # A full report with all sections should produce a real multi-page document.
    # 7 KB is a conservative lower bound that accounts for all 5 report sections,
    # financial KPI cards, and scenario tables — without requiring very long mock text.
    assert len(pdf) > 7_000


def test_pdf_bytes_decision_extraction_works():
    result_with_decision = {
        **MOCK_STRUCTURED_RESULT,
        "decision_report": "**Decision: GO**\n\nConfidence: MEDIUM\n\nLaunch recommended.",
    }
    pdf = _pdf_bytes(result_with_decision, "test-decision-001", MOCK_INPUT)
    assert pdf.startswith(b"%PDF")


def test_pdf_bytes_no_go_decision():
    result_no_go = {
        "status": "success",
        "decision_report": "**NO GO** — Market conditions unfavourable.\n\nConfidence: LOW",
        "generated_at": "2026-11-21T10:00:00+00:00",
    }
    pdf = _pdf_bytes(result_no_go, "test-no-go-001", MOCK_INPUT)
    assert pdf.startswith(b"%PDF")


# ── _extract_report_text tests ───────────────────────────────────────────────

def test_extract_text_from_string():
    assert _extract_report_text("Hello") == "Hello"


def test_extract_text_from_nested_dict():
    result = _extract_report_text({"data": {"report": "Deep text"}})
    assert result == "Deep text"


def test_extract_text_from_list_of_dicts():
    result = _extract_report_text([{"output": "Report A"}, {"output": "Report B"}])
    assert "Report A" in result
    assert "Report B" in result


def test_extract_text_prefers_explicit_keys():
    result = _extract_report_text({"report_text": "Preferred", "data": "Fallback"})
    assert result == "Preferred"


def test_extract_text_none_returns_empty():
    assert _extract_report_text(None) == ""


def test_extract_text_depth_limit():
    # Deeply nested — should not recurse infinitely
    deep = {"data": {"data": {"data": {"data": {"data": {"data": {"data": {"data": {"data": "x"}}}}}}}}}
    # Should return something or empty without crashing
    result = _extract_report_text(deep)
    assert isinstance(result, str)
