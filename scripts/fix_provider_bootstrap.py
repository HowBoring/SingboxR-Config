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
from pathlib import Path
from config_io import configure_console, ConfigError, read_json as load, save_profile
from provider_policy import effective_ua, get_client, safe_tag, set_user_agent


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
    if not any(out.get("tag") == detour for out in data.get("outbounds", [])):
        raise ConfigError("Provider refresh detour 引用了不存在的出站。")

    seed = Path(seed_path).expanduser().resolve()
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
    set_user_agent(base, ua)
    clients.append(base)
    provider["http_client"] = new_tag

    # Keep a reasonably infrequent normal refresh. Do not make this less than the core minimum.
    provider.setdefault("update_interval", "24h")

    backup = save_profile(profile, data)
    if backup is None:
        print("Provider bootstrap settings already applied.")
        return
    print(f"Patched provider: {provider_tag}")
    print(f"initial_path: {seed}")
    print(f"refresh detour: {detour}")
    print(f"backup: {backup}")


def main():
    configure_console()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("profile")
    ap.add_argument("provider_tag")
    ap.add_argument("seed_path")
    ap.add_argument("--detour", default="PROXY", help="existing outbound/group used for later remote refreshes")
    args = ap.parse_args()
    patch(Path(args.profile).expanduser().resolve(), args.provider_tag, args.seed_path, args.detour)


if __name__ == "__main__":
    try:
        main()
    except ConfigError as exc:
        raise SystemExit(str(exc)) from None
