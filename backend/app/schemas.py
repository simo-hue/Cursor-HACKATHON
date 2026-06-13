from typing import Literal

from pydantic import BaseModel, Field

Verticale = Literal["crm", "erp", "calls", "kb"]


class AskRequest(BaseModel):
    question: str = Field(min_length=1)


class AskResponse(BaseModel):
    answer: str
    sources: list[str]
    verticale: Verticale
    artifact_url: str | None = None
