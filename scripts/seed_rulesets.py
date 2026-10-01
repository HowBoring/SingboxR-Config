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
import json
from pathlib import Path
import shutil
import urllib.request


def as_list(v):
    return v if isinstance(v, list) else [v]


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def expand_remote(rule_sets):
    for entry in rule_sets:
        if not isinstance(entry, dict) or entry.get("type") != "remote":
            continue
        tags = as_list(entry.get("tag"))
        for tag in tags:
            if not isinstance(tag, str) or not tag:
                raise SystemExit("Remote rule-set has invalid tag")
            url = entry.get("url", "").replace("{tag}", tag)
            if not url:
                raise SystemExit(f"Remote rule-set {tag} has no URL")
            yield entry, tag, url


def main():
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
        if args.proxy:
            handler = urllib.request.ProxyHandler({"http": args.proxy, "https": args.proxy})
        else:
            # Explicit direct attempt: don't accidentally point at the failing sing-box profile.
            handler = urllib.request.ProxyHandler({})
        opener = urllib.request.build_opener(handler)
        seen = set()
        for _entry, tag, url in expanded:
            if tag in seen:
                continue
            seen.add(tag)
            out = seed_dir / f"{tag}.srs"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 reF1nd-ruleset-seed/1.0"})
            print(f"GET {tag}: {url}")
            with opener.open(req, timeout=args.timeout) as resp:
                body = resp.read(64 * 1024 * 1024 + 1)
            if len(body) > 64 * 1024 * 1024:
                raise SystemExit(f"{tag}: response exceeds 64 MiB")
            if body[:3] != b"SRS":
                raise SystemExit(f"{tag}: downloaded content is not an SRS binary")
            out.write_bytes(body)
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

    backup = profile.with_suffix(profile.suffix + ".bak-rulesets")
    shutil.copy2(profile, backup)
    profile.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Patched {len(expanded)} rule-set tag(s) with initial_path.")
    print(f"Backup: {backup}")


if __name__ == "__main__":
    main()
