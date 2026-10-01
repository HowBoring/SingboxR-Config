#!/usr/bin/env python3
"""Patch reF1nd Windows profile TUN inbounds to use the system stack.

Use this when the Desktop core was built without the `with_gvisor` build tag and
startup fails with:
  gVisor is not included in this build, rebuild with -tags with_gvisor

Usage:
  py -3 fix_tun_stack.py windows-profile.json
"""
from __future__ import annotations
import argparse
from pathlib import Path
from config_io import configure_console, ConfigError, read_json, save_profile


def patch(profile: Path):
    data = read_json(profile)

    changed = []
    for inbound in data.get("inbounds", []):
        if isinstance(inbound, dict) and inbound.get("type") == "tun":
            old = inbound.get("stack", "<unset>")
            inbound["stack"] = "system"
            changed.append((inbound.get("tag", "tun"), old))

    if not changed:
        raise SystemExit("No TUN inbound found")

    backup = save_profile(profile, data, suffix=".bak-tun-stack")
    if backup is None:
        print("TUN system stack already applied.")
        return
    for tag, old in changed:
        print(f"Patched TUN {tag}: stack {old!r} -> 'system'")
    print(f"Backup: {backup}")


def main():
    configure_console()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("profile")
    args = ap.parse_args()
    patch(Path(args.profile).expanduser().resolve())


if __name__ == "__main__":
    try:
        main()
    except ConfigError as exc:
        raise SystemExit(str(exc)) from None
