#!/usr/bin/env python3
"""Fallback: download remote rule-sets outside sing-box and configure initial_path.

Use this only if the dedicated Provider bootstrap can start but that proxy node still cannot
reach the rule-set URLs. An optional already-working external HTTP proxy may be supplied.

Examples:
  py -3 seed_rulesets.py windows-profile.json C:\\Users\\me\\Documents\\reF1nd-private\\rules
  py -3 seed_rulesets.py windows-profile.json C:\\Users\\me\\Documents\\reF1nd-private\\rules --proxy http://127.0.0.1:7891
"""
from __future__ import annotations
import argparse
import hashlib
from pathlib import Path
import re
from config_io import configure_console, ConfigError, read_json as load, save_profile, write_bytes
from config_model import as_list
from downloads import fetch_bytes


def expand_remote(rule_sets):
    seen = set()
    for entry in rule_sets:
        if not isinstance(entry, dict) or entry.get("type") != "remote":
            continue
        tags = as_list(entry.get("tag"))
        for tag in tags:
            if not isinstance(tag, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", tag):
                raise ConfigError("Remote rule-set tag 不可用作安全的 seed 文件名。")
            if tag in seen:
                raise ConfigError("Remote rule-set tag 重复。")
            seen.add(tag)
            url = entry.get("url", "").replace("{tag}", tag)
            if not url:
                raise SystemExit(f"Remote rule-set {tag} has no URL")
            yield entry, tag, url


def main():
    configure_console()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("profile")
    ap.add_argument("seed_dir")
    ap.add_argument("--proxy", help="already-working external HTTP proxy")
    ap.add_argument("--timeout", type=float, default=45.0)
    ap.add_argument("--no-download", action="store_true", help="only patch initial_path; require existing <tag>.srs files")
    args = ap.parse_args()

    profile = Path(args.profile).expanduser().resolve()
    data = load(profile)
    rule_sets = data.get("route", {}).get("rule_set", [])
    expanded = list(expand_remote(rule_sets))
    if not expanded:
        raise SystemExit("No remote rule-sets found")

    seed_dir = Path(args.seed_dir).expanduser().resolve()
    seed_dir.mkdir(parents=True, exist_ok=True)

    if not args.no_download:
        for _entry, tag, url in expanded:
            out = seed_dir / f"{tag}.srs"
            print(f"GET {tag}")
            body = fetch_bytes(url, headers={"User-Agent": "Mozilla/5.0 reF1nd-ruleset-seed/1.0"},
                               proxy=args.proxy, timeout=args.timeout)
            if body[:3] != b"SRS":
                raise SystemExit(f"{tag}: downloaded content is not an SRS binary")
            write_bytes(out, body)
            print(f"  -> {out}  sha256={hashlib.sha256(body).hexdigest()}")

    # Require every seed before mutating the profile.
    for _entry, tag, _url in expanded:
        f = seed_dir / f"{tag}.srs"
        if not f.is_file() or f.read_bytes()[:3] != b"SRS":
            raise SystemExit(f"Missing/invalid seed: {f}")

    # initial_path requires cache_file and conflicts with path.
    cache = data.setdefault("experimental", {}).setdefault("cache_file", {})
    cache["enabled"] = True

    # Preserve compact multi-tag definitions using {tag} where possible.
    for entry in rule_sets:
        if not isinstance(entry, dict) or entry.get("type") != "remote":
            continue
        entry.pop("path", None)
        tags = as_list(entry.get("tag"))
        if len(tags) > 1:
            entry["initial_path"] = str(seed_dir / "{tag}.srs")
        else:
            entry["initial_path"] = str(seed_dir / f"{tags[0]}.srs")

    backup = save_profile(profile, data, suffix=".bak-rulesets")
    if backup is None:
        print("Rule-set seed settings already applied.")
        return
    print(f"Patched {len(expanded)} rule-set tag(s) with initial_path.")
    print(f"Backup: {backup}")


if __name__ == "__main__":
    try:
        main()
    except ConfigError as exc:
        raise SystemExit(str(exc)) from None
