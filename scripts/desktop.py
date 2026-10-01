"""Pure Windows target transformation; no CLI parsing or implicit private input."""
from __future__ import annotations

import copy
from config_io import ConfigError, read_json
from config_model import as_list, inside_root
from provider_policy import sync_memberships
from validation import lint

def _inline_local_provider(provider, root):
    """Convert a native sing-box JSON local provider to an inline provider for single-file targets."""
    path = inside_root(root, provider.get("path", ""))
    if not path.is_file():
        raise ConfigError(f"Windows 单文件构建找不到本地 Provider 文件：{provider.get('tag', '(unknown)')}")
    try:
        document = read_json(path)
    except ConfigError:
        raise ConfigError(
            f"Windows 单文件构建只能自动内联原生 sing-box JSON 本地 Provider：{provider.get('tag', '(unknown)')}。"
            "若当前文件是 Clash/YAML 或分享链接，请改用 remote Provider，或先转换为包含 outbounds/endpoints 的 sing-box JSON。"
        ) from None
    outbounds = document.get("outbounds", [])
    endpoints = document.get("endpoints", [])
    if not isinstance(outbounds, list) or not isinstance(endpoints, list) or (not outbounds and not endpoints):
        raise ConfigError(
            f"本地 Provider {provider.get('tag', '(unknown)')} 没有可内联的 outbounds/endpoints。"
        )
    # These options exist on local providers but not inline providers in the pinned core.
    # Fail explicitly instead of silently dropping TLS/dialer changes while packing.
    if any(provider.get(key) for key in ("override_dialer", "override_tls", "override_anytls")):
        raise ConfigError("本地 Provider 的 override_* 不能直接内联；请将覆盖字段写入原生节点后再构建。")
    if any(not isinstance(node, dict) or not isinstance(node.get("type"), str) for node in outbounds + endpoints):
        raise ConfigError("本地 Provider 的节点必须是带 type 的 JSON 对象。")
    outbounds = [node for node in outbounds if node.get("type") not in
                 ("direct", "block", "dns", "selector", "urltest", "pass")]
    if not outbounds and not endpoints:
        raise ConfigError("本地 Provider 过滤后没有可内联的代理节点。")
    inline = {
        "type": "inline",
        "tag": provider["tag"],
        "outbounds": outbounds,
        "endpoints": endpoints,
    }
    if provider.get("health_check"):
        inline["health_check"] = copy.deepcopy(provider["health_check"])
    return inline

def pack_windows_profile(config, root, template=False, keep_seed_paths=False):
    """Build a self-contained single JSON profile for reF1nd sing-box-for-desktop on Windows."""
    # Validate source fragments first; template builds may keep Provider/API placeholders.
    result = copy.deepcopy(config)
    if template:
        sync_memberships(result["outbounds"], {p["tag"]: p for p in result["providers"]})
    lint(result, root, template=template)

    # Desktop profile content is a single JSON document. Inline project-local rule-sets,
    # and remove CLI-only initial seed paths from remote rule-sets.
    packed_rule_sets = []
    for entry in result["route"]["rule_set"]:
        kind = entry.get("type")
        if kind == "local":
            tags = as_list(entry.get("tag"))
            if len(tags) != 1:
                raise ConfigError("本地 rule-set 转 inline 时必须只有一个 tag。")
            source = read_json(inside_root(root, entry["path"]))
            if source.get("version") != 3 or not isinstance(source.get("rules"), list):
                raise ConfigError(f"本地规则集格式错误：{tags[0]}")
            rules = copy.deepcopy(source["rules"])
            if not rules:
                rules = [{"domain": ["ref1nd-empty-rule-set.invalid"]}]
            packed_rule_sets.append({"type": "inline", "tag": tags[0], "rules": rules})
        elif kind == "remote":
            packed = copy.deepcopy(entry)
            if not keep_seed_paths:
                packed.pop("initial_path", None)
            packed.pop("path", None)
            packed_rule_sets.append(packed)
        else:
            packed_rule_sets.append(copy.deepcopy(entry))
    result["route"]["rule_set"] = packed_rule_sets

    # Remote Provider content is cached by cache.db in the Desktop daemon; keeping the CLI
    # ./state/providers paths would make the profile depend on an external project directory.
    packed_providers = []
    for provider in result["providers"]:
        if provider.get("type") == "remote":
            packed = copy.deepcopy(provider)
            packed.pop("path", None)
            if not keep_seed_paths:
                packed.pop("initial_path", None)
            packed_providers.append(packed)
        elif provider.get("type") == "local":
            packed_providers.append(_inline_local_provider(provider, root))
        elif provider.get("type") == "inline":
            packed_providers.append(copy.deepcopy(provider))
        else:
            raise ConfigError(f"Windows 单文件构建不支持 Provider 类型：{provider.get('type')}")
    result["providers"] = packed_providers

    experimental = result.setdefault("experimental", {})
    cache = experimental.setdefault("cache_file", {"enabled": True})
    cache.pop("path", None)
    cache.setdefault("cache_id", "personal-ref1nd-windows")

    # sing-box-for-desktop already supplies its own UI. Keep the local Clash API for optional
    # external inspection/selector control, but remove the embedded MetaCubeXD file dependency.
    clash = experimental.get("clash_api")
    if isinstance(clash, dict):
        for key in ("external_ui", "external_ui_download_url", "external_ui_http_client", "external_ui_update_interval"):
            clash.pop(key, None)

    if template and isinstance(clash, dict):
        clash["secret"] = "REPLACE_WITH_RANDOM_SECRET_RUN_INIT"

    # Add schema only to the packed artifact; source fragments remain merge-friendly.
    result = {
        "$schema": "https://raw.githubusercontent.com/reF1nd/sing-box/reF1nd-stable/docs/schema.json",
        **result,
    }
    lint(result, root, template=template)
    return result
