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
        max_length=10
    )
