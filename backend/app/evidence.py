from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Verticale = Literal["crm", "erp", "calls", "kb"]


@dataclass
class EvidencePack:
    answerable: bool
    verticale: Verticale
    facts: dict[str, Any] = field(default_factory=dict)
    sources: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    confidence: float = 0.0
    artifact_url: str | None = None

    def add_source(self, source: str) -> None:
        source = source.strip("/")
        if source and source not in self.sources:
            self.sources.append(source)

    @property
    def answer(self) -> str:
        return str(self.facts.get("answer", "")).strip()
