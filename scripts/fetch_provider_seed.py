#!/usr/bin/env python3
"""Fetch one Provider's raw subscription body from a profile into a seed file.

This helper reads the secret URL from the local profile so it does not need to be pasted
into the shell command. Optional --proxy accepts an already-working HTTP proxy.

Examples:
  py -3 fetch_provider_seed.py windows-profile.json YunTu YunTu.seed
  py -3 fetch_provider_seed.py windows-profile.json YunTu YunTu.seed --proxy http://127.0.0.1:7891
"""
from __future__ import annotations
import argparse
from pathlib import Path
from config_io import configure_console, ConfigError, read_json, write_bytes
from downloads import fetch_bytes
from provider_policy import download_headers


def fetch(profile_path, provider_tag, output, proxy=None, timeout=30.0):
    out = Path(output).expanduser().resolve()
    if out == profile_path.resolve():
        raise ConfigError("seed 输出不能覆盖输入 Profile。")
    profile = read_json(profile_path)
    provider = next((p for p in profile.get("providers", []) if p.get("tag") == provider_tag), None)
    if not provider or provider.get("type") != "remote" or not provider.get("url"):
        raise ConfigError("remote provider with URL not found")
    headers = download_headers(provider, profile.get("http_clients", []))
    body = fetch_bytes(provider["url"], headers=headers, proxy=proxy, timeout=timeout)
    write_bytes(out, body, private=True)
    print(f"Saved raw seed: {out} ({len(body)} bytes)")
    print("Keep this file private: it may contain node credentials.")
    return out


def main():
    configure_console()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("profile")
    ap.add_argument("provider_tag")
    ap.add_argument("output")
    ap.add_argument("--proxy", help="already-working HTTP proxy, e.g. http://127.0.0.1:7891")
    ap.add_argument("--timeout", type=float, default=30.0)
    args = ap.parse_args()

    fetch(Path(args.profile).expanduser().resolve(), args.provider_tag, args.output, args.proxy, args.timeout)


if __name__ == "__main__":
    try:
        main()
    except ConfigError as exc:
        raise SystemExit(str(exc)) from None
