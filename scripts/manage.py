#!/usr/bin/env python3
"""Manage this native reF1nd sing-box configuration; Python 3.9+, standard library only.

lint performs project-level checks, NOT sing-box schema/runtime validation.
check/run/export invoke the user's actual sing-box executable.
"""
from __future__ import annotations
import argparse
import concurrent.futures
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
import io

ROOT = Path(__file__).resolve().parents[1]
TARGET = "1.14.2-reF1nd"
PRIVATE_FILES = [ROOT / "private/providers.json", ROOT / "private/api.json"]

class ConfigError(Exception):
    pass

def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=unique_keys)
    except (OSError, ValueError) as exc:
        # Do not print the file contents; they may contain subscription credentials.
        raise ConfigError(f"无法读取 JSON：{path.name} ({type(exc).__name__})") from None

def unique_keys(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError(f"duplicate key: {key}")
        result[key] = value
    return result

def write_json(path: Path, value, private=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".config-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(value, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, path)
        if private:
            path.chmod(0o600)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

def config_files(profile="mixed"):
    files = sorted((ROOT / "config").glob("*.json"))
    files += sorted((ROOT / "profiles" / profile).glob("*.json"))
    return files + PRIVATE_FILES

def merge_unique(left, right, path=""):
    """Static inspection only; native sing-box handles production merging."""
    if isinstance(left, dict) and isinstance(right, dict):
        result = copy.deepcopy(left)
        for k, v in right.items():
            result[k] = merge_unique(result[k], v, f"{path}.{k}") if k in result else copy.deepcopy(v)
        return result
    if isinstance(left, list) and isinstance(right, list):
        return copy.deepcopy(left + right)
    if left != right:
        raise ConfigError(f"配置片段包含冲突标量：{path}")
    return copy.deepcopy(right)

def load_config(profile="mixed"):
    result = {}
    for path in config_files(profile):
        result = merge_unique(result, read_json(path))
    return result

def as_list(v):
    return v if isinstance(v, list) else [v]

def expand_rulesets(config):
    result = []
    for entry in config["route"]["rule_set"]:
        for tag in as_list(entry["tag"]):
            item = copy.deepcopy(entry)
            item["tag"] = tag
            for key in ("url", "path", "initial_path"):
                if key in item:
                    item[key] = item[key].replace("{tag}", tag)
            result.append(item)
    return result

def inside_root(value):
    path = (ROOT / value).resolve()
    try:
        path.relative_to(ROOT)
    except ValueError:
        raise ConfigError("配置包脚本仅操作此目录下的文件；请避免外部路径。") from None
    return path

def tag_map(entries, label):
    result = {}
    for entry in entries:
        tag = entry.get("tag")
        if not isinstance(tag, str) or not tag or tag in result:
            raise ConfigError(f"{label} tag 缺失或重复。")
        result[tag] = entry
    return result

def placeholder(value):
    if isinstance(value, str):
        return "REPLACE_" in value or ".invalid" in value
    if isinstance(value, list):
        return any(placeholder(x) for x in value)
    if isinstance(value, dict):
        return any(placeholder(x) for x in value.values())
    return False

def walk(value):
    if isinstance(value, dict):
        yield value
        for x in value.values():
            yield from walk(x)
    elif isinstance(value, list):
        for x in value:
            yield from walk(x)

def lint(config, template=False, require_seeds=False):
    outs = tag_map(config["outbounds"], "Outbound")
    providers = tag_map(config["providers"], "Provider")
    dns = tag_map(config["dns"]["servers"], "DNS")
    clients = tag_map(config["http_clients"], "HTTP client")
    rulesets = tag_map(expand_rulesets(config), "Rule-set")
    if "Compatible" in outs:
        raise ConfigError("不要覆盖内核自动注入的 Compatible tag。")
    if outs.get("REJECT", {}).get("type") != "block":
        raise ConfigError("REJECT 必须是该 reF1nd 版本支持的 block 出站。")
    for tag, entry in outs.items():
        for ref in entry.get("outbounds", []):
            if ref not in outs:
                raise ConfigError(f"{tag} 引用了不存在的 Outbound：{ref}")
        for ref in entry.get("providers", []):
            if ref not in providers:
                raise ConfigError(f"{tag} 引用了不存在的 Provider：{ref}")
        if tag != "CLAUDE" and "Claude-Dedicated" in entry.get("providers", []):
            raise ConfigError(f"Claude 专用 Provider 不得加入 {tag}。")
        if entry.get("use_all_providers"):
            raise ConfigError("本方案禁止 use_all_providers，避免专用节点进入通用池。")
        if entry.get("type") == "selector" and not (entry.get("providers") and not entry.get("outbounds") and "default" not in entry) and entry.get("default") not in entry.get("outbounds", []):
            raise ConfigError(f"{tag} 的初始 default 必须是已声明静态出站。")
        if entry.get("type") == "urltest" and entry.get("outbounds", []) != ["REJECT"]:
            raise ConfigError(f"{tag} 应保留唯一静态兜底 REJECT，正常节点通过 Provider 注入。")
    claude = outs.get("CLAUDE", {})
    if claude.get("providers") != ["Claude-Dedicated"] or claude.get("outbounds") != ["REJECT"]:
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
        visiting.remove(tag)
        done.add(tag)
    for tag in outs:
        visit(tag)
    for obj in walk(config):
        if "rule_set" in obj and not isinstance(obj["rule_set"], list) or (
            isinstance(obj.get("rule_set"), list) and all(isinstance(x, str) for x in obj["rule_set"])):
            for tag in as_list(obj["rule_set"]):
                if tag not in rulesets:
                    raise ConfigError(f"未声明的规则集：{tag}")
        if "outbound" in obj and isinstance(obj["outbound"], str) and obj["outbound"] not in outs:
            raise ConfigError("路由引用了不存在的 Outbound。")
        if "detour" in obj and obj["detour"] not in outs:
            raise ConfigError("detour 引用了不存在的 Outbound。")
        if "http_client" in obj and isinstance(obj["http_client"], str) and obj["http_client"] not in clients:
            raise ConfigError("HTTP client 引用不存在。")
    for rule in config["dns"]["rules"]:
        if "server" in rule and rule["server"] not in dns:
            raise ConfigError("DNS rule server 引用不存在。")
    if config["dns"]["final"] not in dns or config["route"]["final"] not in outs:
        raise ConfigError("final 引用不存在。")
    for rs in rulesets.values():
        if rs["type"] == "local":
            local = read_json(inside_root(rs["path"]))
            if not isinstance(local.get("rules"), list) or local.get("version") != 3:
                raise ConfigError(f"本地规则集格式错误：{rs['tag']}")
        elif rs["type"] == "remote" and require_seeds:
            path = inside_root(rs["initial_path"])
            if not path.is_file() or path.read_bytes()[:3] != b"SRS":
                raise ConfigError("缺少公开规则初始缓存；先执行 bootstrap。")
    if not template:
        for provider in providers.values():
            if placeholder(provider):
                raise ConfigError(f"尚未填写 Provider：{provider['tag']}。请编辑 private/providers.json。")
            if provider["type"] == "remote":
                url = urllib.parse.urlsplit(provider.get("url", ""))
                if url.scheme != "https" or not url.hostname:
                    raise ConfigError(f"{provider['tag']} 请使用有效的 HTTPS 订阅 URL。")
            elif provider["type"] == "local":
                path = inside_root(provider["path"])
                if not path.is_file() or not path.stat().st_size or placeholder(path.read_text(encoding="utf-8")):
                    raise ConfigError(f"请填好 {provider['tag']} 的本地订阅文件。")
            else:
                raise ConfigError("本管理脚本仅支持 remote/local Provider；其他类型请使用内核原生命令。")
        secret = config["experimental"]["clash_api"].get("secret", "")
        if placeholder(secret) or len(secret) < 32:
            raise ConfigError("API 密钥未初始化或太短；先执行 init。")
    return {"outbounds": len(outs), "providers": len(providers), "rulesets": len(rulesets)}

def initialize():
    for folder in ("private", "state/providers", "state/seeds", "state/ui", "dist", "bin"):
        (ROOT / folder).mkdir(parents=True, exist_ok=True)
    for dest, sample in [("private/providers.json", "examples/providers.example.json"),
                         ("private/api.json", "examples/api.example.json")]:
        if not (ROOT / dest).exists():
            write_json(ROOT / dest, read_json(ROOT / sample), private=True)
    api = read_json(PRIVATE_FILES[1])
    secret = api["experimental"]["clash_api"].get("secret", "")
    if not secret or placeholder(secret):
        api["experimental"]["clash_api"]["secret"] = secrets.token_urlsafe(32)
        write_json(PRIVATE_FILES[1], api, private=True)
    for p in PRIVATE_FILES:
        p.chmod(0o600)
    print("初始化完成；已有订阅配置未覆盖。填写 private/providers.json；API 密钥位于 private/api.json。")

def sync_providers():
    """Explicit edit, never invoked automatically by check or run."""
    p = tag_map(read_json(PRIVATE_FILES[0])["providers"], "Provider")
    if "Claude-Dedicated" not in p:
        raise ConfigError("必须保留 Claude-Dedicated。")
    normal = [tag for tag in p if tag != "Claude-Dedicated"]
    if not normal:
        raise ConfigError("至少需要一家普通机场。")
    path = ROOT / "config/50-outbounds.json"
    obj = read_json(path)
    for item in obj["outbounds"]:
        if item["tag"] == "RULESET-BOOTSTRAP" and any(tag not in normal for tag in item.get("providers", [])):
            item["providers"] = [normal[0]]
        if item["tag"] in ["AUTO", "MANUAL", "HK", "TW", "JP", "SG", "US"]:
            item["providers"] = normal
    write_json(path, obj)
    print("已同步普通机场白名单：" + ", ".join(normal))

def bootstrap(config, proxy=None, force=False):
    """Fetch PUBLIC rules only, never subscription URLs. TLS verification stays on."""
    rs = [x for x in expand_rulesets(config) if x["type"] == "remote"]
    if proxy and (urllib.parse.urlsplit(proxy).scheme not in ("http", "https") or not urllib.parse.urlsplit(proxy).hostname):
        raise ConfigError("--proxy 使用已有 HTTP 代理，例如 http://127.0.0.1:7890；此脚本不支持 SOCKS。")
    def download(entry):
        path = inside_root(entry["initial_path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.read_bytes()[:3] == b"SRS" and not force:
            data = path.read_bytes()
            return entry["tag"], hashlib.sha256(data).hexdigest(), "cached"
        for attempt in range(2):
            tmp = None
            try:
                handler = urllib.request.ProxyHandler({"http": proxy, "https": proxy}) if proxy else urllib.request.ProxyHandler()
                opener = urllib.request.build_opener(handler)
                req = urllib.request.Request(entry["url"], headers={"User-Agent": "ref1nd-config-bootstrap/1.0"})
                with opener.open(req, timeout=30) as response:
                    data = response.read(32 * 1024 * 1024 + 1)
                if len(data) > 32 * 1024 * 1024 or data[:3] != b"SRS":
                    raise ConfigError("返回内容不是允许大小内的 SRS 文件")
                fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".download-", suffix=".tmp")
                with os.fdopen(fd, "wb") as f:
                    f.write(data)
                os.replace(tmp, path)
                return entry["tag"], hashlib.sha256(data).hexdigest(), "downloaded"
            except (OSError, urllib.error.URLError, ConfigError):
                if attempt:
                    raise ConfigError(f"公开规则下载失败：{entry['tag']}。请检查网络或 --proxy；旧缓存不会被覆盖。") from None
                time.sleep(1)
            finally:
                if tmp and os.path.exists(tmp):
                    os.unlink(tmp)
    results, errors = {}, []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(download, x) for x in rs]
        for future in concurrent.futures.as_completed(futures):
            try:
                name, digest, status = future.result()
                results[name] = {"sha256": digest, "status": status}
                print(f"{status:10} {name}")
            except ConfigError as exc:
                errors.append(str(exc))
    write_json(ROOT / "state/seed-manifest.json", {"created_at_unix": int(time.time()), "files": results,
                                                   "note": "Local integrity record, not publisher-authenticated signatures."})
    if errors:
        raise ConfigError("\n".join(errors))
    print(f"已准备 {len(results)} 个公开规则初始文件。订阅 URL 未被此脚本请求。")
    bootstrap_ui(config, proxy, force)


def bootstrap_ui(config, proxy=None, force=False):
    """Download upstream MetaCubeXD; validate paths and archive sizes before extraction."""
    ui = ROOT / "state/ui"
    if (ui / "index.html").is_file() and not force:
        print("cached     MetaCubeXD")
        return
    url = config["experimental"]["clash_api"]["external_ui_download_url"]
    handler = urllib.request.ProxyHandler({"http": proxy, "https": proxy}) if proxy else urllib.request.ProxyHandler()
    opener = urllib.request.build_opener(handler)
    temp = Path(tempfile.mkdtemp(prefix=".ui-", dir=ROOT / "state"))
    try:
        with opener.open(url, timeout=60) as response:
            data = response.read(64 * 1024 * 1024 + 1)
        if len(data) > 64 * 1024 * 1024:
            raise ConfigError("面板归档过大。")
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            if len(entries) > 10000 or sum(e.file_size for e in entries) > 128 * 1024 * 1024:
                raise ConfigError("面板解压大小超过限制。")
            for entry in entries:
                parts = entry.filename.split("/")
                if entry.filename.startswith("/") or ".." in parts or "\\" in entry.filename:
                    raise ConfigError("面板归档包含不安全路径。")
                if len(parts) < 2 or entry.is_dir():
                    continue
                relative = Path(*parts[1:])  # GitHub archive's one enclosing directory
                target = (temp / relative).resolve()
                target.relative_to(temp.resolve())
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(entry) as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
        if not (temp / "index.html").is_file():
            raise ConfigError("面板归档内没有 index.html。")
        previous = ROOT / "state/ui.previous"
        if previous.exists():
            shutil.rmtree(previous)
        if ui.exists():
            os.replace(ui, previous)
        os.replace(temp, ui)
        print("downloaded MetaCubeXD")
    except (OSError, ValueError, zipfile.BadZipFile, urllib.error.URLError):
        raise ConfigError("公开规则已准备；MetaCubeXD 下载失败。可重试 bootstrap，或暂用 groups/select 命令控制。") from None
    finally:
        if temp.exists():
            shutil.rmtree(temp)


def _inline_local_provider(provider):
    """Convert a native sing-box JSON local provider to an inline provider for single-file targets."""
    path = inside_root(provider.get("path", ""))
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
    inline = {
        "type": "inline",
        "tag": provider["tag"],
        "outbounds": outbounds,
        "endpoints": endpoints,
    }
    if provider.get("health_check"):
        inline["health_check"] = copy.deepcopy(provider["health_check"])
    return inline

def windows_profile_config(template=False, keep_seed_paths=False):
    """Build a self-contained single JSON profile for reF1nd sing-box-for-desktop on Windows."""
    config = load_config("tun")
    # Validate source fragments first; template builds may keep Provider/API placeholders.
    lint(config, template=template)
    result = copy.deepcopy(config)

    # Desktop profile content is a single JSON document. Inline project-local rule-sets,
    # and remove CLI-only initial seed paths from remote rule-sets.
    packed_rule_sets = []
    for entry in result["route"]["rule_set"]:
        kind = entry.get("type")
        if kind == "local":
            tags = as_list(entry.get("tag"))
            if len(tags) != 1:
                raise ConfigError("本地 rule-set 转 inline 时必须只有一个 tag。")
            source = read_json(inside_root(entry["path"]))
            if source.get("version") != 3 or not isinstance(source.get("rules"), list):
                raise ConfigError(f"本地规则集格式错误：{tags[0]}")
            packed_rule_sets.append({"type": "inline", "tag": tags[0], "rules": copy.deepcopy(source["rules"])})
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
            packed_providers.append(_inline_local_provider(provider))
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
    return result

def write_windows_profile(template=False, output=None, keep_seed_paths=False):
    result = windows_profile_config(template=template, keep_seed_paths=keep_seed_paths)
    if output is None:
        name = "windows-profile.template.json" if template else "windows-profile.json"
        output = ROOT / "dist" / name
    else:
        output = Path(output).expanduser()
        if not output.is_absolute():
            output = ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)
    write_json(output, result, private=not template)
    print(f"已生成 Windows Desktop 单文件 Profile：{output}")
    if not template:
        print("该文件含真实订阅 URL 与 API 密钥；不要提交 Git、上传公共网盘或作为公开远程 Profile 托管。")
    return output

def core_path(spec=None):
    choice = spec or os.environ.get("SING_BOX_BINARY")
    if choice:
        located = shutil.which(choice)
        path = Path(located or choice).expanduser().resolve()
    else:
        local = ROOT / "bin" / ("sing-box.exe" if os.name == "nt" else "sing-box")
        found = str(local) if local.is_file() else shutil.which("sing-box")
        if not found:
            raise ConfigError("找不到 sing-box：安装 1.14.2-reF1nd，或通过 --core 指定路径。")
        path = Path(found)
    if not path.is_file():
        raise ConfigError("指定的内核文件不存在。")
    try:
        p = subprocess.run([str(path), "version"], capture_output=True, text=True, timeout=15, check=True)
    except (OSError, subprocess.SubprocessError):
        raise ConfigError("无法运行内核 version 命令。") from None
    if TARGET not in p.stdout:
        raise ConfigError(f"此包核验目标是 {TARGET}；检测到的内核版本不匹配。升级前应重新检查配置和空 Provider 行为。")
    return str(path)

def core_command(exe, action, profile, output=None):
    cmd = [exe, action]
    if output is not None:
        cmd.append(str(output))
    cmd += ["-D", str(ROOT)]
    for f in config_files(profile):
        cmd += ["-c", str(f)]
    return cmd

def api_request(config, path, data=None):
    controller = config["experimental"]["clash_api"]["external_controller"]
    if controller not in ("127.0.0.1:9090", "localhost:9090"):
        raise ConfigError("本辅助命令只操作本机 9090 API。其他部署请使用原生命令或面板。")
    request = urllib.request.Request("http://" + controller + path,
        data=None if data is None else json.dumps(data).encode(),
        headers={"Authorization": "Bearer " + config["experimental"]["clash_api"]["secret"], "Content-Type": "application/json"},
        method="GET" if data is None else "PUT")
    try:
        # Never forward the API secret through a system HTTP proxy.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=10) as response:
            body = response.read()
        return json.loads(body) if body else None
    except (OSError, ValueError, urllib.error.URLError):
        raise ConfigError("本机 API 请求失败：确认内核已运行且密钥一致。") from None

def show_groups(config):
    obj = api_request(config, "/proxies")["proxies"]
    for tag in ["PROXY", "AI", "CLAUDE", "MEDIA", "GAME", "AUTO", "MANUAL", "HK", "TW", "JP", "SG", "US"]:
        group = obj.get(tag, {})
        print(f"{tag}: {group.get('now', '(not loaded)')}")
        if tag == "CLAUDE":
            for name in group.get("all", []):
                print("    " + name)

def select_group(config, group, target=None, single_claude=False):
    if not group:
        raise ConfigError("指定策略组和节点名称，例如 select AI US。")
    state = api_request(config, "/proxies/" + urllib.parse.quote(group, safe=""))
    members = state.get("all", [])
    if single_claude:
        candidates = [x for x in members if x.startswith("Claude-Dedicated/")]
        if len(candidates) != 1:
            raise ConfigError("Claude 专用节点数量不等于 1；执行 groups 查看候选，再用 select CLAUDE 明确选择。")
        target = candidates[0]
    if target not in members:
        raise ConfigError("目标不是该策略组的候选项。")
    if group == "CLAUDE" and target != "REJECT" and not target.startswith("Claude-Dedicated/"):
        raise ConfigError("CLAUDE 不允许选择普通机场。")
    api_request(config, "/proxies/" + urllib.parse.quote(group, safe=""), {"name": target})
    print(f"已选择 {group} → {target}")

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["init", "sync-providers", "lint", "bootstrap", "build-windows", "check", "run", "export", "groups", "select", "select-claude"])
    parser.add_argument("group", nargs="?")
    parser.add_argument("target", nargs="?")
    parser.add_argument("--profile", choices=["mixed", "tun"], default="mixed")
    parser.add_argument("--template", action="store_true", help="lint 时允许占位符；不代表配置可联网运行")
    parser.add_argument("--core", help="reF1nd sing-box 可执行文件路径")
    parser.add_argument("--output", help="build-windows 的输出路径；默认 dist/windows-profile.json")
    parser.add_argument("--proxy", help="bootstrap 下载公开规则时使用的已有 HTTP 代理")
    parser.add_argument("--force", action="store_true", help="bootstrap 重新下载初始规则；运行时 cache.db 中规则不会因此自动替换")
    args = parser.parse_args()
    if args.action == "init":
        initialize(); return 0
    if args.action == "sync-providers":
        sync_providers(); return 0
    if args.action == "build-windows":
        write_windows_profile(template=args.template, output=args.output); return 0
    config = load_config(args.profile)
    if args.action == "bootstrap":
        lint(config, template=True)
        bootstrap(config, args.proxy, args.force); return 0
    if args.action == "lint":
        print(json.dumps(lint(config, template=args.template), ensure_ascii=False))
        print("静态检查通过；这不等同于 sing-box check 或联网验收。")
        return 0
    lint(config, require_seeds=args.action in ["check", "run", "export"])
    if args.action == "groups":
        show_groups(config); return 0
    if args.action in ("select", "select-claude"):
        select_group(config, "CLAUDE" if args.action == "select-claude" else args.group, args.target,
                     args.action == "select-claude"); return 0
    exe = core_path(args.core)
    if args.action == "check":
        return subprocess.call(core_command(exe, "check", args.profile), cwd=ROOT)
    if args.action == "export":
        output = ROOT / "dist" / f"config-{args.profile}.json"
        code = subprocess.call(core_command(exe, "merge", args.profile, output), cwd=ROOT)
        if code == 0:
            output.chmod(0o600)
            print(f"已导出 {output.name}；含真实订阅及密钥，请勿公开。运行仍需 -D 指向本配置包根目录。")
        return code
    check = subprocess.call(core_command(exe, "check", args.profile), cwd=ROOT)
    if check:
        return check
    cmd = core_command(exe, "run", args.profile)
    if os.name == "posix":
        os.chdir(ROOT)
        os.execv(exe, cmd)
    return subprocess.call(cmd, cwd=ROOT)

if __name__ == "__main__":
    try:
        sys.exit(main() or 0)
    except ConfigError as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        sys.exit(2)
    except KeyboardInterrupt:
        sys.exit(130)
