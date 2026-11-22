"""Read-only SQLite store for synthetic retailer inventory.

Opens in URI mode=ro with PRAGMA query_only=ON. Never uses synthetic_generation_note
or item_id suffix (-A/-B) as a matching oracle. Candidate discovery via vector/Qdrant
IDs must resolve through this authoritative SQLite database.
"""

from pathlib import Path
import re
import sqlite3

from inventory_loader import INVENTORY_COLUMNS
from models import Nonblank, StrictModel
from pydantic import Field


class InventoryStoreError(ValueError):
    """The retailer inventory SQLite database is unavailable or invalid."""


class InventorySchemaError(InventoryStoreError):
    """The retailer inventory SQLite schema or manifest does not match contract."""


class InventoryRow(StrictModel):
    inventory_set_id: Nonblank
    item_id: Nonblank
    retailer_id: Nonblank
    store_id: Nonblank
    product_label: str
    brand: str
    upc: str
    lot_code: str
    package_size: str
    simulated_quantity: int = Field(ge=0)
    quantity_unit: Nonblank
    inventory_reference_date: Nonblank
    source_type: Nonblank
    synthetic_generation_note: str


def _normalize_upc_digits(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = re.sub(r"[\s\-]+", "", value)
    if cleaned and cleaned.isdigit():
        return cleaned
    return None


def _parse_package_value_unit(value: str | None) -> tuple[float, str] | None:
    if not value or not value.strip():
        return None
    match = re.fullmatch(
        r"\s*(\d+(?:\.\d+)?)\s*(oz|ounces?|lb|lbs|pounds?|g|grams?|kg|kilograms?|gallons?|gal)\.?\s*",
        value,
        re.IGNORECASE,
    )
    if not match:
        return None
    num = float(match.group(1))
    raw_unit = match.group(2).lower()
    unit_map = {
        "oz": "oz",
        "ounce": "oz",
        "ounces": "oz",
        "lb": "lb",
        "lbs": "lb",
        "pound": "lb",
        "pounds": "lb",
        "g": "g",
        "gram": "g",
        "grams": "g",
        "kg": "kg",
        "kilogram": "kg",
        "kilograms": "kg",
        "gallon": "gallon",
        "gallons": "gallon",
        "gal": "gallon",
    }
    return (num, unit_map[raw_unit])


# Bounded deterministic product name equivalence table between FDA product_description
# substrings/canonical forms and retailer inventory product_label strings.
APPROVED_PRODUCT_NAME_EQUIVALENCES: dict[str, tuple[str, ...]] = {
    "donutful chocolate dipped vanilla cake donuts": ("donutful chocolate dipped vanilla cake donuts",),
    "solina garlic cream sauce seasoning": ("solina 6036277 garlic cream sauce seasoning", "solina garlic cream sauce seasoning"),
    "somebody's mother's island sauce": ("somebody's mother's island sauce",),
    "atlantic salmon portions with seafood stuffing": ("atlantic salmon portions with seafood stuffing",),
    "arepas la mejor sweet corn pancakes": (
        "arepas la mejor, arepa de chocolo (chocolate sweet corn pancakes)",
        "arepas la mejor sweet corn pancakes",
    ),
    "hillside orchard farms strawberry fritter": (
        "strawberry fritter net wt 7oz (198g) contains: wheat, soybeans, milk. made by: hillside orchard farms",
        "hillside orchard farms strawberry fritter",
    ),
    "hershey's green mint chip ice cream": (
        "hershey s ice cream, green mint chip (gmc) bulk",
        "hershey's green mint chip ice cream",
    ),
    "irvington seafood lump crab meat": ("irvington seafood lump crab meat",),
    "baiwei shanzhuang dried seedless plum candy": (
        "baiwei shanzhuang, dried seedless plum candy",
        "baiwei shanzhuang dried seedless plum candy",
    ),
    "southern belle seafood crabmeat stuffing": ("southern belle seafood crabmeat stuffing",),
    "brie royal faucon": ("brie royal faucon",),
    "blum's dried shrimp": ("blum's shrimp shred dried shrimp", "blum's dried shrimp"),
    "wilbur dark chocolate covered cashews": (
        "wilbur¿ dark chocolate covered cashews",
        "wilbur dark chocolate covered cashews",
    ),
    "vegan peanut butter jam cookie": (
        "gluten free vegan peanut butter jam cookie",
        "vegan peanut butter jam cookie",
    ),
    "fullei fresh alfalfa sprouts": (
        "fullei fresh brand alfalfa sprouts",
        "fullei fresh alfalfa sprouts",
    ),
    "vegetarian pia cake mung bean pumpkin": ("vegetarian pia cake mung bean pumpkin",),
    "tandoori peanut spread": ("tandoori peanut spread",),
    "cravings chocolate chunk cookie mix": (
        "the perfect chocolate chunk cookie mix cravings by chrissy teigen",
        "cravings chocolate chunk cookie mix",
    ),
    "smoked wahoo dip": ("smoked wahoo dip",),
    "queso de mano fresh white cheese": (
        "queso de mano, fresh soft white cheese",
        "queso de mano fresh white cheese",
    ),
    "cricket creek farm feta cheese": (
        "cricket creek farm brand feta cheese",
        "cricket creek farm feta cheese",
    ),
    "jack and the green sprouts alfalfa sprouts": (
        "jack & the green sprouts alfalfa sprouts",
        "jack and the green sprouts alfalfa sprouts",
    ),
    "fresh direct dark chocolate pretzels": ("fresh direct dark chocolate pretzels",),
    "swad cinnamon powder": ("swad brand cinnamon powder", "swad cinnamon powder"),
    "ginger snap milk chocolate": ("ginger snap milk chocolate",),
    "volupta organic black chia seeds": ("volupta organic black chia seeds",),
    "alpha steakless ranchero burrito": (
        "alpha plant-based burrito - steakless ranchero",
        "alpha steakless ranchero burrito",
    ),
    "hinterland mango habanero farmstead cheese": (
        "hinterland dairy farmstead cheese mango habanero",
        "hinterland mango habanero farmstead cheese",
    ),
    "chuao potato chip mini chocolate bar": (
        "chuao chocolatier potato chip mini chocolate bar",
        "chuao potato chip mini chocolate bar",
    ),
    "asli cinnamon powder": ("asli cinnamon powder",),
    "bettergoods pistachio nut butter": (
        "bettergoods brand pistachio nut butter",
        "bettergoods pistachio nut butter",
    ),
    "popping topping sour cream and onion popcorn seasoning": (
        "popping topping, sour cream & onion flavored popcorn seasoning",
        "popping topping sour cream and onion popcorn seasoning",
    ),
    "mon sire brie cheese": ("mon sire brie, soft-ripened french cheese", "mon sire brie", "mon sire brie cheese"),
    "todd's seeds alfalfa sprouting seeds": ("todd's seeds alfalfa sprouting seeds",),
    "taylor farms salsa roja medium": ("salsa roja medium", "taylor farms salsa roja medium"),
    "jk patisserie croissant": ("croissant; packaged in cardboard box", "jk patisserie croissant"),
    "bettergoods lemon alfredo fettuccine": ("lemon alfredo fettuccine", "bettergoods lemon alfredo fettuccine"),
    "annie's rising crust four cheese pizza": (
        "annie's homegrown rising crust four cheese pizza",
        "annie's rising crust four cheese pizza",
    ),
    "country fresh ovens cheese coffee cake": ("country fresh ovens cheese coffee cake",),
    "little salad bar asian chopped salad kit": ("little salad bar asian chopped salad kit",),
    "betty crocker super moist carrot cake mix": (
        "betty crocker delights super moist carrot cake mix",
        "betty crocker super moist carrot cake mix",
    ),
    "tastykake chocolate creme filled cupcakes": ("tastykake chocolate creme filled cupcakes",),
    "veggie pizza": ("veggie pizza sold under the following brands", "veggie pizza"),
    "full tilt vanilla bean ice cream": ("vanilla bean, full tilt ice cream", "full tilt vanilla bean ice cream"),
    "bundle organics salty nuts and seeds bar": (
        "bundle organics bar salty nuts and seeds",
        "bundle organics salty nuts and seeds bar",
    ),
    "blueberry greek yogurt bar": ("blueberry greek yogurt bar",),
    "gomacro coconut almond butter chocolate chip macrobar": (
        "go macro macrobar, coconut + almond butter + chocolate chips",
        "gomacro coconut almond butter chocolate chip macrobar",
    ),
    "reny picot brie with peppercorn": ("reny picot", "reny picot brie with peppercorn"),
}


def deterministic_product_name_matches(fda_product_name: str | None, inventory_label: str | None) -> bool:
    """Return True if fda_product_name and inventory_label match deterministically."""
    if not fda_product_name or not fda_product_name.strip() or not inventory_label or not inventory_label.strip():
        return False
    fda_norm = " ".join(fda_product_name.strip().lower().split())
    inv_norm = " ".join(inventory_label.strip().lower().split())
    if fda_norm == inv_norm:
        return True
    if fda_norm.startswith(inv_norm):
        return True
    variants = APPROVED_PRODUCT_NAME_EQUIVALENCES.get(inv_norm, ())
    for variant in variants:
        if variant in fda_norm:
            return True
    return False


class InventoryStore:
    """Read-only SQLite wrapper for authoritative retailer inventory."""

    def __init__(self, path: Path) -> None:
        try:
            resolved = Path(path).resolve(strict=True)
            self._db = sqlite3.connect(resolved.as_uri() + "?mode=ro", uri=True)
        except Exception as exc:
            raise InventoryStoreError("Inventory SQLite database is unavailable") from exc
        try:
            self._db.row_factory = sqlite3.Row
            self._db.execute("PRAGMA query_only=ON")
            table_info = self._db.execute("PRAGMA table_info(inventory)").fetchall()
            cols = tuple(row["name"] for row in table_info)
            if cols != INVENTORY_COLUMNS:
                raise InventorySchemaError("Inventory table columns differ from approved contract")
            manifest = self._db.execute("SELECT * FROM manifest").fetchall()
            if len(manifest) != 1 or manifest[0]["synthetic"] != 1:
                raise InventorySchemaError("Invalid or missing inventory manifest")
            self.snapshot_id: str = manifest[0]["reference_snapshot_id"]
            self.source_sha256: str = manifest[0]["source_sha256"]
            self.set_count: int = manifest[0]["set_count"]
            self.record_count: int = manifest[0]["record_count"]
            actual_count = self._db.execute("SELECT count(*) FROM inventory").fetchone()[0]
            if actual_count != self.record_count:
                raise InventorySchemaError("Inventory row count differs from manifest")
        except InventoryStoreError:
            self._db.close()
            raise
        except Exception as exc:
            self._db.close()
            raise InventorySchemaError("Invalid inventory database schema") from exc

    def close(self) -> None:
        self._db.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def _row_to_model(self, row: sqlite3.Row) -> InventoryRow:
        return InventoryRow.model_validate({col: row[col] for col in INVENTORY_COLUMNS})

    def resolve_candidate_ids(self, candidate_item_ids: tuple[str, ...]) -> list[InventoryRow]:
        """Re-query candidate item IDs (e.g. from Qdrant) against authoritative SQLite.

        Any candidate ID absent from SQLite is rejected/excluded.
        """
        if not candidate_item_ids:
            return []
        try:
            results: list[InventoryRow] = []
            seen: set[str] = set()
            for item_id in candidate_item_ids:
                if not isinstance(item_id, str) or item_id in seen:
                    continue
                seen.add(item_id)
                row = self._db.execute(
                    "SELECT * FROM inventory WHERE item_id = ?", (item_id,)
                ).fetchone()
                if row is not None:
                    results.append(self._row_to_model(row))
            return results
        except Exception as exc:
            raise InventoryStoreError("SQLite read failure during candidate ID resolution") from exc

    def _select(self, where: str, params: tuple, id_filter: tuple[str, ...] | None) -> list[InventoryRow]:
        """Run one parameterized SELECT; `where` is always a constant fragment."""
        sql = "SELECT * FROM inventory WHERE (" + where + ")"
        args = list(params)
        if id_filter is not None:
            sql += " AND item_id IN (" + ",".join("?" * len(id_filter)) + ")"
            args.extend(id_filter)
        sql += " ORDER BY item_id"
        return [self._row_to_model(r) for r in self._db.execute(sql, args).fetchall()]

    def find_inventory_candidates(
        self,
        brand: str | None,
        product_name: str | None,
        lot_numbers: tuple[str, ...],
        package_sizes: tuple[str, ...],
        *,
        upcs: tuple[str, ...] = (),
        candidate_item_ids: tuple[str, ...] | None = None,
    ) -> list[InventoryRow]:
        """Discover candidate rows with SQLite filters in literal priority order:
        1. Exact UPC digits (only rows with an explicit UPC)
        2. Exact lot code (binary comparison: leading zeros and case preserved)
        3. Exact/approved-deterministic product label, else package size
        4. Brand, only when nothing else matched
        Never reads synthetic_generation_note or the -A/-B item suffix. When
        candidate_item_ids (e.g. from a vector index) is given, results are
        restricted to IDs that exist in SQLite; absent IDs are dropped.
        The deterministic matcher remains the final authority.
        """
        ids: tuple[str, ...] | None = None
        if candidate_item_ids is not None:
            ids = tuple(dict.fromkeys(i for i in candidate_item_ids if isinstance(i, str)))
            if not ids:
                return []
        norm_upcs = sorted({d for u in upcs if (d := _normalize_upc_digits(u)) is not None})
        exact_lots = sorted({lot for lot in lot_numbers if isinstance(lot, str) and lot != ""})
        parsed_pkgs = {p for s in package_sizes if (p := _parse_package_value_unit(s)) is not None}
        raw_pkgs = {s.strip().lower() for s in package_sizes if s and s.strip()}
        norm_brand = brand.strip().lower() if brand and brand.strip() else None

        candidates: list[InventoryRow] = []
        seen: set[str] = set()

        def add(rows: list[InventoryRow]) -> None:
            for r in rows:
                if r.item_id not in seen:
                    seen.add(r.item_id)
                    candidates.append(r)

        try:
            if norm_upcs:
                add(self._select(
                    "upc != '' AND REPLACE(REPLACE(upc, ' ', ''), '-', '') IN ("
                    + ",".join("?" * len(norm_upcs)) + ")", tuple(norm_upcs), ids))
            if exact_lots:
                add(self._select(
                    "lot_code != '' AND lot_code IN (" + ",".join("?" * len(exact_lots)) + ")",
                    tuple(exact_lots), ids))
            if product_name and product_name.strip():
                labels = [r[0] for r in self._db.execute(
                    "SELECT DISTINCT product_label FROM inventory WHERE product_label != ''")]
                hit = [l for l in labels if deterministic_product_name_matches(product_name, l)]
                if hit:
                    add(self._select("product_label IN (" + ",".join("?" * len(hit)) + ")",
                                     tuple(hit), ids))
            elif parsed_pkgs or raw_pkgs:
                sizes = [r[0] for r in self._db.execute(
                    "SELECT DISTINCT package_size FROM inventory WHERE package_size != ''")]
                hit = [s for s in sizes
                       if _parse_package_value_unit(s) in parsed_pkgs
                       or s.strip().lower() in raw_pkgs]
                if hit:
                    add(self._select("package_size IN (" + ",".join("?" * len(hit)) + ")",
                                     tuple(hit), ids))
            if not candidates and norm_brand is not None:
                add(self._select("brand != '' AND LOWER(TRIM(brand)) = ?", (norm_brand,), ids))
        except InventoryStoreError:
            raise
        except Exception as exc:
            raise InventoryStoreError("SQLite read failure during inventory lookup") from exc
        return candidates
