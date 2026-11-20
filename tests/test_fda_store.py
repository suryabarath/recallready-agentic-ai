"""Exact FDA SQLite store checks against the immutable starter source."""

import hashlib
import json
import sqlite3

import pytest

from fda_store import FDAStore, StoreError, build_fda_store
from group_c_contract import validate_group_c_result
from group_c_interpreter import interpret_group_c
from interpreter import Budget, interpret, main
from source import DEFAULT_ARCHIVE, DEVELOPMENT_RECORDS, FIELDS, Source
from test_group_c_contract import example as group_c_example
from test_group_c_interpreter import proposal as group_c_proposal
from test_interpreter import client_for, proposal as a_b_proposal
from test_task02b import EXAMPLES, ctx
from validation import validate_result


def test_all_18_records_and_72_passages_round_trip(tmp_path):
    path = tmp_path / "fda.sqlite"
    build_fda_store(path)
    original = Source()
    with FDAStore(path) as store:
        assert store.snapshot_id == original.snapshot_id
        assert store.archive_sha256 == hashlib.sha256(DEFAULT_ARCHIVE.read_bytes()).hexdigest()
        for recall in DEVELOPMENT_RECORDS:
            record = original.lookup(recall, snapshot_id=original.snapshot_id)
            context = dict(recall_number=recall, event_id=record["event_id"],
                           snapshot_id=original.snapshot_id)
            assert store.lookup(**context) == record
            for field in FIELDS:
                evidence_id = f"EV-{recall}-{field.upper()}"
                assert store.resolve(evidence_id, **context) == original.resolve(evidence_id, **context)
    with pytest.raises(StoreError, match="Refusing to overwrite"):
        build_fda_store(path)


def test_wrong_context_and_tampered_passage_rejected(tmp_path):
    path = tmp_path / "fda.sqlite"
    build_fda_store(path)
    source = Source()
    first, second = DEVELOPMENT_RECORDS[:2]
    record = source.lookup(first, snapshot_id=source.snapshot_id)
    context = dict(recall_number=first, event_id=record["event_id"],
                   snapshot_id=source.snapshot_id)
    evidence_id = f"EV-{first}-CODE_INFO"
    with FDAStore(path) as store:
        with pytest.raises(StoreError):
            store.lookup(first, snapshot_id="WRONG")
        with pytest.raises(StoreError):
            store.lookup(first, snapshot_id=source.snapshot_id, event_id="WRONG")
        with pytest.raises(StoreError):
            store.resolve(f"EV-{second}-CODE_INFO", **context)
        with pytest.raises(StoreError):
            store.resolve("EV-INVENTED-CODE_INFO", **context)
    with sqlite3.connect(path) as db:
        db.execute("UPDATE passages SET original_text = 'INVENTED' WHERE evidence_id = ?",
                   (evidence_id,))
    with FDAStore(path) as store:
        with pytest.raises(StoreError, match="passage differs"):
            store.resolve(evidence_id, **context)


def test_incomplete_store_rejected(tmp_path):
    path = tmp_path / "fda.sqlite"
    build_fda_store(path)
    with sqlite3.connect(path) as db:
        db.execute("DELETE FROM passages WHERE field_name = 'code_info'")
    with pytest.raises(StoreError, match="counts differ"):
        FDAStore(path)


def test_existing_a1_validators_accept_exact_sqlite_source(tmp_path):
    path = tmp_path / "fda.sqlite"
    build_fda_store(path)
    with FDAStore(path) as store:
        result = validate_result(EXAMPLES[0], store, **ctx(EXAMPLES[0]))
        assert result.facts.recall_number == DEVELOPMENT_RECORDS[0]
        payload, context = group_c_example(Source(), "F-0536-2021")
        group_c = validate_group_c_result(payload, store, **context)
        assert group_c.base.facts.recall_number == "F-0536-2021"


def test_both_interpreters_use_sqlite_evidence_offline(tmp_path):
    path = tmp_path / "fda.sqlite"
    build_fda_store(path)
    with FDAStore(path) as store:
        seen = []
        with client_for([(json.dumps(a_b_proposal(0)), "completed")], seen) as client:
            result = interpret(store, client, Budget(tmp_path / "a_usage.sqlite"),
                               recall_number=DEVELOPMENT_RECORDS[0], snapshot_id=store.snapshot_id)
        assert result.facts.recall_number == DEVELOPMENT_RECORDS[0]
        assert len(json.loads(seen[0]["input"])) == 4
        seen = []
        with client_for([(json.dumps(group_c_proposal(Source(), "F-0536-2021")), "completed")], seen) as client:
            result = interpret_group_c(store, client, Budget(tmp_path / "c_usage.sqlite"),
                                       recall_number="F-0536-2021", snapshot_id=store.snapshot_id)
        assert result.base.facts.recall_number == "F-0536-2021"
        assert len(json.loads(seen[0]["input"])) == 4


def test_paid_cli_can_select_exact_sqlite_store_offline(tmp_path, monkeypatch, capsys):
    path = tmp_path / "fda.sqlite"
    build_fda_store(path)
    seen = []
    monkeypatch.setenv("OPENAI_API_KEY", "offline-test-key")
    with client_for([(json.dumps(a_b_proposal(0)), "completed")], seen) as client:
        monkeypatch.setattr("interpreter.OpenAI", lambda **kwargs: client)
        assert main(["--recall", DEVELOPMENT_RECORDS[0], "--allow-paid-call",
                     "--fda-store", str(path), "--ledger", str(tmp_path / "usage.sqlite")]) == 0
    result, _ = json.JSONDecoder().raw_decode(capsys.readouterr().out)
    assert result["facts"]["recall_number"] == DEVELOPMENT_RECORDS[0]
    assert len(seen) == 1
