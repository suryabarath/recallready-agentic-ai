"""Acceptance tests for inventory_store.py (Items 14, 16, 18, 29)."""

from pathlib import Path
import sqlite3
import tempfile
import unittest

from inventory_loader import DEFAULT_INVENTORY_JSON, build_inventory_store
from inventory_store import (
    InventorySchemaError,
    InventoryStore,
    InventoryStoreError,
)


class TestInventoryStore(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.db_path = Path(cls._tmp.name) / "inventory.sqlite"
        build_inventory_store(cls.db_path, json_path=DEFAULT_INVENTORY_JSON)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_opens_read_only_and_blocks_writes(self) -> None:
        """Item 16: SQL connection opens read-only and cannot modify inventory."""
        with InventoryStore(self.db_path) as store:
            self.assertEqual(store.snapshot_id, "FDA-FOOD-2026-10-23-USER-SNAPSHOT")
            self.assertEqual(store.set_count, 48)
            self.assertEqual(store.record_count, 96)
            with self.assertRaises(sqlite3.OperationalError):
                store._db.execute(
                    "UPDATE inventory SET simulated_quantity = 0 WHERE item_id = 'INV-001-A'"
                )
            with self.assertRaises(sqlite3.OperationalError):
                store._db.execute("DELETE FROM inventory")

    def test_missing_database_raises_store_error(self) -> None:
        """Item 14: Unavailable SQLite database raises InventoryStoreError."""
        with self.assertRaises(InventoryStoreError):
            InventoryStore(Path(self._tmp.name) / "does_not_exist.sqlite")

    def test_invalid_schema_raises_schema_error(self) -> None:
        from contextlib import closing

        bad_db = Path(self._tmp.name) / "bad_schema.sqlite"
        with closing(sqlite3.connect(bad_db)) as db:
            with db:
                db.execute("CREATE TABLE inventory (item_id TEXT PRIMARY KEY)")
        with self.assertRaises(InventorySchemaError):
            InventoryStore(bad_db)

    def test_candidate_lookup_priority_and_vector_id_resolution(self) -> None:
        """Items 18, 29: Candidate IDs from Qdrant/vector search absent from SQLite are rejected."""
        with InventoryStore(self.db_path) as store:
            resolved = store.resolve_candidate_ids(("INV-001-A", "INV-999-MISSING", "INV-003-A"))
            self.assertEqual([r.item_id for r in resolved], ["INV-001-A", "INV-003-A"])

            # Candidate search restricted to nonexistent vector candidate returns empty
            none_found = store.find_inventory_candidates(
                brand=None,
                product_name="Donutful Chocolate Dipped Vanilla Cake Donuts",
                lot_numbers=("26078",),
                package_sizes=("7.05oz",),
                upcs=("850041392103",),
                candidate_item_ids=("INV-999-MISSING",),
            )
            self.assertEqual(none_found, [])

            # Candidate search with real data finds INV-003-A (leading zero lot 060723)
            candidates = store.find_inventory_candidates(
                brand=None,
                product_name="Somebody's Mother's Island Sauce, Net Wt 9.5 oz (270g), UPC 5803100115",
                lot_numbers=("060723",),
                package_sizes=("9.5 oz",),
                upcs=("5803100115",),
            )
            item_ids = [c.item_id for c in candidates]
            self.assertIn("INV-003-A", item_ids)


if __name__ == "__main__":
    unittest.main()
