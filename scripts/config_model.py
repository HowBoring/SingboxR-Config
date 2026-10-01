"""Configuration loading and inspection, with an explicit repository root."""
from __future__ import annotations

import copy
from config_io import ConfigError, read_json

def config_files(root, profile="mixed", private_files=None):
    if profile not in ("mixed", "tun"):
        raise ConfigError("未知 Profile；请选择 mixed 或 tun。")
    files = sorted((root / "config").glob("*.json"))
    files += sorted((root / "profiles" / profile).glob("*.json"))
    return files + list(private_files or [root / "private/providers.json", root / "private/api.json"])

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

def load_config(root, profile="mixed", private_files=None):
    result = {}
    for path in config_files(root, profile, private_files):
        result = merge_unique(result, read_json(path))
    return result

def as_list(v):
    return v if isinstance(v, list) else [v]

def expand_rulesets(config):
    result = []
    for entry in config["route"]["rule_set"]:
        if not isinstance(entry, dict) or entry.get("type") not in ("local", "remote", "inline"):
            raise ConfigError("Rule-set 类型必须是 local / remote / inline。")
        tags = as_list(entry.get("tag"))
        if not tags or any(not isinstance(tag, str) or not tag for tag in tags):
            raise ConfigError("Rule-set tag 缺失或无效。")
        for tag in tags:
            item = copy.deepcopy(entry)
            item["tag"] = tag
            for key in ("url", "path", "initial_path"):
                if key in item:
                    if not isinstance(item[key], str):
                        raise ConfigError(f"Rule-set {key} 必须是字符串。")
                    item[key] = item[key].replace("{tag}", tag)
            result.append(item)
    return result

def inside_root(root, value):
    path = (root / value).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError:
        raise ConfigError("配置包脚本仅操作此目录下的文件；请避免外部路径。") from None
    return path

def tag_map(entries, label):
    result = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ConfigError(f"{label} 条目必须是对象。")
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
