from enum import Enum
from pydantic import BaseModel, Field


class SeverityEnum(str, Enum):
    CRITICAL = "Critical"
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"
    INFO = "Info"


class ProductSummary(BaseModel):
    id: int
    name: str
    description: str
    prod_type: int


class EngagementSummary(BaseModel):
    model_config = {"populate_by_name": True}
    id: int
    name: str | None = None
    product_id: int = Field(alias="product")
    status: str | None = None
    target_start: str
    target_end: str


class TestSummary(BaseModel):
    __test__ = False
    model_config = {"populate_by_name": True}
    id: int
    engagement_id: int = Field(alias="engagement")
    test_type: int
    title: str | None = None
    target_start: str | None = None
    target_end: str | None = None


class FindingSummary(BaseModel):
    model_config = {"populate_by_name": True}
    id: int
    test_id: int = Field(alias="test")
    title: str
    severity: SeverityEnum
    description: str
    active: bool
    verified: bool
    mitigated: str | None = None
    is_mitigated: bool
    out_of_scope: bool
    false_p: bool
    duplicate: bool
    risk_accepted: bool = False
    cwe: int | None = None
    cvssv3_score: float | None = None
    component_name: str | None = None
    component_version: str | None = None
    file_path: str | None = None
    line: int | None = None
    tags: list[str] | None = None
    vulnerability_ids: list | None = None


class NoteAuthor(BaseModel):
    """Author of a finding note as returned by DefectDojo."""
    id: int | None = None
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None


class FindingNote(BaseModel):
    id: int | None = None
    entry: str
    private: bool = False
    date: str | None = None
    author: NoteAuthor | str | None = None


class ImportScanResult(BaseModel):
    model_config = {"populate_by_name": True}
    test: int
    test_id: int | None = None
    findings_affected: int | None = None
    scan_type: str | None = None
    findings_count: int | None = None
    created: int | None = None
    closed: int | None = None
    reactivated: int | None = None
    untouched: int | None = None


class PaginationMetadata(BaseModel):
    count: int
    offset: int
    limit: int
    has_next: bool


class ProductTypeSummary(BaseModel):
    id: int
    name: str
    description: str | None = None
    critical_product: bool = False
    key_product: bool = False


class TestTypeSummary(BaseModel):
    __test__ = False
    id: int
    name: str
    tags: list[str] | None = None


class TagList(BaseModel):
    tags: list[str]
