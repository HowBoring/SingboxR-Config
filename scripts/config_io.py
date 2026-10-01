"""Shared strict JSON and atomic file writes; never include file contents in errors."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile


class ConfigError(Exception):
    pass


def unique_keys(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=unique_keys)
    except (OSError, ValueError) as exc:
        raise ConfigError(f"无法读取 JSON：{path.name} ({type(exc).__name__})") from None


def write_bytes(path: Path, data: bytes, private=False):
    """Replace only after a complete write; set permissions before publishing the file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".config-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        mode = 0o600 if private else (path.stat().st_mode & 0o777 if path.exists() else 0o644)
        Path(temporary).chmod(mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_json(path: Path, value, private=False):
    data = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    write_bytes(path, data, private=private)


def save_profile(path: Path, value, suffix=".bak"):
    """Keep each migration backup and skip writes when the profile is unchanged."""
    if read_json(path) == value:
        return None
    original = path.read_bytes()
    index = 1
    while True:
        ending = suffix if index == 1 else f"{suffix}-{index}"
        backup = path.with_suffix(path.suffix + ending)
        try:
            fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            index += 1
            continue
        with os.fdopen(fd, "wb") as stream:
            stream.write(original)
        break
    write_json(path, value, private=True)
    return backup
