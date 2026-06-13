from __future__ import annotations

import math
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rank_bm25 import BM25Okapi

from .config import BACKEND_DIR
from .normalizers import normalize_text


@dataclass(frozen=True)
class KBDoc:
    doc_id: str
    path: str
    title: str
    text: str
    tokens: list[str]
    sku: str | None = None


@dataclass(frozen=True)
class KBDocHit:
    doc: KBDoc
    score: float


class KnowledgeBase:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or BACKEND_DIR / "data" / "kb"
        self._docs: list[KBDoc] = []
        self._bm25: BM25Okapi | None = None
        self._lock = threading.Lock()

    @staticmethod
    def _tokens(text: str) -> list[str]:
        return [token for token in normalize_text(text).split() if len(token) > 1]

    def _ensure_loaded(self) -> None:
        if self._docs:
            return
        with self._lock:
            if self._docs:
                return
            docs: list[KBDoc] = []
            for path in sorted(self.root.glob("*.md")):
                text = path.read_text(encoding="utf-8")
                doc_match = re.search(r"\bDOC-\d{3}\b", text)
                sku_match = re.search(r"\bPAS-[A-Z0-9-]{3,}\b", text)
                title = next(
                    (line.lstrip("# ").strip() for line in text.splitlines() if line.startswith("#")),
                    path.stem,
                )
                docs.append(
                    KBDoc(
                        doc_id=doc_match.group(0) if doc_match else path.stem,
                        path=str(path),
                        title=title,
                        text=text,
                        tokens=self._tokens(f"{title}\n{text}"),
                        sku=sku_match.group(0) if sku_match else None,
                    )
                )
            self._docs = docs
            self._bm25 = BM25Okapi([doc.tokens for doc in docs]) if docs else None

    @property
    def documents(self) -> list[KBDoc]:
        self._ensure_loaded()
        return list(self._docs)

    def search_by_id(self, doc_id: str) -> KBDoc | None:
        self._ensure_loaded()
        wanted = doc_id.upper()
        return next((doc for doc in self._docs if doc.doc_id == wanted), None)

    def search(self, query: str, top_k: int = 5) -> list[KBDocHit]:
        self._ensure_loaded()
        if not self._docs or not self._bm25:
            return []
        tokens = self._tokens(query)
        bm25_scores = self._bm25.get_scores(tokens or ["_"])
        normalized_query = normalize_text(query)
        upper_query = query.upper()
        hits: list[KBDocHit] = []
        max_bm25 = max(bm25_scores) if len(bm25_scores) else 1.0
        for index, doc in enumerate(self._docs):
            score = float(bm25_scores[index]) / max(max_bm25, 1.0)
            normalized_doc = normalize_text(f"{doc.title} {doc.text}")
            if doc.doc_id in upper_query:
                score += 4.0
            if doc.sku and doc.sku in upper_query:
                score += 3.0
            if normalized_query and normalized_query in normalized_doc:
                score += 2.0
            overlap = len(set(tokens) & set(doc.tokens))
            score += min(overlap / max(len(set(tokens)), 1), 1.0)
            hits.append(KBDocHit(doc=doc, score=score))
        return sorted(hits, key=lambda hit: hit.score, reverse=True)[:top_k]

    def search_product(self, sku_or_name: str) -> list[KBDocHit]:
        hits = self.search(sku_or_name, top_k=8)
        product_hits = [
            hit
            for hit in hits
            if "product specification" in hit.doc.title.lower()
            or "spec sheet" in hit.doc.title.lower()
        ]
        return product_hits or hits

    def search_policy(self, topic: str) -> list[KBDocHit]:
        return self.search(f"{topic} policy procedure", top_k=5)


def _clean_markdown_value(value: str) -> str:
    value = re.sub(r"[*_`>#]", "", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip(" .:|-")


def extract_product_spec(text: str) -> dict[str, Any]:
    sku_match = re.search(r"\bPAS-[A-Z0-9-]{3,}\b", text)
    title_match = re.search(r"^#\s+(.+)$", text, flags=re.M)
    product_match = re.search(
        r"\|\s*(?:Commercial name|Product name)\s*\|\s*([^|]+)\|", text, re.I
    )
    shelf_match = re.search(
        r"\|\s*Shelf life(?:\s*\([^|]*\))?\s*\|\s*([^|]+)\|", text, re.I
    )
    if not shelf_match:
        shelf_match = re.search(r"\*\*Shelf life:\*\*\s*([^\n]+)", text, re.I)

    allergen_section_match = re.search(
        r"##\s*\d*\.?\s*Allergen.*?(?=\n##\s*\d|\Z)", text, re.I | re.S
    )
    allergen_section = allergen_section_match.group(0) if allergen_section_match else text
    parts = re.split(r"may contain", allergen_section, maxsplit=1, flags=re.I)
    present_part = parts[0]
    may_part = parts[1] if len(parts) > 1 else ""
    allergens = [
        allergen
        for allergen in ("gluten", "soy", "mustard", "egg")
        if re.search(rf"\b{allergen}\b", present_part, re.I)
    ]
    no_traces = bool(
        re.search(
            r"(?:none declared|no [\"']?may contain|no declared cross-contamination)",
            may_part,
            re.I,
        )
    )
    may_contain = (
        []
        if no_traces
        else [
            allergen
            for allergen in ("soy", "mustard")
            if re.search(rf"\b{allergen}\b", may_part, re.I)
        ]
    )
    shelf_life = (
        _clean_markdown_value(shelf_match.group(1)) if shelf_match else None
    )
    concise_shelf = re.search(r"\b\d+\s+months?\b", shelf_life or "", re.I)
    return {
        "sku": sku_match.group(0) if sku_match else None,
        "product": _clean_markdown_value(product_match.group(1))
        if product_match
        else _clean_markdown_value(title_match.group(1))
        if title_match
        else None,
        "shelf_life": concise_shelf.group(0) if concise_shelf else shelf_life,
        "allergens": list(dict.fromkeys(allergens)),
        "may_contain": list(dict.fromkeys(may_contain)),
    }


def extract_price_for_sku(text: str, sku: str) -> dict[str, Any]:
    sku = sku.upper()
    row = re.search(
        rf"^\|\s*{re.escape(sku)}\s*\|([^|]*)\|([^|]*)\|\s*([0-9]+(?:\.[0-9]+)?)\s*\|",
        text,
        re.I | re.M,
    )
    detail = re.search(
        rf"###\s*{re.escape(sku)}[^\n]*\n-\s*\*\*List price:\*\*\s*EUR\s*([0-9]+(?:\.[0-9]+)?)\s*per carton",
        text,
        re.I,
    )
    price = float(detail.group(1)) if detail else float(row.group(3)) if row else None
    return {
        "sku": sku,
        "product": _clean_markdown_value(row.group(1)) if row else None,
        "price": price,
        "currency": "EUR",
        "unit": "carton",
    }


def extract_return_policy_terms(text: str) -> dict[str, Any]:
    window_match = re.search(r"within\s+\*\*(\d+)\s+days\*\*", text, re.I)
    covered_section = re.search(
        r"##\s*4\.\s*Covered Defects(.*?)(?=\n##\s*5|\Z)", text, re.I | re.S
    )
    excluded_section = re.search(
        r"##\s*5\.\s*Exclusions(.*?)(?=\n##\s*6|\Z)", text, re.I | re.S
    )

    def bullets(section: re.Match[str] | None) -> list[str]:
        if not section:
            return []
        return [
            _clean_markdown_value(item)
            for item in re.findall(r"^\s*-\s+\*\*([^*]+)\*\*", section.group(1), re.M)
        ]

    return {
        "window_days": int(window_match.group(1)) if window_match else 15,
        "required_evidence": ["lot number", "photo of the non-conformity"],
        "covered_defects": bullets(covered_section),
        "exclusions": bullets(excluded_section),
        "outcomes": ["replacement", "credit note on the lot value"],
        "block_confirmed_lot": True,
    }


def relevant_excerpt(text: str, query: str, max_sentences: int = 4) -> str:
    query_tokens = set(normalize_text(query).split())
    candidates = re.split(r"(?<=[.!?])\s+|\n{2,}", text)
    scored: list[tuple[float, str]] = []
    for candidate in candidates:
        clean = _clean_markdown_value(candidate)
        if len(clean) < 25 or clean.startswith("Document ID"):
            continue
        tokens = set(normalize_text(clean).split())
        overlap = len(query_tokens & tokens)
        score = overlap / math.sqrt(max(len(tokens), 1))
        if overlap:
            scored.append((score, clean))
    return " ".join(item for _, item in sorted(scored, reverse=True)[:max_sentences])
