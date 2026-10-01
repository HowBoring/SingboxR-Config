#!/usr/bin/env python3
"""Patch a reF1nd 1.14 Windows profile so initial remote rule-set downloads use
one already-seeded Provider directly instead of PROXY -> AUTO -> REJECT.

Usage:
  py -3 fix_ruleset_bootstrap.py windows-profile.json YunTu

The selected Provider should already be able to cold-start from cache/initial_path.
"""
from __future__ import annotations
import argparse
from pathlib import Path
from config_io import ConfigError, read_json as load, save_profile
from provider_policy import CLAUDE_PROVIDER

BOOTSTRAP_TAG = "RULESET-BOOTSTRAP"
RULESET_CLIENT = "ruleset-download"


def find_tag(items, tag):
    return next((x for x in items if isinstance(x, dict) and x.get("tag") == tag), None)


def patch(profile: Path, provider_tag: str):
    data = load(profile)
    providers = data.get("providers", [])
    outbounds = data.setdefault("outbounds", [])
    clients = data.setdefault("http_clients", [])
    route = data.get("route", {})
    rule_sets = route.get("rule_set", [])

    provider = find_tag(providers, provider_tag)
    if provider is None:
        raise SystemExit(f"Provider not found: {provider_tag}")
    if provider_tag == CLAUDE_PROVIDER:
        raise ConfigError("规则下载组不使用 Claude 专用 Provider；请选择普通机场。")
    if provider.get("type") not in ("remote", "local", "inline"):
        raise SystemExit(f"Unsupported Provider type for bootstrap: {provider.get('type')}")

    # The current error happens only after providers have started, but make the intended
    # cold-start dependency explicit for remote providers.
    if provider.get("type") == "remote" and not provider.get("initial_path"):
        print(
            f"WARNING: remote Provider {provider_tag!r} has no initial_path. "
            "This patch assumes it already loads successfully from cache or direct download."
        )

    # Provider-only selector: no static REJECT and no default. Before provider load the core
    # may have its internal Compatible placeholder, but Provider Start happens before Router
    # / remote rule-set Start. The provider callback replaces membership before this client
    # is used for rule-set cold-start downloads.
    bootstrap = {
        "type": "selector",
        "tag": BOOTSTRAP_TAG,
        "providers": [provider_tag],
        "interrupt_exist_connections": False,
    }
    existing = find_tag(outbounds, BOOTSTRAP_TAG)
    if existing is None:
        # Put it before user-facing groups only for readability; references are tag-based.
        outbounds.insert(0, bootstrap)
    else:
        existing.clear()
        existing.update(bootstrap)

    client = find_tag(clients, RULESET_CLIENT)
    if client is None:
        client = {"tag": RULESET_CLIENT}
        clients.append(client)
    client["detour"] = BOOTSTRAP_TAG
    # When detouring through a proxy node, the outbound path handles the destination.
    # Keep the client minimal and avoid bootstrap resolver/bind ambiguity.
    for key in (
        "domain_resolver",
        "domain_strategy",
        "bind_interface",
        "inet4_bind_address",
        "inet6_bind_address",
        "routing_mark",
    ):
        client.pop(key, None)

    # Make all remote rule-sets use the dedicated client. Inline/local sets are untouched.
    changed = 0
    for rs in rule_sets:
        if isinstance(rs, dict) and rs.get("type") == "remote":
            rs["http_client"] = RULESET_CLIENT
            rs.pop("download_detour", None)
            changed += 1

    if changed == 0:
        raise SystemExit("No remote rule-sets found in route.rule_set")

    backup = save_profile(profile, data)
    if backup is None:
        print("Rule-set bootstrap settings already applied.")
        return
    print(f"Patched {changed} remote rule-set definition(s).")
    print(f"Rule-set cold-start path: {RULESET_CLIENT} -> {BOOTSTRAP_TAG} -> {provider_tag}/*")
    print(f"Backup: {backup}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("profile")
    ap.add_argument("provider_tag", help="Provider that is already cold-startable, e.g. YunTu")
    args = ap.parse_args()
    patch(Path(args.profile).expanduser().resolve(), args.provider_tag)


if __name__ == "__main__":
    try:
        main()
    except ConfigError as exc:
        raise SystemExit(str(exc)) from None
