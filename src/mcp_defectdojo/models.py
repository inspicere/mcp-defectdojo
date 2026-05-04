from typing import Optional
from pydantic import BaseModel, Field

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
