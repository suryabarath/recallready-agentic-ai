"""Actual ZIP verification and exclusive restoration for CI, without extraction."""

import base64
import hashlib
import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest

from source import DEFAULT_ARCHIVE


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "prepare_ci_source.py"
spec = importlib.util.spec_from_file_location("prepare_ci_source", SCRIPT)
ci_source = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci_source)


def encoded_archive():
    return base64.b64encode(DEFAULT_ARCHIVE.read_bytes()).decode("ascii")


def test_restore_exact_zip_with_private_permissions(tmp_path):
    target = tmp_path / "reference" / ci_source.ARCHIVE_NAME
    ci_source.restore_archive(encoded_archive(), target)
    assert target.read_bytes() == DEFAULT_ARCHIVE.read_bytes()
    assert hashlib.sha256(target.read_bytes()).hexdigest() == ci_source.EXPECTED_SHA256
    assert target.stat().st_mode & 0o777 == 0o600
    assert list(target.parent.iterdir()) == [target]


def test_reuse_identical_destination_without_rewriting(tmp_path):
    target = tmp_path / ci_source.ARCHIVE_NAME
    ci_source.restore_archive(encoded_archive(), target)
    before = target.stat().st_mtime_ns
    ci_source.restore_archive(encoded_archive(), target)
    assert target.stat().st_mtime_ns == before


@pytest.mark.parametrize("encoded", ["", " \n", "not-valid-@@base64", "c3Vic3RpdHV0ZWQgc291cmNl"])
def test_reject_missing_or_invalid_source_before_writing(tmp_path, encoded):
    target = tmp_path / "not-created" / ci_source.ARCHIVE_NAME
    with pytest.raises(ValueError):
        ci_source.restore_archive(encoded, target)
    assert not target.parent.exists()


def test_refuse_to_overwrite_different_existing_source(tmp_path):
    target = tmp_path / ci_source.ARCHIVE_NAME
    target.write_bytes(b"preserve this existing file")
    with pytest.raises(ValueError, match="refusing to overwrite"):
        ci_source.restore_archive(encoded_archive(), target)
    assert target.read_bytes() == b"preserve this existing file"


def test_cli_missing_secret_fails_clearly_without_source_text():
    import os
    env = dict(os.environ, FDA_STARTER_ZIP_BASE64="")
    result = subprocess.run([sys.executable, "-B", str(SCRIPT)], env=env,
                            text=True, capture_output=True)
    assert result.returncode != 0
    assert "secret is missing" in result.stderr
    assert not result.stdout
