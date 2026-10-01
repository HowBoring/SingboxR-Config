"""Bounded HTTPS downloads with explicit proxy behavior and credential-free errors."""
from __future__ import annotations

import urllib.parse
import urllib.request

from config_io import ConfigError


def fetch_bytes(url, headers=None, proxy=None, timeout=30, limit=64 * 1024 * 1024, inherit_proxy=False):
    try:
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("HTTPS URL required")
        if proxy:
            endpoint = urllib.parse.urlsplit(proxy)
            if endpoint.scheme not in ("http", "https") or not endpoint.hostname:
                raise ValueError("HTTP proxy required")
        if timeout <= 0:
            raise ValueError("positive timeout required")
        handler = (urllib.request.ProxyHandler({"http": proxy, "https": proxy}) if proxy else
                   urllib.request.ProxyHandler() if inherit_proxy else urllib.request.ProxyHandler({}))
        opener = urllib.request.build_opener(handler)
        request = urllib.request.Request(url, headers=headers or {})
        with opener.open(request, timeout=timeout) as response:
            body = response.read(limit + 1)
        if not body or len(body) > limit:
            raise ValueError("empty or oversized response")
        return body
    except (OSError, ValueError):
        # URLError/HTTPError messages may contain a full token-bearing subscription URL.
        raise ConfigError("下载失败：请检查 HTTPS 地址、网络、HTTP 代理及响应大小。") from None
