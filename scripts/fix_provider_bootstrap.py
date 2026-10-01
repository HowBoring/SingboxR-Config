#!/usr/bin/env python3
"""Patch one reF1nd remote Provider to cold-start from initial_path, then update via PROXY.

Usage:
  py -3 fix_provider_bootstrap.py windows-profile.json YunTu C:\\path\\to\\YunTu.seed

The seed should be the RAW subscription response downloaded from the Provider URL
(using the same User-Agent if required). It is not converted by this script.
"""
from __future__ import annotations
import argparse
import copy
import json
from pathlib import Path
import re
import shutil
import sys


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def safe_tag(tag: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_.-]+", "-", tag).strip("-")
    return s or "provider"


def get_client(clients, tag):
    for c in clients:
        if isinstance(c, dict) and c.get("tag") == tag:
            return c
    return None


def effective_ua(provider, clients):
    if provider.get("user_agent"):
        return provider["user_agent"]
    hc = provider.get("http_client")
    if isinstance(hc, dict):
        headers = hc.get("headers") or {}
        return headers.get("User-Agent") or headers.get("user-agent") or "clash.meta"
    if isinstance(hc, str):
        c = get_client(clients, hc)
        if c:
            headers = c.get("headers") or {}
            return headers.get("User-Agent") or headers.get("user-agent") or "clash.meta"
    return "clash.meta"


def patch(profile: Path, provider_tag: str, seed_path: str, detour: str = "PROXY"):
    data = load(profile)
    providers = data.get("providers")
    clients = data.setdefault("http_clients", [])
    if not isinstance(providers, list) or not isinstance(clients, list):
        raise SystemExit("profile must contain providers[] and http_clients[]")

    provider = next((p for p in providers if isinstance(p, dict) and p.get("tag") == provider_tag), None)
    if provider is None:
        raise SystemExit(f"provider not found: {provider_tag}")
    if provider.get("type") != "remote":
        raise SystemExit(f"provider {provider_tag} is not type=remote")

    seed = Path(seed_path).expanduser()
    if not seed.is_absolute():
        seed = seed.resolve()
    if not seed.is_file() or seed.stat().st_size == 0:
        raise SystemExit(f"seed file does not exist or is empty: {seed}")

    # initial_path explicitly requires cache_file in reF1nd 1.14.
    experimental = data.setdefault("experimental", {})
    cache = experimental.setdefault("cache_file", {})
    cache["enabled"] = True

    ua = effective_ua(provider, clients)

    # Use initial_path, not path. initial_path accepts initial provider content and is
    # intentionally separate from the persistent cache path.
    provider.pop("path", None)
    provider["initial_path"] = str(seed)
    provider.pop("user_agent", None)

    # Clone the current Provider HTTP client where possible so HTTP headers/options are kept,
    # then make this Provider's refresh go through an already-started PROXY group.
    old = provider.get("http_client")
    base = {}
    if isinstance(old, str):
        existing = get_client(clients, old)
        if existing:
            base = copy.deepcopy(existing)
    elif isinstance(old, dict):
        base = copy.deepcopy(old)

    new_tag = f"provider-update-{safe_tag(provider_tag)}"
    # Replace any previous patch client with the same tag.
    clients[:] = [c for c in clients if not (isinstance(c, dict) and c.get("tag") == new_tag)]
    base["tag"] = new_tag
    base["detour"] = detour
    # With detour enabled, socket-level resolver/bind fields are not needed; the selected
    # outbound handles the destination. Remove bootstrap-only dial fields to avoid ambiguity.
    base.pop("domain_resolver", None)
    base.pop("domain_strategy", None)
    headers = base.setdefault("headers", {})
    headers["User-Agent"] = ua
    clients.append(base)
    provider["http_client"] = new_tag

    # Keep a reasonably infrequent normal refresh. Do not make this less than the core minimum.
    provider.setdefault("update_interval", "24h")

    backup = profile.with_suffix(profile.suffix + ".bak")
    shutil.copy2(profile, backup)
    profile.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Patched provider: {provider_tag}")
    print(f"initial_path: {seed}")
    print(f"refresh detour: {detour}")
    print(f"backup: {backup}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("profile")
    ap.add_argument("provider_tag")
    ap.add_argument("seed_path")
    ap.add_argument("--detour", default="PROXY", help="existing outbound/group used for later remote refreshes")
    args = ap.parse_args()
    patch(Path(args.profile).expanduser().resolve(), args.provider_tag, args.seed_path, args.detour)


if __name__ == "__main__":
    main()
