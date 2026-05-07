import pytest
from pydantic import ValidationError

from mcp_defectdojo.models import (
    ProductSummary,
    EngagementSummary,
    TestSummary,
    FindingSummary,
    SeverityEnum,
    PaginationMetadata,
)


def test_product_summary_valid(sample_product):
    product = ProductSummary(**sample_product)
    assert product.id == 1
    assert product.name == "Test Product"
    assert product.description == "A test product"
    assert product.prod_type == 1


def test_product_summary_missing_field():
    with pytest.raises(ValidationError):
        ProductSummary(id=1, description="No name", prod_type=1)


def test_engagement_summary_alias(sample_engagement):
    engagement = EngagementSummary(**sample_engagement)
    assert engagement.product_id == 2


def test_engagement_summary_optional_name():
    engagement = EngagementSummary(
        id=1, product=2, target_start="2026-01-01", target_end="2026-12-31"
    )
    assert engagement.name is None


def test_test_summary_alias(sample_test_obj):
    test_obj = TestSummary(**sample_test_obj)
    assert test_obj.engagement_id == 3


def test_finding_summary_all_fields(sample_finding):
    finding = FindingSummary(**sample_finding)
    assert finding.id == 1
    assert finding.test_id == 4
    assert finding.title == "XSS Vuln"
    assert finding.severity == "High"
    assert finding.description == "Found XSS"
    assert finding.active is True
    assert finding.verified is False
    assert finding.mitigated is None
    assert finding.is_mitigated is False
    assert finding.out_of_scope is False
    assert finding.false_p is False
    assert finding.duplicate is False


def test_finding_summary_missing_required():
    with pytest.raises(ValidationError):
        FindingSummary(
            id=1,
            test=4,
            severity="High",
            description="Found XSS",
            active=True,
            verified=False,
            is_mitigated=False,
            out_of_scope=False,
            false_p=False,
            duplicate=False,
        )


def test_severity_enum_values():
    assert SeverityEnum.CRITICAL == "Critical"
    assert SeverityEnum.HIGH == "High"
    assert SeverityEnum.MEDIUM == "Medium"
    assert SeverityEnum.LOW == "Low"
    assert SeverityEnum.INFO == "Info"


def test_severity_enum_invalid():
    with pytest.raises(ValueError):
        SeverityEnum("Unknown")


def test_pagination_metadata_valid():
    meta = PaginationMetadata(count=50, offset=0, limit=20, has_next=True)
    assert meta.count == 50
    assert meta.offset == 0
    assert meta.limit == 20
    assert meta.has_next is True


def test_pagination_metadata_has_next_false():
    meta = PaginationMetadata(count=5, offset=0, limit=20, has_next=False)
    assert meta.has_next is False
