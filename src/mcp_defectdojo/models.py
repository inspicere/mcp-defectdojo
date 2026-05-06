from enum import Enum
from typing import Optional
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
    name: Optional[str] = None
    product_id: int = Field(alias="product")
    target_start: str
    target_end: str

class TestSummary(BaseModel):
    model_config = {"populate_by_name": True}
    id: int
    engagement_id: int = Field(alias="engagement")
    test_type: int
    title: Optional[str] = None

class FindingSummary(BaseModel):
    model_config = {"populate_by_name": True}
    id: int
    test_id: int = Field(alias="test")
    title: str
    severity: str
    description: str
    active: bool
    verified: bool
    mitigated: Optional[str] = None
    is_mitigated: bool
    out_of_scope: bool
    false_p: bool
    duplicate: bool

class PaginationMetadata(BaseModel):
    count: int
    offset: int
    limit: int
    has_next: bool
