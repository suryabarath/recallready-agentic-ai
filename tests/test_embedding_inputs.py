"""Embedding preparation never generates vectors or touches Qdrant."""

from embedding_inputs import load_embedding_inputs
from fda_store import FDAStore, build_fda_store
from source import DEVELOPMENT_RECORDS, FIELDS


def test_all_staging_inputs_bind_to_exact_sqlite_source(tmp_path):
    path = tmp_path / "fda.sqlite"
    build_fda_store(path)
    with FDAStore(path) as store:
        inputs = load_embedding_inputs(store)
        assert len(inputs) == 72
        assert len({item.point_id for item in inputs}) == 72
        assert {item.evidence_id for item in inputs} == {
            f"EV-{recall}-{field.upper()}" for recall in DEVELOPMENT_RECORDS for field in FIELDS
        }
        assert all(item.snapshot_id == store.snapshot_id and item.text_for_embedding
                   for item in inputs)
