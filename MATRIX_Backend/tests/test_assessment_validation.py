import pytest
from pydantic import ValidationError
from app.api.v1.assessments import AssessmentInput

BASE = {
    "product_name": "Northstar", "target_market": "India", "decision_type": "new_product_launch",
    "currency": "inr", "product_category": "Electronics", "launch_stage": "pre_launch",
    "planned_selling_price": 1000, "expected_sales_quantity": 500,
    "estimated_unit_cost": 500, "planned_marketing_budget": 10000,
}

def test_assessment_normalizes_currency_and_stage():
    item = AssessmentInput.model_validate(BASE)
    assert item.currency == "INR"
    assert item.launch_stage == "pre_launch"

def test_assessment_rejects_non_prelaunch():
    with pytest.raises(ValidationError):
        AssessmentInput.model_validate({**BASE, "launch_stage": "concept"})

def test_assessment_rejects_invalid_currency():
    with pytest.raises(ValidationError):
        AssessmentInput.model_validate({**BASE, "currency": "ZZZ"})

def test_assessment_requires_positive_price_and_quantity():
    with pytest.raises(ValidationError):
        AssessmentInput.model_validate({**BASE, "planned_selling_price": 0})
    with pytest.raises(ValidationError):
        AssessmentInput.model_validate({**BASE, "expected_sales_quantity": 0})
