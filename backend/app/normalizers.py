from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

ID_PATTERNS = {
    "customer_ids": r"\bCUST-\d{4}\b",
    "opportunity_ids": r"\bOPP-\d{4}\b",
    "order_ids": r"\bORD-\d{4}-\d{4}\b",
    "lot_ids": r"\bLOT-\d{4}-\d{4}\b",
    "skus": r"\bPAS-[A-Z0-9-]{3,}\b",
    "raw_skus": r"\bRAW-[A-Z0-9-]{3,}\b",
    "supplier_ids": r"\bSUP-\d{3}\b",
    "call_ids": r"\bCALL-\d{5}\b",
    "doc_ids": r"\bDOC-\d{3}\b",
}

COMPANY_SUFFIX_RE = re.compile(
    r"\b(?:s\s*p\s*a|spa|s\s*r\s*l|srl|societa per azioni)\b", re.I
)

ISO_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
# Product-name ordinals such as "n.24" / "no. 51" / "#205" are part of the human
# label, not must-contain facts (the SKU is the real identifier), so they are not
# treated as hard tokens. This keeps the LLM free to drop verbose product titles.
ORDINAL_RE = re.compile(r"(?:\bNO?\.\s?\d+|#\s?\d+)")


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = re.sub(r"[^a-zA-Z0-9]+", " ", value.lower())
    return re.sub(r"\s+", " ", value).strip()


def normalize_company_name(value: str) -> str:
    value = COMPANY_SUFFIX_RE.sub(" ", normalize_text(value))
    return re.sub(r"\s+", "", value)


def extract_ids(question: str) -> dict[str, list[str]]:
    upper = question.upper()
    return {
        key: list(dict.fromkeys(re.findall(pattern, upper)))
        for key, pattern in ID_PATTERNS.items()
    }


def _canonical_number(token: str) -> str | None:
    cleaned = token.replace(",", "")
    if not cleaned or not cleaned[0].isdigit():
        return None
    if "." in cleaned:
        cleaned = cleaned.rstrip("0").rstrip(".")
    return cleaned or "0"


def extract_hard_tokens(text: str) -> set[str]:
    """Extract the facts an answer must keep: IDs, ISO dates and numbers.

    Numbers are canonicalized by value (thousands separators stripped, trailing
    zeros trimmed) so that "740,000" and "740000" are treated as the same fact.
    IDs are matched case-insensitively. This lets us verify an LLM-composed
    answer preserved every hard fact regardless of harmless reformatting.
    """
    tokens: set[str] = set()
    if not text:
        return tokens
    working = text.upper()
    for pattern in ID_PATTERNS.values():
        for match in re.findall(pattern, working):
            tokens.add(f"ID:{match.upper()}")
            working = working.replace(match, " ")
    for match in ISO_DATE_RE.findall(working):
        tokens.add(f"DATE:{match}")
        working = working.replace(match, " ")
    working = ORDINAL_RE.sub(" ", working)
    for match in NUMBER_RE.findall(working):
        canonical = _canonical_number(match)
        if canonical is not None:
            tokens.add(f"NUM:{canonical}")
    return tokens


def answer_preserves_tokens(candidate: str, required: set[str]) -> bool:
    """True when every required hard token is present in the candidate text."""
    if not required:
        return True
    return required <= extract_hard_tokens(candidate)


def answer_within_tokens(candidate: str, allowed: set[str]) -> bool:
    """True when the candidate introduces no hard token outside ``allowed``.

    Guards against fabricated facts and prompt injection: a composed answer may
    only contain IDs/dates/numbers that already exist in the grounded evidence.
    """
    return extract_hard_tokens(candidate) <= allowed


def polarity_signature(text: str) -> frozenset[str]:
    """Capture yes/no and below/late conclusions that hard tokens cannot.

    Token validation is value-blind, so an answer could keep every number yet
    invert the verdict ("below" -> "not below", "Yes" -> "No"). This signature
    lets the caller reject such semantic inversions.
    """
    t = normalize_text(text)
    sig: set[str] = set()
    if not t:
        return frozenset(sig)
    if re.search(r"\bnot below\b", t):
        sig.add("not_below")
    elif "below" in t:
        sig.add("below")
    if re.search(r"\bnot late\b", t):
        sig.add("not_late")
    elif re.search(r"\blate\b", t):
        sig.add("late")
    first = t.split(" ", 1)[0]
    if first == "yes":
        sig.add("yes")
    elif first == "no":
        sig.add("no")
    return frozenset(sig)


def answer_keeps_polarity(candidate: str, deterministic: str) -> bool:
    """True when the candidate preserves every polarity conclusion of the source."""
    return polarity_signature(deterministic) <= polarity_signature(candidate)


def is_aggregate_question(question: str) -> bool:
    q = normalize_text(question)
    return any(
        term in q
        for term in ("how many", "total value", "grouped by", "across all", "count")
    )


def is_artifact_request(question: str) -> tuple[bool, str | None]:
    q = normalize_text(question)
    explicit = {
        "xlsx": ("xlsx", "excel", "spreadsheet"),
        "docx": ("docx", "word document"),
        "pptx": ("pptx", "powerpoint"),
        "pdf": ("pdf",),
        "html": ("html",),
        "markdown": ("markdown",),
    }
    for artifact_type, terms in explicit.items():
        if any(term in q for term in terms):
            return True, artifact_type
    if any(term in q for term in ("generate", "create", "make", "deck", "report")):
        return True, "html" if any(term in q for term in ("deck", "slide")) else None
    return False, None


def extract_customer_phrase(question: str) -> str | None:
    without_ids = re.sub(ID_PATTERNS["customer_ids"], "", question, flags=re.I)
    patterns = [
        r"customer\s+(?:named|called)\s+([A-Z][\w&'. -]{2,80}?)(?=\s*(?:\?|,|$)|\s+(?:exist|exists|in (?:the )?crm)\b)",
        r"(?:customer|visiting|with|for|from)\s+([A-Z][\w&'. -]{2,80}?)(?=\s*(?:\(|,|\?|call\b|have\b|has\b|asked\b|order\b|$))",
        r"does\s+([A-Z][\w&'. -]{2,80}?)\s+have",
        r"^([A-Z][\w&'. -]{2,80}?)\s*(?:\([^)]*\))?\s+asked",
    ]
    for pattern in patterns:
        match = re.search(pattern, without_ids, flags=re.I)
        if match:
            candidate = match.group(1).strip(" ,.'")
            candidate = re.sub(
                r"^(?:that last|the last|the customer|customer)\s+",
                "",
                candidate,
                flags=re.I,
            )
            if len(normalize_text(candidate)) >= 3:
                return candidate
    return None


def first_value(record: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        value = record.get(key)
        if value is not None and value != "":
            return value
    return default


def record_id(record: dict[str, Any], *preferred: str) -> str:
    value = first_value(
        record,
        *preferred,
        "id",
        "customer_id",
        "opportunity_id",
        "order_id",
        "lot_id",
        "sku",
        "call_id",
        "supplier_id",
        default="",
    )
    return str(value)


def as_decimal(value: Any) -> Decimal:
    if value is None or value == "":
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    cleaned = re.sub(r"[^\d,.\-]", "", str(value))
    if cleaned.count(",") == 1 and "." not in cleaned:
        cleaned = cleaned.replace(",", ".")
    elif "," in cleaned and "." in cleaned:
        cleaned = cleaned.replace(",", "")
    try:
        return Decimal(cleaned or "0")
    except InvalidOperation:
        return Decimal("0")


def format_number(value: Any, maximum_decimals: int = 2) -> str:
    number = as_decimal(value)
    if number == number.to_integral():
        return f"{int(number):,}"
    rendered = f"{number:,.{maximum_decimals}f}"
    return rendered.rstrip("0").rstrip(".")


def format_money(value: Any, currency: str = "EUR") -> str:
    return f"{format_number(value)} {currency}"


def sort_records_newest(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    def key(record: dict[str, Any]) -> tuple[int, str]:
        raw = str(
            first_value(
                record,
                "datetime",
                "date",
                "call_date",
                "created_at",
                "updated_at",
                "started_at",
                default="",
            )
        )
        try:
            return (1, datetime.fromisoformat(raw.replace("Z", "+00:00")).isoformat())
        except ValueError:
            return (0, raw)

    return sorted(records, key=key, reverse=True)


def compact_record(record: dict[str, Any], keys: Iterable[str]) -> dict[str, Any]:
    return {key: record[key] for key in keys if key in record and record[key] is not None}
