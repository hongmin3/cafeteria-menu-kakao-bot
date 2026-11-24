from __future__ import annotations

import os
from pathlib import Path
from tempfile import NamedTemporaryFile


def write_bytes(path: Path, content: bytes) -> None:
    """Write a sibling file and expose it only after its contents are complete."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with NamedTemporaryFile(dir=path.parent, prefix=".menubot-", suffix=".tmp", delete=False) as temp:
            temp_path = Path(temp.name)
            temp.write(content)
            temp.flush()
            os.fsync(temp.fileno())
        temp_path.replace(path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
