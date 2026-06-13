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


_ARTIFACT_ACTION_WORDS = {
    "generate", "create", "build", "compose", "draft", "prepare", "produce",
    "deck", "slide", "slides", "presentation", "powerpoint", "brochure",
    "one-pager", "onepager",
}
_ARTIFACT_DECK_WORDS = {"deck", "slide", "slides", "presentation", "powerpoint"}


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
    # Whole-word match so verbs inside other words ("reported" -> "report",
    # "remake" -> "make") do not falsely trigger artifact generation.
    words = set(q.split())
    if words & _ARTIFACT_ACTION_WORDS:
        return True, "html" if (words & _ARTIFACT_DECK_WORDS) else None
    # "a report"/"the report" as a deliverable noun (without a verb above).
    if re.search(r"\b(?:a|an|the|this|that|one)\s+report\b", q):
        return True, None
    return False, None


# A captured company name ends at a stop token: punctuation that cannot be part
# of a name (':' '/' '(' ')' ',' '?') or a following clause keyword. The ':' and
# '/' matter for prompts like "...S.p.A.: profile" or "order/lot status", where
# the colon previously blocked extraction entirely.
_NAME = r"([A-Z][\w&'. -]{2,80}?)"
# Case-sensitive variant: the first letter must be uppercase even when the
# overall search runs case-insensitively. Used by the loosely-anchored
# possessive / subject-verb patterns so they don't latch onto lowercase filler
# words ("what's", "did we ...").
_NAME_CS = r"((?-i:[A-Z])[\w&'. -]{2,80}?)"
_NAME_STOP = (
    r"(?=\s*(?:[:/(),?]|call\b|have\b|has\b|had\b|asked\b|order\b"
    r"|exists?\b|in (?:the )?crm\b|$))"
)
# Common non-company words a loose pattern might capture; rejected so we never
# search the CRM for "What" or "Most recently".
_NON_COMPANY_WORDS = {
    "what", "who", "whom", "when", "where", "why", "how", "which", "that",
    "this", "these", "those", "it", "they", "them", "we", "us", "you", "i",
    "the", "a", "an", "there", "here", "today", "tomorrow", "yesterday", "now",
    "please", "thanks", "most recently", "recently", "last", "latest", "their",
    "our", "his", "her", "its", "any", "some", "all", "each", "everyone",
}
# Leading role/filler words that are never part of the company name itself, so a
# generic "for <X>" capture like "the sales rep visiting Acme" can be trimmed.
_LEADING_FILLER_RE = re.compile(
    r"^(?:that last|the last|the|a|an|our|new|customer|account|client|"
    r"sales\s+rep(?:resentative)?|rep|account\s+manager|sales\s+team|team|"
    r"company|firm|visiting|meeting(?:\s+with)?|seeing|visit\s+to|with)\s+",
    re.I,
)
# Dotted legal suffix (S.p.A. / S.r.l. / S.n.c. / S.a.s.). The leading "s." with a
# literal dot avoids matching the plain English word "spa", so a real company name
# ends at this suffix and any trailing noise ("... S.r.l. tomorrow") is dropped.
_DOTTED_SUFFIX_RE = re.compile(
    r"\bs\.\s*p\.?\s*a\.?|\bs\.\s*r\.?\s*l\.?|\bs\.\s*n\.?\s*c\.?|\bs\.\s*a\.?\s*s\.?",
    re.I,
)

# Patterns are tried in priority order; the dedicated "visiting/meeting/seeing"
# verb pattern is placed before the generic prepositions so that "for the sales
# rep visiting <X>" resolves to <X> rather than "the sales rep visiting <X>".
_CUSTOMER_PHRASE_PATTERNS = [
    rf"customer\s+(?:named|called)\s+{_NAME}"
    r"(?=\s*(?:[:/(),?]|exists?\b|in (?:the )?crm\b|$))",
    rf"\b(?:visiting|meeting|seeing|calling\s+on|visit\s+to)\s+(?:with\s+)?{_NAME}{_NAME_STOP}",
    # Possessive: "Primato Supermercati's deals", "NordSpesa's order".
    rf"\b{_NAME_CS}(?=['\u2019]s\b)",
    # Subject + action verb: "did NordSpesa complain", "has GranMercato ordered".
    rf"\b(?:did|does|do|has|have|is|was|will|when|why)\s+{_NAME_CS}\s+"
    r"(?:complain|complaint|report|reported|ask|asked|want|wanted|order|ordered"
    r"|say|said|mention|mentioned|call|called|raise|raised|need|needs|place|placed"
    r"|buy|bought|request|requested|sign|signed|have|has|receive|received)",
    rf"(?:customer|account|client|with|for|from|about|of|regarding|concerning)\s+{_NAME}{_NAME_STOP}",
    r"does\s+([A-Z][\w&'. -]{2,80}?)\s+have",
    r"^([A-Z][\w&'. -]{2,80}?)\s*(?:\([^)]*\))?\s+asked",
]


def extract_customer_phrase(question: str) -> str | None:
    without_ids = re.sub(ID_PATTERNS["customer_ids"], "", question, flags=re.I)
    without_ids = re.sub(r"\(\s*\)", " ", without_ids)  # drop "()" left by id removal
    for pattern in _CUSTOMER_PHRASE_PATTERNS:
        # finditer (not search) so a rejected leading match — e.g. "What's" for
        # the possessive pattern — does not stop us from finding the real name
        # later in the sentence ("...Primato Supermercati's deals").
        for match in re.finditer(pattern, without_ids, flags=re.I):
            candidate = match.group(1).strip(" ,.'\u2019")
            # Strip leading filler repeatedly: "the sales rep visiting" -> "".
            previous = None
            while previous != candidate:
                previous = candidate
                candidate = _LEADING_FILLER_RE.sub("", candidate, count=1).strip(" ,.'\u2019")
            # A dotted legal suffix marks the end of the name; drop trailing noise.
            suffix = list(_DOTTED_SUFFIX_RE.finditer(candidate))
            if suffix:
                candidate = candidate[: suffix[0].end()].strip(" ,.'\u2019")
            norm = normalize_text(candidate)
            if len(norm) < 3 or norm in _NON_COMPANY_WORDS:
                continue
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
