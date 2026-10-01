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
import json
from pathlib import Path
import shutil


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("profile")
    args = ap.parse_args()
    profile = Path(args.profile).expanduser().resolve()
    data = json.loads(profile.read_text(encoding="utf-8-sig"))

    changed = []
    for inbound in data.get("inbounds", []):
        if isinstance(inbound, dict) and inbound.get("type") == "tun":
            old = inbound.get("stack", "<unset>")
            inbound["stack"] = "system"
            changed.append((inbound.get("tag", "tun"), old))

    if not changed:
        raise SystemExit("No TUN inbound found")

    backup = profile.with_suffix(profile.suffix + ".bak-tun-stack")
    shutil.copy2(profile, backup)
    profile.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for tag, old in changed:
        print(f"Patched TUN {tag}: stack {old!r} -> 'system'")
    print(f"Backup: {backup}")


if __name__ == "__main__":
    main()
