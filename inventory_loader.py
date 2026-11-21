"""Synthetic retailer inventory JSON-to-SQLite loader for A2.

Loads 02_retailer_inventory_SYNTHETIC.json into an exact read-only-ready SQLite
schema with manifest verification (48 sets, 96 rows, 1 *-A and 1 *-B per set).
Does not inject FDA recall facts or evaluation labels.
"""

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3



DEFAULT_INVENTORY_JSON = (
    Path(__file__).resolve().parent.parent / "02_retailer_inventory_SYNTHETIC.json"
)

INVENTORY_COLUMNS = (
    "inventory_set_id",
    "item_id",
    "retailer_id",
    "store_id",
    "product_label",
    "brand",
    "upc",
    "lot_code",
    "package_size",
    "simulated_quantity",
    "quantity_unit",
    "inventory_reference_date",
    "source_type",
    "synthetic_generation_note",
)


class InventoryLoadError(ValueError):
    """The synthetic inventory JSON or target database cannot be validated."""


def _validate_record_shape(record: object) -> dict:
    if not isinstance(record, dict):
        raise InventoryLoadError("Inventory record must be a JSON object")
    if set(record.keys()) != set(INVENTORY_COLUMNS):
        raise InventoryLoadError("Inventory record keys differ from required column set")
    for col in INVENTORY_COLUMNS:
        val = record[col]
        if col == "simulated_quantity":
            if isinstance(val, bool) or not isinstance(val, int) or val < 0:
                raise InventoryLoadError("simulated_quantity must be a non-negative integer")
        else:
            if not isinstance(val, str):
                raise InventoryLoadError(f"Column {col} must be a string")
    if not record["inventory_set_id"].strip() or not record["item_id"].strip():
        raise InventoryLoadError("inventory_set_id and item_id must be nonblank")
    if record["source_type"] != "SYNTHETIC":
        raise InventoryLoadError("Inventory source_type must be SYNTHETIC")
    return record


def build_inventory_store(
    db_path: Path,
    *,
    json_path: Path = DEFAULT_INVENTORY_JSON,
    expected_set_count: int | None = 48,
    expected_record_count: int | None = 96,
) -> None:
    """Create a new synthetic retailer inventory SQLite database from JSON.

    Refuses to overwrite an existing database file. Validates exact set and
    row counts and ensures every set has one *-A and one *-B row.
    """
    db_path = Path(db_path)
    if db_path.exists():
        raise InventoryLoadError(f"Refusing to overwrite existing database: {db_path}")
    json_path = Path(json_path)
    try:
        raw_bytes = json_path.read_bytes()
        payload = json.loads(raw_bytes.decode("utf-8-sig"))
    except Exception as exc:
        raise InventoryLoadError("Unable to read synthetic inventory JSON") from exc

    if not isinstance(payload, dict):
        raise InventoryLoadError("Top-level inventory JSON must be an object")
    if payload.get("synthetic") is not True:
        raise InventoryLoadError("Inventory JSON must declare synthetic=true")
    snapshot_id = payload.get("reference_snapshot_id")
    if not isinstance(snapshot_id, str) or not snapshot_id.strip():
        raise InventoryLoadError("Missing or invalid reference_snapshot_id")
    records = payload.get("records")
    if not isinstance(records, list) or not records:
        raise InventoryLoadError("Inventory JSON must contain a non-empty records list")

    validated_records = [_validate_record_shape(r) for r in records]
    if expected_record_count is not None and len(validated_records) != expected_record_count:
        raise InventoryLoadError(
            f"Expected {expected_record_count} inventory records, got {len(validated_records)}"
        )

    sets: dict[str, list[str]] = {}
    seen_items: set[str] = set()
    for rec in validated_records:
        item_id = rec["item_id"]
        if item_id in seen_items:
            raise InventoryLoadError(f"Duplicate item_id: {item_id}")
        seen_items.add(item_id)
        sets.setdefault(rec["inventory_set_id"], []).append(item_id)

    if expected_set_count is not None and len(sets) != expected_set_count:
        raise InventoryLoadError(
            f"Expected {expected_set_count} inventory sets, got {len(sets)}"
        )
    for set_id, item_ids in sets.items():
        a_items = [i for i in item_ids if i.endswith("-A")]
        b_items = [i for i in item_ids if i.endswith("-B")]
        if len(item_ids) != 2 or len(a_items) != 1 or len(b_items) != 1:
            raise InventoryLoadError(
                f"Inventory set {set_id} must contain exactly one *-A and one *-B row"
            )

    source_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(db_path)
    try:
        with db:
            db.execute("PRAGMA foreign_keys=ON")
            db.executescript(
                """
                CREATE TABLE manifest (
                    synthetic INTEGER NOT NULL CHECK(synthetic = 1),
                    reference_snapshot_id TEXT PRIMARY KEY,
                    source_sha256 TEXT NOT NULL,
                    set_count INTEGER NOT NULL CHECK(set_count > 0),
                    record_count INTEGER NOT NULL CHECK(record_count > 0)
                );
                CREATE TABLE inventory (
                    inventory_set_id TEXT NOT NULL,
                    item_id TEXT PRIMARY KEY,
                    retailer_id TEXT NOT NULL,
                    store_id TEXT NOT NULL,
                    product_label TEXT NOT NULL,
                    brand TEXT NOT NULL,
                    upc TEXT NOT NULL,
                    lot_code TEXT NOT NULL,
                    package_size TEXT NOT NULL,
                    simulated_quantity INTEGER NOT NULL CHECK(simulated_quantity >= 0),
                    quantity_unit TEXT NOT NULL,
                    inventory_reference_date TEXT NOT NULL,
                    source_type TEXT NOT NULL CHECK(source_type = 'SYNTHETIC'),
                    synthetic_generation_note TEXT NOT NULL
                );
                CREATE INDEX idx_inventory_upc ON inventory(upc);
                CREATE INDEX idx_inventory_lot_code ON inventory(lot_code);
                CREATE INDEX idx_inventory_product_label ON inventory(product_label);
                """
            )
            db.execute(
                "INSERT INTO manifest VALUES (1, ?, ?, ?, ?)",
                (snapshot_id, source_sha256, len(sets), len(validated_records)),
            )
            for rec in validated_records:
                db.execute(
                    """
                    INSERT INTO inventory VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                    )
                    """,
                    tuple(rec[col] for col in INVENTORY_COLUMNS),
                )
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build synthetic retailer inventory SQLite database")
    parser.add_argument("db_path", type=Path, help="New SQLite database path; existing files are refused")
    parser.add_argument(
        "--json-path",
        type=Path,
        default=DEFAULT_INVENTORY_JSON,
        help="Path to 02_retailer_inventory_SYNTHETIC.json",
    )
    args = parser.parse_args()
    build_inventory_store(args.db_path, json_path=args.json_path)
    print(f"Created {args.db_path} from {args.json_path}")
