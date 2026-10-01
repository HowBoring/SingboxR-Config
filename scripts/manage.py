#!/usr/bin/env python3
"""Manage this native reF1nd sing-box configuration; Python 3.9+, standard library only.

lint performs project-level checks, NOT sing-box schema/runtime validation.
check/run/export invoke the user's actual sing-box executable.
"""
from __future__ import annotations
import argparse
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
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

from config_io import configure_console, ConfigError, read_json, write_bytes, write_json
import config_model as model
from config_model import as_list, expand_rulesets, merge_unique, placeholder, tag_map
from desktop import pack_windows_profile
from downloads import fetch_bytes
from provider_policy import sync_memberships
from validation import lint as validate_config

ROOT = Path(__file__).resolve().parents[1]
TARGET = "1.14.2-reF1nd"
PRIVATE_FILES = [ROOT / "private/providers.json", ROOT / "private/api.json"]

def config_files(profile="mixed", template=False):
    files = [ROOT / "examples/providers.example.json", ROOT / "examples/api.example.json"] if template else PRIVATE_FILES
    return model.config_files(ROOT, profile, files)


def load_config(profile="mixed", template=False):
    files = [ROOT / "examples/providers.example.json", ROOT / "examples/api.example.json"] if template else PRIVATE_FILES
    return model.load_config(ROOT, profile, files)


def inside_root(value):
    return model.inside_root(ROOT, value)


def lint(config, template=False, require_seeds=False):
    return validate_config(config, ROOT, template=template, require_seeds=require_seeds)


def windows_profile_config(template=False, keep_seed_paths=False):
    return pack_windows_profile(load_config("tun", template=template), ROOT,
                                template=template, keep_seed_paths=keep_seed_paths)


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
    path = ROOT / "config/50-outbounds.json"
    obj = read_json(path)
    normal = sync_memberships(obj["outbounds"], p)
    write_json(path, obj)
    print("已同步普通机场白名单：" + ", ".join(normal) + "；MANUAL 同时包含 Claude-Dedicated。")

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
            try:
                data = fetch_bytes(entry["url"], headers={"User-Agent": "ref1nd-config-bootstrap/1.0"},
                                   proxy=proxy, limit=32 * 1024 * 1024, inherit_proxy=True)
                if data[:3] != b"SRS":
                    raise ConfigError("返回内容不是允许大小内的 SRS 文件")
                write_bytes(path, data)
                return entry["tag"], hashlib.sha256(data).hexdigest(), "downloaded"
            except (OSError, urllib.error.URLError, ConfigError):
                if attempt:
                    raise ConfigError(f"公开规则下载失败：{entry['tag']}。请检查网络或 --proxy；旧缓存不会被覆盖。") from None
                time.sleep(1)
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
    temp = Path(tempfile.mkdtemp(prefix=".ui-", dir=ROOT / "state"))
    try:
        data = fetch_bytes(url, proxy=proxy, timeout=60, inherit_proxy=True)
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
        if tag in ("CLAUDE", "MANUAL"):
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
    configure_console()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["init", "sync-providers", "lint", "bootstrap", "build-windows", "check", "run", "export", "groups", "select", "select-claude"])
    parser.add_argument("group", nargs="?")
    parser.add_argument("target", nargs="?")
    parser.add_argument("--profile", choices=["mixed", "tun"], default="mixed")
    parser.add_argument("--template", action="store_true", help="lint 时允许占位符；不代表配置可联网运行")
    parser.add_argument("--core", help="reF1nd sing-box 可执行文件路径")
    parser.add_argument("--output", help="build-windows 的输出路径；默认 dist/windows-profile.json")
    parser.add_argument("--proxy", help="bootstrap 下载公开规则时使用的已有 HTTP 代理")
    parser.add_argument("--keep-seed-paths", action="store_true", help="build-windows 保留 initial_path")
    parser.add_argument("--force", action="store_true", help="bootstrap 重新下载初始规则；运行时 cache.db 中规则不会因此自动替换")
    args = parser.parse_args()
    if args.action == "init":
        initialize(); return 0
    if args.action == "sync-providers":
        sync_providers(); return 0
    if args.action == "build-windows":
        write_windows_profile(template=args.template, output=args.output, keep_seed_paths=args.keep_seed_paths); return 0
    config = load_config(args.profile, template=args.template and args.action == "lint")
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
