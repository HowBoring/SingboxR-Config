#!/usr/bin/env python3
"""Fix reF1nd 1.14 provider user_agent/http_client conflicts in a single JSON profile.

Usage:
  python fix_windows_profile.py path/to/windows-profile.json

The script:
- removes Provider.user_agent whenever http_client is configured;
- carries that User-Agent into the referenced/shared HTTP client headers;
- creates provider-specific HTTP clients if providers sharing one client request different UAs;
- removes detour=DIRECT from provider download HTTP clients;
- removes detour=DIRECT from typed DNS servers (direct dialing is already the default);
- replaces the bootstrap resolver with the Windows/system local resolver;
- pins provider-download DNS resolution to dns-bootstrap;
- writes a .bak backup before replacing the input file.
"""
from __future__ import annotations
import copy
import json
from pathlib import Path
import shutil
import sys


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python fix_windows_profile.py <windows-profile.json>", file=sys.stderr)
        return 2
    path = Path(sys.argv[1]).expanduser().resolve()
    data = load(path)
    providers = data.get("providers")
    clients = data.setdefault("http_clients", [])
    if not isinstance(providers, list) or not isinstance(clients, list):
        raise SystemExit("profile must contain providers[] and http_clients[]")

    by_tag = {c.get("tag"): c for c in clients if isinstance(c, dict) and c.get("tag")}
    changed = False
    assigned = {}  # shared client tag -> User-Agent

    for provider in providers:
        if not isinstance(provider, dict) or provider.get("type") != "remote":
            continue
        ua = provider.get("user_agent")
        hc = provider.get("http_client")
        if not ua or not hc:
            continue

        if isinstance(hc, dict):
            headers = hc.setdefault("headers", {})
            headers["User-Agent"] = ua
            provider.pop("user_agent", None)
            hc.pop("detour", None) if hc.get("detour") == "DIRECT" else None
            changed = True
            continue

        if not isinstance(hc, str):
            raise SystemExit(f"unsupported http_client on provider {provider.get('tag')}")

        client = by_tag.get(hc)
        if client is None:
            client = {"tag": hc}
            clients.append(client)
            by_tag[hc] = client

        prior = assigned.get(hc)
        existing = client.get("headers", {}).get("User-Agent") if isinstance(client.get("headers"), dict) else None
        effective = prior or existing
        if effective and effective != ua:
            # Preserve per-provider UA by cloning the shared client.
            base = copy.deepcopy(client)
            new_tag = f"{hc}-{provider.get('tag','provider')}"
            i = 2
            while new_tag in by_tag:
                new_tag = f"{hc}-{provider.get('tag','provider')}-{i}"
                i += 1
            base["tag"] = new_tag
            base.setdefault("headers", {})["User-Agent"] = ua
            if base.get("detour") == "DIRECT":
                base.pop("detour", None)
            clients.append(base)
            by_tag[new_tag] = base
            provider["http_client"] = new_tag
        else:
            client.setdefault("headers", {})["User-Agent"] = ua
            if client.get("detour") == "DIRECT":
                client.pop("detour", None)
            assigned[hc] = ua
        provider.pop("user_agent", None)
        changed = True

    # Also normalize the generated template even if user_agent was already removed manually.
    for client in clients:
        if isinstance(client, dict) and client.get("tag") == "provider-download" and client.get("detour") == "DIRECT":
            client.pop("detour", None)
            changed = True

    # New DNS transports use a dialer just like an outbound. With no detour they already
    # dial directly. reF1nd/sing-box rejects detouring such a DNS server to an otherwise
    # empty direct outbound as meaningless. Keep policy detours (PROXY/AI/etc.) intact.
    dns = data.get("dns")
    if isinstance(dns, dict):
        servers = dns.get("servers")
        if isinstance(servers, list):
            for server in servers:
                if not isinstance(server, dict):
                    continue
                if server.get("detour") == "DIRECT":
                    server.pop("detour", None)
                    changed = True
                # Provider initialization happens before TUN inbounds start in reF1nd 1.14.
                # Bootstrap with the platform/system resolver instead of hard-coding a public
                # DNS endpoint that may be unreachable on the current access network.
                if server.get("tag") == "dns-bootstrap":
                    desired = {
                        "type": "local",
                        "tag": "dns-bootstrap"
                    }
                    if server != desired:
                        server.clear(); server.update(desired); changed = True

    # Make the Provider bootstrap dependency explicit instead of relying only on
    # route.default_domain_resolver inheritance. HTTP Client supports Dial Fields.
    for client in clients:
        if isinstance(client, dict) and client.get("tag") == "provider-download":
            if client.get("domain_resolver") != "dns-bootstrap":
                client["domain_resolver"] = "dns-bootstrap"
                changed = True

    if not changed:
        print("No conflicting provider user_agent/http_client settings found.")
        return 0

    backup = path.with_suffix(path.suffix + ".bak")
    shutil.copy2(path, backup)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Fixed: {path}")
    print(f"Backup: {backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
