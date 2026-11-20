"""Real SQLite transactions with injected storage failures; no live requests."""

import json
import sqlite3

import pytest

from a1_service import A1RunError, run_a1
from fda_store import FDAStore, StoreError, build_fda_store
from interpreter import Budget, InterpretationError, main
from source import GROUP_A, GROUP_C
from test_a1_service import fixture_output, points_for, retriever_for, store
from test_interpreter import client_for, proposal


def track_connections(monkeypatch, *, fail_sql=None, after_execute=False):
    original = sqlite3.connect
    connections = []

    class Connection(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            fail = fail_sql is not None and sql.startswith(fail_sql)
            if fail and not after_execute:
                raise sqlite3.OperationalError("simulated storage failure")
            result = super().execute(sql, *args, **kwargs)
            if fail:
                raise sqlite3.OperationalError("simulated failure after SQL execution")
            return result

    def connect(*args, **kwargs):
        connection = original(*args, factory=Connection, **kwargs)
        connections.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, "connect", connect)
    return connections


def assert_closed(connections):
    assert connections
    for connection in connections:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            sqlite3.Connection.execute(connection, "SELECT 1")


def test_budget_closes_every_successful_connection(tmp_path, monkeypatch):
    connections = track_connections(monkeypatch)
    budget = Budget(tmp_path / "usage.sqlite")
    call_id = budget.reserve(100)
    assert budget.summary()[0]["state"] == "reserved"
    from types import SimpleNamespace
    usage = SimpleNamespace(input_tokens=10, output_tokens=10, output_tokens_details=None)
    budget.settle(call_id, usage, "offline-response", GROUP_A[0])
    assert budget.summary()[0]["accounted_usd"] == 0.000006
    assert_closed(connections)


@pytest.mark.parametrize("sql,operation,expected", [
    ("CREATE", "initialize", "initialization failed"),
    ("INSERT", "reserve", "reservation failed"),
    ("SELECT", "summary", "summary unavailable"),
])
def test_budget_closes_connections_on_database_error(tmp_path, monkeypatch, sql, operation, expected):
    path = tmp_path / "usage.sqlite"
    budget = Budget(path)
    connections = track_connections(monkeypatch, fail_sql=sql)
    with pytest.raises(InterpretationError, match=expected):
        if operation == "initialize": Budget(path)
        elif operation == "reserve": budget.reserve(100)
        else: budget.summary()
    assert_closed(connections)


@pytest.mark.parametrize("failure", ["connect", "mkdir"])
def test_budget_setup_failure_is_explicit(tmp_path, monkeypatch, failure):
    if failure == "connect":
        def unavailable(*args, **kwargs):
            raise sqlite3.OperationalError("cannot open ledger")
        monkeypatch.setattr(sqlite3, "connect", unavailable)
    else:
        from pathlib import Path
        def unavailable(*args, **kwargs):
            raise PermissionError("cannot create directory")
        monkeypatch.setattr(Path, "mkdir", unavailable)
    with pytest.raises(InterpretationError, match="initialization failed; no new request sent"):
        Budget(tmp_path / "usage.sqlite")


@pytest.mark.parametrize("recall", [GROUP_A[0], GROUP_C[0]])
@pytest.mark.parametrize("operation", ["reserve", "settle"])
def test_service_storage_failure_preserves_accounting_and_resource_ownership(
        store, tmp_path, monkeypatch, recall, operation):
    budget = Budget(tmp_path / "usage.sqlite")
    cloud_calls, model_calls = [], []
    retriever = retriever_for(store, points_for(store, recall), cloud_calls)
    output, _ = fixture_output(store, recall)
    connections = track_connections(monkeypatch,
                                    fail_sql="INSERT" if operation == "reserve" else "UPDATE",
                                    after_execute=True)
    with client_for([(json.dumps(output), "completed")], model_calls) as client:
        expected = "no new request sent" if operation == "reserve" else "request may already be charged"
        with pytest.raises(A1RunError, match=expected):
            run_a1(store, retriever, client, budget,
                    recall_number=recall, snapshot_id=store.snapshot_id)
        assert not client.is_closed()
        assert store.lookup(recall, snapshot_id=store.snapshot_id)
    assert len(model_calls) == (0 if operation == "reserve" else 1)
    assert len(cloud_calls) == 1
    entries = budget.summary()
    if operation == "reserve":
        assert entries == []  # Failed insert was rolled back.
    else:
        assert len(entries) == 1 and entries[0]["state"] == "reserved"
        assert entries[0]["accounted_usd"] > 0  # Failed settlement did not release reservation.
    assert_closed(connections)


def test_service_source_database_failure_is_normalized(store, tmp_path, monkeypatch):
    cloud_calls, model_calls = [], []
    retriever = retriever_for(store, [], cloud_calls)
    budget = Budget(tmp_path / "usage.sqlite")
    def unavailable(*args, **kwargs):
        raise sqlite3.OperationalError("private storage diagnostic")
    monkeypatch.setattr(store, "lookup", unavailable)
    with client_for([], model_calls) as client:
        with pytest.raises(A1RunError, match="preflight failed: local storage unavailable") as error:
            run_a1(store, retriever, client, budget,
                    recall_number=GROUP_A[0], snapshot_id=store.snapshot_id)
    assert "private storage diagnostic" not in str(error.value)
    assert cloud_calls == model_calls == budget.summary() == []


@pytest.mark.parametrize("failure", ["manifest", "schema"])
def test_store_constructor_closes_connection_when_validation_fails(tmp_path, monkeypatch, failure):
    path = tmp_path / "fda.sqlite"
    build_fda_store(path)
    connection = sqlite3.connect(path)
    try:
        if failure == "manifest": connection.execute("DELETE FROM manifest")
        else: connection.execute("DROP TABLE manifest")
        connection.commit()
    finally:
        connection.close()
    connections = track_connections(monkeypatch)
    with pytest.raises((StoreError, sqlite3.Error)):
        FDAStore(path)
    assert_closed(connections)


@pytest.mark.parametrize("failure", ["summary", "invalid-budget", "client-setup"])
def test_cli_closes_owned_resources_on_failure(tmp_path, monkeypatch, capsys, failure):
    path = tmp_path / "fda.sqlite"
    build_fda_store(path)
    closed = []
    original_close = FDAStore.close
    def close_store(self):
        closed.append(self)
        original_close(self)
    monkeypatch.setattr(FDAStore, "close", close_store)
    monkeypatch.setenv("OPENAI_API_KEY", "offline-key")
    seen = []
    client = client_for([(json.dumps(proposal()), "completed")], seen)
    def make_client(**kwargs):
        if failure == "client-setup": raise RuntimeError("simulated setup failure")
        return client
    monkeypatch.setattr("interpreter.OpenAI", make_client)
    if failure == "summary":
        def unavailable(self):
            raise InterpretationError("Usage ledger summary unavailable; do not infer zero usage")
        monkeypatch.setattr(Budget, "summary", unavailable)
    args = ["--recall", GROUP_A[0], "--allow-paid-call", "--fda-store", str(path),
            "--ledger", str(tmp_path / "usage.sqlite")]
    try:
        if failure == "summary":
            assert main(args) == 1
            assert "usage_ledger_error" in capsys.readouterr().out
            assert client.is_closed() and len(seen) == 1
        elif failure == "invalid-budget":
            with pytest.raises(SystemExit): main(args + ["--budget-usd", "0"])
            assert seen == []
        else:
            with pytest.raises(RuntimeError, match="setup failure"): main(args)
            assert seen == []
        assert len(closed) == 1
        with pytest.raises(sqlite3.ProgrammingError): closed[0]._db.execute("SELECT 1")
    finally:
        client.close()
