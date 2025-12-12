from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from .session import ChatMessage


class ChatRequest(BaseModel):
    message: str = Field(..., description="User message to send to the LLM.")
    session_id: Optional[str] = Field(default=None, description="Existing session id to continue a chat.")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Optional metadata from the frontend.")


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    history: List[ChatMessage]


class KVICategoryItem(BaseModel):
    """Represents a single KVI category selection."""
    main_id: str = Field(..., description="ID of the main category (e.g., '01', '02')")
    sub_id: str = Field(..., description="ID of the subcategory (e.g., '011', '021')")


class KVICategoryResponse(BaseModel):
    """Response containing relevant KVI categories based on interview."""
    categories: List[KVICategoryItem] = Field(
        ..., 
        description="List of relevant KVI categories (max 10)",
        max_length=1
    )


class FinalKVICategoryResponse(BaseModel):
    """Response containing final refined KVI categories with no limit."""
    categories: List[KVICategoryItem] = Field(
        ..., 
        description="List of final refined KVI categories (unlimited)"
    )


class KPIItem(BaseModel):
    """Represents a single KPI that should be collected for calculating KVIs."""
    id: str = Field(..., description="Unique identifier for the KPI (e.g., 'kpi_001')")
    name: str = Field(..., description="Name of the KPI")
    description: str = Field(..., description="What is the KPI and how should it be collected")
    measure: str = Field(..., description="Unit of measurement (e.g., 'ms', '%', 'count', 'GB')")


class KPIResponse(BaseModel):
    """Response containing KPIs to be collected for the service."""
    kpis: List[KPIItem] = Field(
        ..., 
        description="List of KPIs to collect (max 10)",
        max_length=5
    )


class CollectedKPIValue(BaseModel):
    """Represents a collected KPI value from the user."""
    kpi_id: str = Field(..., description="ID of the KPI (matches KPIItem.id)")
    kpi_name: str = Field(..., description="Name of the KPI")
    value: Optional[str] = Field(None, description="The collected value (None if AI will decide)")
    measure: str = Field(..., description="Unit of measurement")
    ai_decided: bool = Field(default=False, description="True if user chose to let AI decide")


class CollectedKPIResponse(BaseModel):
    """Response containing all collected KPI values."""
    collected_kpis: List[CollectedKPIValue] = Field(
        ...,
        description="List of collected KPI values"
    )


class KVICalculation(BaseModel):
    """Represents a calculated KVI value."""
    kvi_code: str = Field(..., description="The KVI code (e.g., 'IWCA')")
    kvi_title: str = Field(..., description="The KVI title")
    exact: Optional[float] = Field(None, description="Exact value if all required KPIs provided")
    min: Optional[float] = Field(None, description="Minimum value in worst case scenario")
    max: Optional[float] = Field(None, description="Maximum value in best case scenario")
    description: str = Field(..., description="Brief description of the calculation formula")


class KVICalculationResponse(BaseModel):
    """Response containing calculated KVI values for one category."""
    calculations: List[KVICalculation] = Field(
        ...,
        description="List of calculated KVI values"
    )
