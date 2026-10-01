"""Project invariants and reference checks, not a full sing-box schema validator."""
from __future__ import annotations

import urllib.parse
from config_io import ConfigError, read_json
from config_model import as_list, expand_rulesets, inside_root, placeholder, tag_map, walk
from provider_policy import validate_membership

def lint(config, root, template=False, require_seeds=False):
    if not isinstance(config, dict):
        raise ConfigError("主配置必须是 JSON 对象。")
    for name in ("outbounds", "providers", "http_clients", "inbounds"):
        if not isinstance(config.get(name), list):
            raise ConfigError(f"主配置必须包含 {name} 数组。")
    for name, fields in (("dns", ("servers", "rules")), ("route", ("rule_set", "rules"))):
        section = config.get(name)
        if not isinstance(section, dict) or any(not isinstance(section.get(key), list) for key in fields):
            raise ConfigError(f"{name} 缺少必需数组。")
    outs = tag_map(config["outbounds"], "Outbound")
    providers = tag_map(config["providers"], "Provider")
    dns = tag_map(config["dns"]["servers"], "DNS")
    clients = tag_map(config["http_clients"], "HTTP client")
    rulesets = tag_map(expand_rulesets(config), "Rule-set")
    tag_map(config["inbounds"], "Inbound")
    cache = config.get("experimental", {}).get("cache_file", {})
    if "Compatible" in outs:
        raise ConfigError("不要覆盖内核自动注入的 Compatible tag。")
    if outs.get("REJECT", {}).get("type") != "block":
        raise ConfigError("REJECT 必须是该 reF1nd 版本支持的 block 出站。")
    for tag, entry in outs.items():
        for field in ("outbounds", "providers"):
            if field in entry and (not isinstance(entry[field], list) or not all(isinstance(x, str) for x in entry[field])):
                raise ConfigError(f"{tag}.{field} 必须是 tag 数组。")
        for ref in entry.get("outbounds", []):
            if ref not in outs:
                raise ConfigError(f"{tag} 引用了不存在的 Outbound：{ref}")
        for ref in entry.get("providers", []):
            if ref not in providers:
                raise ConfigError(f"{tag} 引用了不存在的 Provider：{ref}")
        validate_membership(tag, entry)
        if entry.get("type") == "selector" and not (entry.get("providers") and not entry.get("outbounds") and "default" not in entry) and entry.get("default") not in entry.get("outbounds", []):
            raise ConfigError(f"{tag} 的初始 default 必须是已声明静态出站。")
        if entry.get("type") == "urltest" and entry.get("outbounds", []) != ["REJECT"]:
            raise ConfigError(f"{tag} 应保留唯一静态兜底 REJECT，正常节点通过 Provider 注入。")
    claude = outs.get("CLAUDE", {})
    if (claude.get("type") != "selector" or claude.get("providers") != ["Claude-Dedicated"]
            or claude.get("outbounds") != ["REJECT"] or claude.get("default") != "REJECT"):
        raise ConfigError("CLAUDE 必须只允许专用 Provider 和 REJECT。")
    visiting, done = set(), set()
    def visit(tag):
        if tag in visiting:
            raise ConfigError(f"Outbound 存在环：{tag}")
        if tag in done:
            return
        visiting.add(tag)
        for child in outs[tag].get("outbounds", []):
            visit(child)
        if outs[tag].get("detour") in outs:
            visit(outs[tag]["detour"])
        visiting.remove(tag)
        done.add(tag)
    for tag in outs:
        visit(tag)
    for obj in walk(config):
        if "rule_set" in obj and (isinstance(obj["rule_set"], str) or (
            isinstance(obj["rule_set"], list) and all(isinstance(x, str) for x in obj["rule_set"]))):
            for tag in as_list(obj["rule_set"]):
                if tag not in rulesets:
                    raise ConfigError(f"未声明的规则集：{tag}")
        if "outbound" in obj and isinstance(obj["outbound"], str) and obj["outbound"] not in outs:
            raise ConfigError("路由引用了不存在的 Outbound。")
        if "detour" in obj and obj["detour"] not in outs:
            raise ConfigError("detour 引用了不存在的 Outbound。")
        if "http_client" in obj and isinstance(obj["http_client"], str) and obj["http_client"] not in clients:
            raise ConfigError("HTTP client 引用不存在。")
        for field in ("domain_resolver", "default_domain_resolver"):
            if field in obj:
                resolver = obj[field]
                ref = resolver.get("server") if isinstance(resolver, dict) else resolver
                if ref not in dns:
                    raise ConfigError("域名解析器引用不存在。")
    for provider in providers.values():
        kind = provider.get("type")
        if kind not in ("remote", "local", "inline"):
            raise ConfigError("Provider 类型必须是 remote / local / inline。")
        if kind == "local" and (not isinstance(provider.get("path"), str) or not provider["path"]):
            raise ConfigError("local Provider 必须指定 path。")
        if kind == "remote" and provider.get("user_agent") and provider.get("http_client"):
            raise ConfigError("Provider.user_agent 与 http_client 冲突；请将 UA 放入 HTTP client headers。")
        if kind == "inline":
            nodes = provider.get("outbounds", [])
            endpoints = provider.get("endpoints", [])
            if not isinstance(nodes, list) or not isinstance(endpoints, list) or not (nodes or endpoints):
                raise ConfigError("inline Provider 必须有节点。")
            tag_map(nodes + endpoints, "Provider node")
            if any(node.get("type") in ("direct", "block", "dns", "selector", "urltest", "pass") for node in nodes):
                raise ConfigError("inline Provider 只允许代理节点，不允许策略组或直连/拒绝出站。")
    for entry in list(providers.values()) + list(rulesets.values()):
        if entry.get("type") == "remote" and entry.get("initial_path"):
            if entry.get("path"):
                raise ConfigError("remote path 与 initial_path 冲突。")
            if not isinstance(cache, dict) or cache.get("enabled") is not True:
                raise ConfigError("initial_path 需要启用 cache_file。")
    for server in dns.values():
        if server.get("detour") == "DIRECT" and outs.get("DIRECT") == {"type": "direct", "tag": "DIRECT"}:
            raise ConfigError("新式 DNS 不应 detour 到空 DIRECT 出站；省略 detour 即可直连。")
    for rule in config["dns"]["rules"]:
        if "server" in rule and rule["server"] not in dns:
            raise ConfigError("DNS rule server 引用不存在。")
    if config["dns"]["final"] not in dns or config["route"]["final"] not in outs:
        raise ConfigError("final 引用不存在。")
    for rs in rulesets.values():
        if rs["type"] == "local":
            if not rs.get("path"):
                raise ConfigError("local rule-set 必须指定 path。")
            local = read_json(inside_root(root, rs["path"]))
            if not isinstance(local.get("rules"), list) or local.get("version") != 3:
                raise ConfigError(f"本地规则集格式错误：{rs['tag']}")
        elif rs["type"] == "remote" and require_seeds:
            if not rs.get("initial_path"):
                raise ConfigError("缺少规则 initial_path；先执行 bootstrap。")
            path = inside_root(root, rs["initial_path"])
            if not path.is_file() or path.read_bytes()[:3] != b"SRS":
                raise ConfigError("缺少公开规则初始缓存；先执行 bootstrap。")
        elif rs["type"] == "inline" and (not isinstance(rs.get("rules"), list) or not rs["rules"]):
            raise ConfigError("inline rule-set 不能没有规则。")
    if not template:
        for provider in providers.values():
            if placeholder(provider):
                raise ConfigError(f"尚未填写 Provider：{provider['tag']}。请编辑 private/providers.json。")
            if provider["type"] == "remote":
                url = urllib.parse.urlsplit(provider.get("url", ""))
                if url.scheme != "https" or not url.hostname:
                    raise ConfigError(f"{provider['tag']} 请使用有效的 HTTPS 订阅 URL。")
            elif provider["type"] == "local":
                path = inside_root(root, provider["path"])
                if not path.is_file() or not path.stat().st_size or placeholder(path.read_text(encoding="utf-8")):
                    raise ConfigError(f"请填好 {provider['tag']} 的本地订阅文件。")
            elif provider["type"] == "inline":
                pass  # Node structure was checked above; placeholders are checked for all kinds.
        secret = config["experimental"]["clash_api"].get("secret", "")
        if placeholder(secret) or len(secret) < 32:
            raise ConfigError("API 密钥未初始化或太短；先执行 init。")
    return {"outbounds": len(outs), "providers": len(providers), "rulesets": len(rulesets)}
