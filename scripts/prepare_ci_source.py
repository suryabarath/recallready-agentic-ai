"""Restore only the approved FDA ZIP from a private Actions secret."""

import base64
import binascii
import hashlib
import os
from pathlib import Path


EXPECTED_SHA256 = "b1f55e7cc2b0ec37c29b87af31478230766b3ba9b45bd0db03c8c38c1bfe2f0e"
ARCHIVE_NAME = "RecallReady_Agent1_FDA_18_Starter.zip"


def restore_archive(encoded: str, destination: Path) -> None:
    """Verify before writing; preserve an existing destination byte for byte."""
    if not encoded.strip():
        raise ValueError("Required FDA_STARTER_ZIP_BASE64 secret is missing; source tests cannot run.")
    try:
        payload = base64.b64decode("".join(encoded.split()), validate=True)
    except (ValueError, binascii.Error):
        raise ValueError("FDA source secret is not valid base64.") from None
    if hashlib.sha256(payload).hexdigest() != EXPECTED_SHA256:
        raise ValueError("FDA source checksum differs from the approved starter ZIP.")
    destination = Path(destination)
    if destination.exists():
        if hashlib.sha256(destination.read_bytes()).hexdigest() != EXPECTED_SHA256:
            raise ValueError("Existing FDA source differs; refusing to overwrite it.")
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as output:
        output.write(payload)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    destination = root.parent / "project_reference" / ARCHIVE_NAME
    try:
        restore_archive(os.environ.get("FDA_STARTER_ZIP_BASE64", ""), destination)
    except (ValueError, OSError) as exc:
        raise SystemExit(str(exc)) from None
    print("FDA starter ZIP checksum verified; archive preserved without extraction.")


if __name__ == "__main__":
    main()
