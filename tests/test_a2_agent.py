"""Acceptance tests for a2_agent.py (Items 1, 8-15, 18-21, 29, 30)."""

from pathlib import Path
import sqlite3
import tempfile
import unittest

from a1_run import A1RunEnvelope, RunError
from a1_trace import RunTrace
from a2_agent import A2RunEnvelope, InventoryFinding, run_a2
from group_c_contract import GroupCResult, RelationPart, SourceRelation
from inventory_loader import DEFAULT_INVENTORY_JSON, build_inventory_store
from inventory_store import InventoryStore
from models import A1Result, Facts, Identifier, SourceField, SourceFields
from pydantic import ValidationError


SNAPSHOT = "FDA-FOOD-2026-10-23-USER-SNAPSHOT"
DUMMY_UUID = "50b6bb65-921a-55ed-8d00-4f5f56962cc7"


def _make_trace(recall_number: str = "H-0011-2027", event_id: str = "99686") -> RunTrace:
    return RunTrace(
        recall_number=recall_number,
        snapshot_id=SNAPSHOT,
        event_id=event_id,
        collection="recallready_fda_food_a1_v1",
        embedding_model="sentence-transformers/all-minilm-l6-v2",
        max_output_tokens=4000,
        started_utc="2026-11-20T00:00:00+00:00",
        completed_utc="2026-11-20T00:00:01+00:00",
    )


def _make_source_fields(recall_number: str, product_text: str, code_text: str) -> SourceFields:
    return SourceFields(
        product_description=SourceField(
            original_text=product_text,
            evidence_id=f"EV-{recall_number}-PRODUCT_DESCRIPTION",
            point_id=DUMMY_UUID,
        ),
        code_info=SourceField(
            original_text=code_text,
            evidence_id=f"EV-{recall_number}-CODE_INFO",
            point_id=DUMMY_UUID,
        ),
        reason_for_recall=SourceField(
            original_text="Undeclared allergen",
            evidence_id=f"EV-{recall_number}-REASON_FOR_RECALL",
            point_id=DUMMY_UUID,
        ),
        distribution_pattern=SourceField(
            original_text="Nationwide",
            evidence_id=f"EV-{recall_number}-DISTRIBUTION_PATTERN",
            point_id=DUMMY_UUID,
        ),
        recalling_firm=SourceField(
            original_text="Test Firm",
            evidence_id=None,
            point_id=None,
        ),
        classification=SourceField(
            original_text="Class I",
            evidence_id=None,
            point_id=None,
        ),
    )


def _make_a1_envelope(
    *,
    run_id: str = "run-001",
    recall_number: str = "H-0011-2027",
    event_id: str = "99686",
    product_name: str = "Donutful Chocolate Dipped Vanilla Cake Donuts - 7.05oz/10ct. UPC 850041392103.",
    code_info: str = "Lot # 26078 BEST BY: 09/15/2026",
    identifiers: list[Identifier] | None = None,
    uncertainties: list[str] | None = None,
) -> A1RunEnvelope:
    ev_ids = [
        f"EV-{recall_number}-PRODUCT_DESCRIPTION",
        f"EV-{recall_number}-CODE_INFO",
        f"EV-{recall_number}-REASON_FOR_RECALL",
        f"EV-{recall_number}-DISTRIBUTION_PATTERN",
    ]
    if identifiers is None:
        identifiers = [
            Identifier(
                kind="lot",
                value="26078",
                scope_note=code_info,
                evidence_ids=[f"EV-{recall_number}-CODE_INFO"],
            ),
            Identifier(
                kind="upc",
                value="850041392103",
                scope_note=product_name,
                evidence_ids=[f"EV-{recall_number}-PRODUCT_DESCRIPTION"],
            ),
        ]
    a1_result = A1Result(
        contract_version="0.1-proposed",
        snapshot_id=SNAPSHOT,
        event_id=event_id,
        facts=Facts(
            recall_number=recall_number,
            product_name=product_name,
            recalling_firm="Test Firm",
            recall_reason="Undeclared allergen",
            classification="Class I",
            identifiers=identifiers,
            uncertainties=uncertainties or [],
            evidence_ids=ev_ids,
        ),
        source_fields=_make_source_fields(recall_number, product_name, code_info),
    )
    return A1RunEnvelope(
        run_id=run_id,
        status="validated",
        result=a1_result,
        error=None,
        trace=_make_trace(recall_number, event_id),
    )


class TestA2Agent(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.db_path = Path(cls._tmp.name) / "inventory.sqlite"
        build_inventory_store(cls.db_path, json_path=DEFAULT_INVENTORY_JSON)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_exact_match_preserves_quantity_store_and_original_text(self) -> None:
        """Items 1, 19, 30: Validated A1 envelope + exact match preserves quantity, store, date, and original strings."""
        envelope = _make_a1_envelope()
        with InventoryStore(self.db_path) as store:
            a2 = run_a2(store, envelope, case_id="case-001", run_id="run-001")
        self.assertEqual(a2.status, "matched")
        self.assertIsNone(a2.error)
        self.assertFalse(a2.requires_human_review)
        self.assertEqual(len(a2.findings), 1)
        f = a2.findings[0]
        self.assertEqual(f.item_id, "INV-001-A")
        self.assertEqual(f.match_status, "exact")
        self.assertEqual(f.simulated_quantity, 12)
        self.assertEqual(f.store_id, "SIM-STORE-02")
        self.assertEqual(f.inventory_reference_date, "2026-08-17")
        self.assertEqual(f.package_size, "7.05oz")
        self.assertEqual(f.lot_code, "26078")
        self.assertEqual(f.upc, "850041392103")
        self.assertEqual(f.brand, "")
        self.assertEqual(f.brand_match, "unknown")

    def test_multiple_matching_rows_preserved_separately(self) -> None:
        """Item 8: Multiple matching inventory rows and quantities are never merged."""
        from contextlib import closing

        multi_db = Path(self._tmp.name) / "multi.sqlite"
        build_inventory_store(multi_db, json_path=DEFAULT_INVENTORY_JSON)
        # Add a second matching row in a separate store location
        with closing(sqlite3.connect(multi_db)) as db:
            with db:
                db.execute("UPDATE manifest SET record_count = 97")
                db.execute(
                    """
                    INSERT INTO inventory VALUES (
                        'SIMSET-001', 'INV-001-A2', 'SIM-RETAILER-01', 'SIM-STORE-09',
                        'Donutful Chocolate Dipped Vanilla Cake Donuts', '', '850041392103',
                        '26078', '7.05oz', 44, 'packages', '2026-08-18', 'SYNTHETIC', 'Second store stock'
                    )
                    """
                )
        envelope = _make_a1_envelope()
        with InventoryStore(multi_db) as store:
            a2 = run_a2(store, envelope, case_id="case-multi", run_id="run-001")
        self.assertEqual(a2.status, "matched")
        self.assertEqual(len(a2.findings), 2)
        quantities = {f.item_id: (f.simulated_quantity, f.store_id) for f in a2.findings}
        self.assertEqual(quantities["INV-001-A"], (12, "SIM-STORE-02"))
        self.assertEqual(quantities["INV-001-A2"], (44, "SIM-STORE-09"))

    def test_no_inventory_match_returns_no_match_status_not_error(self) -> None:
        """Items 3, 9, 20: Explicit lot mismatch returns no_match with empty findings and no error."""
        # F-0818-2023 has lot US3-12 in FDA recall, while INV-017-A has lot US3-11
        prod = "Tandoori Peanut Spread; Net. Wt 11.29  oz PetJar; packed in cases consisting of 12 Jars per case"
        code = "UPC Code 8904067712635 Lot # US3-12"
        envelope = _make_a1_envelope(
            recall_number="F-0818-2023",
            event_id="92067",
            product_name=prod,
            code_info=code,
            identifiers=[
                Identifier(
                    kind="lot",
                    value="US3-12",
                    scope_note=code,
                    evidence_ids=["EV-F-0818-2023-CODE_INFO"],
                ),
                Identifier(
                    kind="upc",
                    value="8904067712635",
                    scope_note=code,
                    evidence_ids=["EV-F-0818-2023-CODE_INFO"],
                ),
            ],
        )
        with InventoryStore(self.db_path) as store:
            a2 = run_a2(store, envelope, case_id="case-nomatch", run_id="run-001")
        self.assertEqual(a2.status, "no_match")
        self.assertEqual(a2.findings, [])
        self.assertIsNone(a2.error)

    def test_group_c_explicit_lot_date_relation_and_package_lot_ambiguity(self) -> None:
        """Items 10, 11, 21: Group C lot/date relation matched only from explicit relation; package/lot ambiguity stays unresolved."""
        # H-1388-2026: Mon Sire Brie, 1 kg, LOT 00000ZRAA1 EXP 08/15/2026
        prod = "Mon Sire Brie, soft-ripened French cheese, 1 kg"
        code = "LOT 00000ZRAA1  EXP 08/15/2026 LOT 00000ZUAD2  EXP 08/18/2026"
        base_env = _make_a1_envelope(
            recall_number="H-1388-2026",
            event_id="99841",
            product_name=prod,
            code_info=code,
            identifiers=[],
            uncertainties=["Group C relationship requires human review."],
        )
        group_c = GroupCResult(
            contract_version="0.2-group-c-provisional",
            base=base_env.result,
            relations=[
                SourceRelation(
                    kind="lot_date",
                    evidence_id="EV-H-1388-2026-CODE_INFO",
                    start=0,
                    end=30,
                    source_span="LOT 00000ZRAA1  EXP 08/15/2026",
                    parts=[
                        RelationPart(role="lot", value="00000ZRAA1"),
                        RelationPart(role="date", value="08/15/2026"),
                    ],
                )
            ],
        )
        gc_env = A1RunEnvelope(
            run_id="run-gc",
            status="validated",
            result=group_c,
            error=None,
            trace=_make_trace("H-1388-2026", "99841"),
        )
        with InventoryStore(self.db_path) as store:
            # Default route stops Group C before inventory match unless approved route enabled
            stopped = run_a2(store, gc_env, case_id="case-gc-stop")
            self.assertEqual(stopped.status, "unresolved")
            self.assertEqual(stopped.error.code, "ambiguous_recall_scope")

            # When approved route enabled, INV-033-A (which has lot_code='') is excluded unless lot or UPC matches;
            # if a row in inventory matches the explicit Group C lot_date lot 00000ZRAA1, it is returned as partial
            # (preserving Group C review uncertainty).
            from contextlib import closing

            gc_db = Path(self._tmp.name) / "gc_match.sqlite"
            build_inventory_store(gc_db, json_path=DEFAULT_INVENTORY_JSON)
            with closing(sqlite3.connect(gc_db)) as db:
                with db:
                    db.execute(
                        "UPDATE inventory SET lot_code = '00000ZRAA1' WHERE item_id = 'INV-033-A'"
                    )
            with InventoryStore(gc_db) as gc_store:
                resumed = run_a2(gc_store, gc_env, case_id="case-gc-resume", allow_group_c_or_uncertain=True)
            self.assertEqual(resumed.status, "partial")
            self.assertTrue(resumed.requires_human_review)
            self.assertEqual(len(resumed.findings), 1)
            self.assertEqual(resumed.findings[0].item_id, "INV-033-A")
            self.assertEqual(resumed.findings[0].match_status, "partial")
            self.assertEqual(resumed.findings[0].lot_match, "matched")
            self.assertIn("00000ZRAA1", resumed.findings[0].a1_identifier_values)

        # Item 11 & 21: Group C with multiple package sizes and multiple lots (F-2413-2017) -> ambiguous_recall_scope
        prod_multi = "go macro MACROBAR, 1. Net Wt 0.9 oz / 25 G minbar and 2. net Wt 2.3 oz / 65 G"
        code_multi = "3516 / 1/3/2018, 3537 / 1/16/2018"
        base_multi = _make_a1_envelope(
            recall_number="F-2413-2017",
            event_id="77557",
            product_name=prod_multi,
            code_info=code_multi,
            identifiers=[],
            uncertainties=["Multi-size lot relationship ambiguous"],
        )
        gc_multi = GroupCResult(
            contract_version="0.2-group-c-provisional",
            base=base_multi.result,
            relations=[
                SourceRelation(
                    kind="lot_date",
                    evidence_id="EV-F-2413-2017-CODE_INFO",
                    start=0,
                    end=15,
                    source_span="3516 / 1/3/2018",
                    parts=[
                        RelationPart(role="lot", value="3516"),
                        RelationPart(role="date", value="1/3/2018"),
                    ],
                ),
                SourceRelation(
                    kind="lot_date",
                    evidence_id="EV-F-2413-2017-CODE_INFO",
                    start=17,
                    end=33,
                    source_span="3537 / 1/16/2018",
                    parts=[
                        RelationPart(role="lot", value="3537"),
                        RelationPart(role="date", value="1/16/2018"),
                    ],
                ),
            ],
        )
        gc_multi_env = A1RunEnvelope(
            run_id="run-gc-multi",
            status="validated",
            result=gc_multi,
            error=None,
            trace=_make_trace("F-2413-2017", "77557"),
        )
        with InventoryStore(self.db_path) as store:
            ambig = run_a2(store, gc_multi_env, case_id="case-ambig", allow_group_c_or_uncertain=True)
            self.assertEqual(ambig.status, "unresolved")
            self.assertEqual(ambig.error.code, "ambiguous_recall_scope")

    def test_a1_unresolved_does_not_call_inventory_or_produce_findings(self) -> None:
        """Item 12: A1 unresolved status returns unresolved with a1_unresolved and no findings."""
        unresolved_env = A1RunEnvelope(
            run_id="run-unres",
            status="unresolved",
            result=None,
            error=RunError(
                stage="interpretation",
                code="provider_failure",
                message="A1 failed",
                request_state="not_sent",
            ),
            trace=_make_trace(),
        )
        with InventoryStore(self.db_path) as store:
            a2 = run_a2(store, unresolved_env, case_id="case-unres")
        self.assertEqual(a2.status, "unresolved")
        self.assertEqual(a2.error.code, "a1_unresolved")
        self.assertEqual(a2.findings, [])

    def test_context_mismatch_rejected(self) -> None:
        """Item 13: Recall/snapshot/event/run_id mismatch rejected."""
        envelope = _make_a1_envelope()
        with InventoryStore(self.db_path) as store:
            a2_recall = run_a2(store, envelope, recall_number="F-1542-2023")
            self.assertEqual(a2_recall.status, "unresolved")
            self.assertEqual(a2_recall.error.code, "a1_context_mismatch")

            a2_snap = run_a2(store, envelope, snapshot_id="WRONG-SNAPSHOT")
            self.assertEqual(a2_snap.status, "unresolved")
            self.assertEqual(a2_snap.error.code, "a1_context_mismatch")

            a2_event = run_a2(store, envelope, event_id="00000")
            self.assertEqual(a2_event.status, "unresolved")
            self.assertEqual(a2_event.error.code, "a1_context_mismatch")

    def test_sqlite_unavailable_differs_from_no_match(self) -> None:
        """Items 14, 20: Inventory SQLite failure is a typed unresolved outcome, never no_match."""
        envelope = _make_a1_envelope()
        store = InventoryStore(self.db_path)
        store.close()  # Simulate closed/unavailable database connection
        a2 = run_a2(store, envelope, case_id="case-closed")
        self.assertEqual(a2.status, "unresolved")
        self.assertEqual(a2.error.code, "inventory_store_unavailable")
        self.assertNotEqual(a2.status, "no_match")

    def test_strict_pydantic_output_rejects_extra_fields(self) -> None:
        """Item 15: Strict Pydantic output rejects extra fields on InventoryFinding and A2RunEnvelope."""
        envelope = _make_a1_envelope()
        with InventoryStore(self.db_path) as store:
            a2 = run_a2(store, envelope, case_id="case-strict")
        finding_dict = a2.findings[0].model_dump()
        finding_dict["recommended_action"] = "quarantine"
        with self.assertRaises(ValidationError):
            InventoryFinding.model_validate(finding_dict)

        env_dict = a2.model_dump()
        env_dict["extra_field"] = "forbidden"
        with self.assertRaises(ValidationError):
            A2RunEnvelope.model_validate(env_dict)


if __name__ == "__main__":
    unittest.main()
