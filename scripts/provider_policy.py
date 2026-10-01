"""Provider membership policy shared by synchronization and configuration validation."""
from __future__ import annotations

import hashlib
import re

from config_io import ConfigError

CLAUDE_PROVIDER = "Claude-Dedicated"
ORDINARY_GROUPS = ("AUTO", "HK", "TW", "JP", "SG", "US")
DEDICATED_GROUPS = ("CLAUDE", "MANUAL")


def sync_memberships(outbounds, providers):
    if CLAUDE_PROVIDER not in providers:
        raise ConfigError("必须保留 Claude-Dedicated。")
    normal = [tag for tag in providers if tag != CLAUDE_PROVIDER]
    if not normal:
        raise ConfigError("至少需要一家普通机场。")
    for item in outbounds:
        tag = item["tag"]
        if tag in ORDINARY_GROUPS:
            item["providers"] = list(normal)
        elif tag == "MANUAL":
            item["providers"] = normal + [CLAUDE_PROVIDER]
        elif tag == "CLAUDE":
            item["providers"] = [CLAUDE_PROVIDER]
        elif tag == "RULESET-BOOTSTRAP":
            selected = item.get("providers", [])
            if not selected or any(ref not in normal for ref in selected):
                item["providers"] = [normal[0]]
    return normal


def validate_membership(tag, entry):
    if CLAUDE_PROVIDER in entry.get("providers", []):
        if tag not in DEDICATED_GROUPS or entry.get("type") != "selector":
            raise ConfigError(f"Claude 专用 Provider 只允许进入 CLAUDE / MANUAL 手选组：{tag}。")
    if entry.get("use_all_providers"):
        raise ConfigError("本方案禁止 use_all_providers，避免专用节点进入自动节点池。")


def get_client(clients, tag):
    return next((c for c in clients if isinstance(c, dict) and c.get("tag") == tag), None)


def effective_ua(provider, clients):
    if provider.get("user_agent"):
        return provider["user_agent"]
    client = provider.get("http_client")
    if isinstance(client, str):
        client = get_client(clients, client)
    headers = client.get("headers", {}) if isinstance(client, dict) else {}
    for name, value in headers.items():
        if name.lower() == "user-agent" and value:
            return ", ".join(value) if isinstance(value, list) else value
    return "clash.meta"


def set_user_agent(client, value):
    headers = client.setdefault("headers", {})
    for key in list(headers):
        if key.lower() == "user-agent":
            del headers[key]
    headers["User-Agent"] = value


def download_headers(provider, clients):
    client = provider.get("http_client")
    if isinstance(client, str):
        client = get_client(clients, client)
    headers = dict(client.get("headers", {})) if isinstance(client, dict) else {}
    headers = {name: ", ".join(value) if isinstance(value, list) else value for name, value in headers.items()}
    wrapper = {"headers": headers}
    set_user_agent(wrapper, effective_ua(provider, clients))
    return headers


def safe_tag(tag):
    result = re.sub(r"[^A-Za-z0-9_.-]+", "-", tag).strip("-") or "provider"
    # Different non-ASCII/provider tags must not overwrite each other's update clients.
    if result != tag:
        result += "-" + hashlib.sha256(tag.encode()).hexdigest()[:10]
    return result
