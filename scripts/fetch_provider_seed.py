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
import json
from pathlib import Path
import urllib.request


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("profile")
    ap.add_argument("provider_tag")
    ap.add_argument("output")
    ap.add_argument("--proxy", help="already-working HTTP proxy, e.g. http://127.0.0.1:7891")
    ap.add_argument("--timeout", type=float, default=30.0)
    args = ap.parse_args()

    profile = json.loads(Path(args.profile).read_text(encoding="utf-8-sig"))
    provider = next((p for p in profile.get("providers", []) if p.get("tag") == args.provider_tag), None)
    if not provider or provider.get("type") != "remote" or not provider.get("url"):
        raise SystemExit("remote provider with URL not found")

    ua = provider.get("user_agent")
    hc = provider.get("http_client")
    clients = profile.get("http_clients", [])
    if not ua and isinstance(hc, str):
        c = next((x for x in clients if x.get("tag") == hc), None)
        if c:
            ua = (c.get("headers") or {}).get("User-Agent")
    ua = ua or "clash.meta"

    handlers = []
    if args.proxy:
        handlers.append(urllib.request.ProxyHandler({"http": args.proxy, "https": args.proxy}))
    else:
        # Explicitly avoid inheriting a broken/current process proxy when testing direct access.
        handlers.append(urllib.request.ProxyHandler({}))
    opener = urllib.request.build_opener(*handlers)
    req = urllib.request.Request(provider["url"], headers={"User-Agent": ua})
    with opener.open(req, timeout=args.timeout) as resp:
        body = resp.read(64 * 1024 * 1024 + 1)
        if len(body) > 64 * 1024 * 1024:
            raise SystemExit("subscription body exceeds 64 MiB safety limit")
        if not body:
            raise SystemExit("subscription response is empty")
    out = Path(args.output).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(body)
    print(f"Saved raw seed: {out} ({len(body)} bytes)")
    print("Keep this file private: it may contain node credentials.")


if __name__ == "__main__":
    main()
