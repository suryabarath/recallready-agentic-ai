"""Explicit checks for the private-data A1-to-A2 demonstration.

The filename deliberately keeps this outside default pytest discovery. When
invoked directly, missing development data is a failure rather than a skip.
"""

import hashlib
import json
from pathlib import Path

import pytest

from a2_development_demo import DEMO_CASES, create_demo
from case_state import CaseState


DEVELOPMENT_PACKAGE = (
    Path(__file__).resolve().parents[1] / "runtime" / "a2_development_18_v1"
)


def test_demo_saves_three_complete_validated_routes(tmp_path):
    output = tmp_path / "demo"
    summary = create_demo(DEVELOPMENT_PACKAGE, output)
    assert summary["network_mode"].startswith("simulated")
    assert {case["route"] for case in summary["cases"]} == set(DEMO_CASES)
    expected = {
        "matched": ("a2_completed", "matched", 1),
        "no_match": ("a2_completed", "no_match", 0),
        "human_review": ("human_review", "not_run_requires_A1_review", 0),
    }
    for item in summary["cases"]:
        state_path = output / item["state_file"]
        state = CaseState.model_validate_json(state_path.read_text())
        assert (item["case_status"], item["a2_status"], item["finding_count"]) == expected[item["route"]]
        assert state.recall_number == item["recall_number"]
        assert state.a1 is not None and state.a1.status == "validated"
        assert item["inventory_rows_supplied"] == 2
        assert item["simulated_qdrant_requests"] == item["simulated_openai_requests"] == 1
        if item["route"] == "human_review":
            assert state.a2 is None
        else:
            assert state.a2 is not None
    manifest = json.loads((output / "manifest.json").read_text())
    for name, digest in manifest["files"].items():
        assert hashlib.sha256((output / name).read_bytes()).hexdigest() == digest


def test_demo_refuses_to_overwrite_existing_output(tmp_path):
    output = tmp_path / "exists"
    output.mkdir()
    with pytest.raises(ValueError, match="Refusing to overwrite"):
        create_demo(tmp_path / "unused", output)
