from app.api.v1.assessments import _normalize_agent_payload, _extract_report_text, _pdf_bytes

INPUT = {
    "product_name": "Smart Cooling Bottle",
    "product_category": "Electronics",
    "target_market": "India",
    "currency": "INR",
}

REPORT = """### 1. Executive Summary

This report assesses the Smart Cooling Bottle.

### 2. Preliminary Decision

**CONDITIONAL GO**

Proceed only after validating demand.
"""

def test_normalizes_n8n_array_output_to_success():
    raw = [{"output": REPORT}]
    normalized = _normalize_agent_payload(raw, INPUT)
    assert normalized["status"] == "success"
    assert normalized["report_text"] == REPORT.strip()
    assert normalized["product"]["product_name"] == "Smart Cooling Bottle"

def test_normalizes_n8n_object_output_to_success():
    normalized = _normalize_agent_payload({"output": REPORT}, INPUT)
    assert normalized["status"] == "success"
    assert "CONDITIONAL GO" in normalized["report_text"]

def test_keeps_explicit_agent_failure():
    raw = {"status": "failed", "message": "provider error"}
    normalized = _normalize_agent_payload(raw, INPUT)
    assert normalized == raw

def test_pdf_contains_report_text_and_is_pdf():
    normalized = _normalize_agent_payload([{"output": REPORT}], INPUT)
    pdf = _pdf_bytes(normalized, "assessment-test")
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 1000

def test_extracts_text_from_nested_n8n_wrapper():
    assert _extract_report_text({"body": {"data": [{"text": "Full report"}]}}) == "Full report"
