"""Acceptance tests for inventory_match.py (Items 2-7, 17, 24-28)."""

import unittest

from inventory_match import (
    RecallInventoryScope,
    compare_recall_to_inventory,
)
from inventory_store import InventoryRow


def _make_row(**overrides) -> InventoryRow:
    base = {
        "inventory_set_id": "SIMSET-001",
        "item_id": "INV-001-A",
        "retailer_id": "SIM-RETAILER-01",
        "store_id": "SIM-STORE-02",
        "product_label": "Donutful Chocolate Dipped Vanilla Cake Donuts",
        "brand": "",
        "upc": "850041392103",
        "lot_code": "26078",
        "package_size": "7.05oz",
        "simulated_quantity": 12,
        "quantity_unit": "packages",
        "inventory_reference_date": "2026-08-17",
        "source_type": "SYNTHETIC",
        "synthetic_generation_note": "Fictional stock record",
    }
    base.update(overrides)
    return InventoryRow.model_validate(base)


def _make_scope(**overrides) -> RecallInventoryScope:
    base = {
        "recall_number": "H-0011-2027",
        "snapshot_id": "FDA-FOOD-2026-10-23-USER-SNAPSHOT",
        "event_id": "99686",
        "product_name": "Donutful Chocolate Dipped Vanilla Cake Donuts - 7.05oz/10ct. UPC 850041392103.",
        "brand": None,
        "lot_numbers": ("26078",),
        "package_sizes": ("7.05oz",),
        "upcs": ("850041392103",),
        "skus": (),
        "uncertainties": (),
        "evidence_ids": ("EV-H-0011-2027-PRODUCT_DESCRIPTION", "EV-H-0011-2027-CODE_INFO"),
        "has_ambiguous_package_lot_relation": False,
    }
    base.update(overrides)
    return RecallInventoryScope.model_validate(base)


class TestInventoryMatch(unittest.TestCase):
    def test_exact_match_and_package_equivalence(self) -> None:
        """Items 1, 17, 26, 27: Pure deterministic match with package equivalence 7.05oz vs 7.05 oz and blank brand unknown."""
        scope = _make_scope(package_sizes=("7.05 oz",))
        row = _make_row(package_size="7.05oz", brand="")
        match = compare_recall_to_inventory(scope, row)
        self.assertEqual(match.match_status, "exact")
        self.assertEqual(match.lot, "matched")
        self.assertEqual(match.product_name, "matched")
        self.assertEqual(match.package_size, "matched")
        self.assertEqual(match.upc, "matched")
        self.assertEqual(match.brand, "unknown")

    def test_leading_zero_lot_preservation(self) -> None:
        """Items 2, 24: Leading-zero lot 060723 matches 060723, never 60723."""
        scope = _make_scope(
            recall_number="F-1542-2023",
            event_id="92944",
            product_name="Somebody's Mother's Island Sauce, Net Wt 9.5 oz (270g), UPC 5803100115",
            lot_numbers=("060723",),
            package_sizes=("9.5 oz",),
            upcs=("5803100115",),
        )
        row_exact = _make_row(
            item_id="INV-003-A",
            product_label="Somebody's Mother's Island Sauce",
            lot_code="060723",
            package_size="9.5 oz",
            upc="5803100115",
        )
        match_exact = compare_recall_to_inventory(scope, row_exact)
        self.assertEqual(match_exact.lot, "matched")
        self.assertEqual(match_exact.match_status, "exact")

        row_stripped = _make_row(
            item_id="INV-003-A",
            product_label="Somebody's Mother's Island Sauce",
            lot_code="60723",
            package_size="9.5 oz",
            upc="5803100115",
        )
        match_stripped = compare_recall_to_inventory(scope, row_stripped)
        self.assertEqual(match_stripped.lot, "mismatched")
        self.assertEqual(match_stripped.match_status, "no_match")

    def test_lot_mismatch(self) -> None:
        """Item 3: Lot mismatch produces no_match even when UPC, product, and package match."""
        scope = _make_scope(lot_numbers=("US3-12",))
        row = _make_row(lot_code="US3-11")
        match = compare_recall_to_inventory(scope, row)
        self.assertEqual(match.lot, "mismatched")
        self.assertEqual(match.match_status, "no_match")

    def test_brand_mismatch_and_unknown_handling(self) -> None:
        """Items 4, 27: Blank brand is unknown; concrete disagreeing brand is mismatched."""
        scope = _make_scope(brand="Fullei Fresh")
        row_blank = _make_row(brand="")
        match_blank = compare_recall_to_inventory(scope, row_blank)
        self.assertEqual(match_blank.brand, "unknown")
        # Because recall specified a concrete brand and inventory brand is unknown, match is partial
        self.assertEqual(match_blank.match_status, "partial")

        row_mismatch = _make_row(brand="SWAD")
        match_mismatch = compare_recall_to_inventory(scope, row_mismatch)
        self.assertEqual(match_mismatch.brand, "mismatched")
        self.assertEqual(match_mismatch.match_status, "no_match")

    def test_package_size_mismatch(self) -> None:
        """Item 5: Concrete package size mismatch returns no_match."""
        scope = _make_scope(package_sizes=("7.05oz",))
        row = _make_row(package_size="14 oz")
        match = compare_recall_to_inventory(scope, row)
        self.assertEqual(match.package_size, "mismatched")
        self.assertEqual(match.match_status, "no_match")

    def test_product_name_mismatch_and_distractor_exclusion(self) -> None:
        """Items 6, 28: *-B distractor with different product, lot, and package is excluded."""
        scope = _make_scope()
        distractor = _make_row(
            item_id="INV-001-B",
            product_label="Southern Belle Seafood Crabmeat Stuffing",
            upc="",
            lot_code="",
            package_size="",
        )
        match = compare_recall_to_inventory(scope, distractor)
        self.assertEqual(match.product_name, "mismatched")
        self.assertEqual(match.match_status, "no_match")

    def test_upc_separator_equivalence_and_mismatch(self) -> None:
        """Items 7, 25: UPC separators/spaces normalize for digit comparison only; never sole lot proof."""
        scope = _make_scope(upcs=("17442 30012",))
        row_same_upc = _make_row(upc="17442-30012")
        match = compare_recall_to_inventory(scope, row_same_upc)
        self.assertEqual(match.upc, "matched")
        self.assertEqual(match.match_status, "exact")

        # UPC match with missing lot in inventory is partial, never exact
        row_no_lot = _make_row(upc="1744230012", lot_code="")
        match_no_lot = compare_recall_to_inventory(scope, row_no_lot)
        self.assertEqual(match_no_lot.upc, "matched")
        self.assertEqual(match_no_lot.lot, "unknown")
        self.assertEqual(match_no_lot.match_status, "partial")

        # UPC mismatch
        row_bad_upc = _make_row(upc="999999999999")
        match_bad = compare_recall_to_inventory(scope, row_bad_upc)
        self.assertEqual(match_bad.upc, "mismatched")
        self.assertEqual(match_bad.match_status, "no_match")


if __name__ == "__main__":
    unittest.main()
