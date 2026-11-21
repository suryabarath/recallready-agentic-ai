"""Deterministic lot/brand/package/product/UPC comparison tool for A2.

Pure deterministic function with no LLM calls, no Qdrant queries, and no SQLite writes.
Preserves exact SQLite strings in findings while keeping normalized forms in diagnostics only.
"""

import re
from typing import Literal

from inventory_store import (
    InventoryRow,
    _normalize_upc_digits,
    _parse_package_value_unit,
    deterministic_product_name_matches,
)
from models import Nonblank, StrictModel
from pydantic import Field


AttributeMatchStatus = Literal["matched", "mismatched", "unknown"]
MatchLevel = Literal["exact", "partial", "no_match"]

_PACKAGE_PATTERN = re.compile(
    r"(?<!\w)(\d+(?:\.\d+)?)\s*(oz|ounces?|lb|lbs|pounds?|g|grams?|kg|kilograms?|gallons?|gal)\b",
    re.IGNORECASE,
)
_EXPLICIT_BRAND_PATTERN = re.compile(
    r"\b([A-Za-z0-9][A-Za-z0-9 '&.\-]{0,40}?)\s+brand\b",
    re.IGNORECASE,
)


class RecallInventoryScope(StrictModel):
    recall_number: Nonblank
    snapshot_id: Nonblank
    event_id: Nonblank
    product_name: str | None = None
    brand: str | None = None
    lot_numbers: tuple[str, ...] = ()
    package_sizes: tuple[str, ...] = ()
    upcs: tuple[str, ...] = ()
    skus: tuple[str, ...] = ()
    uncertainties: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    has_ambiguous_package_lot_relation: bool = False
    # (lot/code value, provenance text) pairs, e.g. which Group C relation or
    # batch identifier a lot value came from. Diagnostics only.
    source_notes: tuple[tuple[str, str], ...] = ()


class MatchDiagnostics(StrictModel):
    normalized_recall_upcs: tuple[str, ...] = ()
    normalized_inventory_upc: str | None = None
    normalized_recall_packages: tuple[str, ...] = ()
    normalized_inventory_package: str | None = None
    matched_lot_value: str | None = None
    reason_codes: tuple[Nonblank, ...] = Field(min_length=1)


class InventoryMatch(StrictModel):
    item_id: Nonblank
    lot: AttributeMatchStatus
    brand: AttributeMatchStatus
    product_name: AttributeMatchStatus
    package_size: AttributeMatchStatus
    upc: AttributeMatchStatus
    match_status: MatchLevel
    diagnostics: MatchDiagnostics


def extract_package_sizes_from_text(text: str | None) -> tuple[str, ...]:
    """Extract literal package-size substrings from FDA product description."""
    if not text:
        return ()
    found: list[str] = []
    for match in _PACKAGE_PATTERN.finditer(text):
        literal = match.group(0).strip()
        if literal not in found:
            found.append(literal)
    return tuple(found)


def extract_explicit_brand_from_text(text: str | None) -> str | None:
    """Extract brand only when explicitly labeled '<Name> brand' in FDA product text.

    Never infers brand from recalling_firm or unlabeled descriptions.
    """
    if not text:
        return None
    match = _EXPLICIT_BRAND_PATTERN.search(text)
    if not match:
        return None
    candidate = match.group(1).strip(" ,;:\"'-")
    # Strip leading articles or generic prefixes if any
    if not candidate or candidate.lower() in {"following", "the", "a", "an", "private"}:
        return None
    return candidate


def _compare_lot(recall_lots: tuple[str, ...], inv_lot: str) -> tuple[AttributeMatchStatus, str | None]:
    clean_recall_lots = tuple(lot for lot in recall_lots if isinstance(lot, str) and lot != "")
    if not clean_recall_lots or inv_lot == "":
        return ("unknown", None)
    # Exact string comparison preserving leading zeros and case
    for lot in clean_recall_lots:
        if inv_lot == lot:
            return ("matched", lot)
    return ("mismatched", None)


def _compare_brand(recall_brand: str | None, inv_brand: str) -> AttributeMatchStatus:
    if not recall_brand or not recall_brand.strip() or not inv_brand or not inv_brand.strip():
        return "unknown"
    if " ".join(recall_brand.strip().lower().split()) == " ".join(inv_brand.strip().lower().split()):
        return "matched"
    return "mismatched"


def _compare_product_name(recall_product: str | None, inv_label: str) -> AttributeMatchStatus:
    if not recall_product or not recall_product.strip() or not inv_label or not inv_label.strip():
        return "unknown"
    if deterministic_product_name_matches(recall_product, inv_label):
        return "matched"
    return "mismatched"


def _compare_package_size(
    recall_pkgs: tuple[str, ...], inv_pkg: str
) -> tuple[AttributeMatchStatus, tuple[str, ...], str | None]:
    parsed_recall: list[tuple[float, str]] = []
    norm_recall_strs: list[str] = []
    for pkg in recall_pkgs:
        parsed = _parse_package_value_unit(pkg)
        if parsed is not None:
            parsed_recall.append(parsed)
            norm_str = f"{parsed[0]:g} {parsed[1]}"
            if norm_str not in norm_recall_strs:
                norm_recall_strs.append(norm_str)

    parsed_inv = _parse_package_value_unit(inv_pkg)
    norm_inv_str = f"{parsed_inv[0]:g} {parsed_inv[1]}" if parsed_inv is not None else None

    if not parsed_recall or parsed_inv is None:
        if recall_pkgs and inv_pkg.strip():
            # Both provide non-empty text, check exact lower match if unit parser didn't match
            if inv_pkg.strip().lower() in {p.strip().lower() for p in recall_pkgs if p.strip()}:
                return ("matched", tuple(norm_recall_strs), norm_inv_str)
            return ("mismatched", tuple(norm_recall_strs), norm_inv_str)
        return ("unknown", tuple(norm_recall_strs), norm_inv_str)

    if parsed_inv in parsed_recall:
        return ("matched", tuple(norm_recall_strs), norm_inv_str)
    return ("mismatched", tuple(norm_recall_strs), norm_inv_str)


def _compare_upc(
    recall_upcs: tuple[str, ...], inv_upc: str
) -> tuple[AttributeMatchStatus, tuple[str, ...], str | None]:
    norm_recall: list[str] = []
    for u in recall_upcs:
        digits = _normalize_upc_digits(u)
        if digits is not None and digits not in norm_recall:
            norm_recall.append(digits)
    norm_inv = _normalize_upc_digits(inv_upc)
    if not norm_recall or norm_inv is None:
        if recall_upcs and inv_upc.strip():
            return ("mismatched", tuple(norm_recall), norm_inv)
        return ("unknown", tuple(norm_recall), norm_inv)
    if norm_inv in norm_recall:
        return ("matched", tuple(norm_recall), norm_inv)
    return ("mismatched", tuple(norm_recall), norm_inv)


def compare_recall_to_inventory(
    recall_attributes: RecallInventoryScope,
    inventory_row: InventoryRow,
) -> InventoryMatch:
    """Compare source-supported A1 recall attributes to one authoritative inventory row."""
    lot_status, matched_lot = _compare_lot(recall_attributes.lot_numbers, inventory_row.lot_code)
    brand_status = _compare_brand(recall_attributes.brand, inventory_row.brand)
    product_status = _compare_product_name(recall_attributes.product_name, inventory_row.product_label)
    pkg_status, norm_rec_pkgs, norm_inv_pkg = _compare_package_size(
        recall_attributes.package_sizes, inventory_row.package_size
    )
    upc_status, norm_rec_upcs, norm_inv_upc = _compare_upc(
        recall_attributes.upcs, inventory_row.upc
    )

    reasons: list[str] = [
        f"lot_{lot_status}",
        f"product_{product_status}",
        f"package_{pkg_status}",
        f"upc_{upc_status}",
        f"brand_{brand_status}",
    ]

    if recall_attributes.has_ambiguous_package_lot_relation:
        reasons.append("ambiguous_package_lot_relation")
    if recall_attributes.uncertainties:
        reasons.append("a1_uncertainty_present")

    # Determine overall match level per Section 2.2 and Section 4.3:
    # - Any explicit mismatch on a primary or concrete compared attribute (product, lot, package, upc, brand)
    #   or completely unrelated product -> no_match (unless lot matched and a secondary attribute is unknown).
    # - Wait: if product_status == "mismatched" -> no_match (filters out *-B distractors and unrelated items).
    # - If lot_status == "mismatched" -> no_match.
    # - If package_size == "mismatched" or upc == "mismatched" or brand == "mismatched" -> no_match.
    has_mismatch = any(
        status == "mismatched"
        for status in (lot_status, product_status, pkg_status, upc_status, brand_status)
    )

    if has_mismatch or product_status != "matched":
        match_level: MatchLevel = "no_match"
    elif lot_status == "matched":
        # Lot and product matched, and no concrete attribute mismatched.
        # Check whether any required scope attribute is missing/ambiguous:
        # 1. If recall has package_sizes or inventory requires package_size and pkg_status == "unknown"
        # 2. If recall has upcs and upc_status == "unknown"
        # 3. If recall has brand and brand_status == "unknown"
        # 4. If A1 has uncertainties or ambiguous Group C relation
        secondary_unknown = (
            (bool(recall_attributes.package_sizes) and pkg_status == "unknown")
            or (bool(recall_attributes.upcs) and upc_status == "unknown")
            or (bool(recall_attributes.brand) and brand_status == "unknown")
            or bool(recall_attributes.uncertainties)
            or recall_attributes.has_ambiguous_package_lot_relation
        )
        if secondary_unknown:
            match_level = "partial"
            # A blank inventory attribute is "unknown", never a match: the row
            # cannot become exact until the attribute is known (requirements 2.2).
            if recall_attributes.package_sizes and pkg_status == "unknown":
                reasons.append("secondary_unknown:package_size")
            if recall_attributes.upcs and upc_status == "unknown":
                reasons.append("secondary_unknown:upc")
            if recall_attributes.brand and brand_status == "unknown":
                reasons.append("secondary_unknown:brand")
            reasons.append("lot_matched_with_unknown_or_uncertain_secondary_attribute")
        else:
            match_level = "exact"
            reasons.append("exact_scope_match")
    else:
        # lot_status is "unknown" while product matched and no concrete attribute mismatched.
        # Per Section 2.2:
        # - If the recall specifies lot_numbers, a row with empty lot_code ("unknown" lot)
        #   must NOT be claimed as a match unless it matched an explicit product identifier
        #   (such as UPC) or when the recall itself has no lot numbers (e.g. Group C review).
        #   This ensures *-B distractors (which have blank lot_code and blank UPC) are excluded!
        if recall_attributes.lot_numbers:
            if upc_status == "matched":
                match_level = "partial"
                reasons.append("lot_missing_in_inventory_with_matched_upc")
            else:
                match_level = "no_match"
                reasons.append("lot_missing_in_inventory_for_lot_scoped_recall")
        else:
            any_matched = any(
                status == "matched"
                for status in (product_status, pkg_status, upc_status, brand_status)
            )
            if any_matched:
                match_level = "partial"
                reasons.append("lot_unknown_partial_candidate")
            else:
                match_level = "no_match"

    diagnostics = MatchDiagnostics(
        normalized_recall_upcs=norm_rec_upcs,
        normalized_inventory_upc=norm_inv_upc,
        normalized_recall_packages=norm_rec_pkgs,
        normalized_inventory_package=norm_inv_pkg,
        matched_lot_value=matched_lot,
        reason_codes=tuple(reasons),
    )

    return InventoryMatch(
        item_id=inventory_row.item_id,
        lot=lot_status,
        brand=brand_status,
        product_name=product_status,
        package_size=pkg_status,
        upc=upc_status,
        match_status=match_level,
        diagnostics=diagnostics,
    )
