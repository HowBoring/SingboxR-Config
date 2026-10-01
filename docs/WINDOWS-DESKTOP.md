# Windows Desktop 适配说明

适用目标：reF1nd 构建的 sing-box-for-desktop / Windows，配置目标内核 `1.14.2-reF1nd`。

## 构建

1. `py -3 scripts/manage.py init`
2. 编辑 `private/providers.json`，填写所有普通机场和 `Claude-Dedicated`。
3. 增删普通机场后执行 `py -3 scripts/manage.py sync-providers`。
4. 执行 `py -3 scripts/build.py windows`。
5. 使用 `dist/windows-profile.json` 作为 Desktop 的 Local Profile 内容。

如果本机同时有 reF1nd CLI 内核：

```powershell
py -3 scripts/build.py windows --check --core .\bin\sing-box.exe
```

`--template` 允许保留 Provider/API 占位符，仅用于审阅：

```powershell
py -3 scripts/build.py windows --template
```

## 与 CLI 源配置的转换关系

| 源配置 | Windows Profile | 原因 |
|---|---|---|
| `profiles/tun/20-inbounds.json` | 直接合并 | Windows 日常代理默认采用 TUN，同时保留 mixed 7890 |
| `rules/local/*.json` | `type: inline` | 消除外部规则文件路径依赖 |
| remote rule-set `initial_path` | 删除 | Desktop 单文件不携带 `state/seeds/*.srs` |
| remote Provider `path` | 删除 | Provider 内容由启用的 `cache.db` 保存 |
| native JSON local Provider | 转为 `type: inline` | 可把单节点/少量节点封装进一个 Profile |
| Clash/YAML/分享链接 local Provider | 构建时报错 | Python builder 不复制 reF1nd 的订阅解析器，避免错误转换 |
| `cache_file.path` | 删除 | 使用内核默认 `cache.db`，不依赖项目目录 |
| MetaCubeXD `external_ui*` | 删除 | Desktop 已有自己的 GUI |
| Clash API | 保留本机 9090 | 可选的外部观测/策略控制入口 |

## Provider

最常用的 Windows 方式仍是 remote Provider：

```json
{
  "type": "remote",
  "tag": "Airport-A",
  "url": "https://your-provider.example/subscription",
  "user_agent": "clash.meta",
  "update_interval": "24h",
  "health_check": { "enabled": false },
  "http_client": "provider-download"
}
```

Windows build 会自动删除源文件中的 `path`。reF1nd 1.14 的 remote Provider 允许不设置 `path`；在 `experimental.cache_file.enabled` 打开后，Provider 缓存元数据/内容由 cache 数据库管理。

如果 `Claude-Dedicated` 使用 local Provider，builder 仅自动支持原生 sing-box JSON：

```json
{
  "outbounds": [
    {
      "type": "trojan",
      "tag": "Claude-Primary",
      "server": "example.com",
      "server_port": 443,
      "password": "...",
      "tls": { "enabled": true }
    }
  ]
}
```

它会被转换成 reF1nd 已注册的 inline Provider。若本地文件是 Clash YAML 或多行分享链接，继续使用 CLI/local Provider 没问题，但 Windows single-file builder 会拒绝自动转换；此时更推荐直接使用 remote Provider。

## Desktop 导入方式

reF1nd 的 Desktop Profile 后端把每个 Profile 保存成单个 JSON 内容，并把该内容直接交给 daemon 启动。当前“Import File”代码只识别 `.bpf`，不是通用 JSON 导入器。因此本包不生成伪 `.bpf`。

推荐：

1. 打开 Windows Desktop；
2. 新建 Local Profile；
3. 打开 Profile Editor；
4. 将 `dist/windows-profile.json` 完整粘贴；
5. 保存并选中该 Profile；
6. 启动服务；
7. 在策略组界面确认 `CLAUDE` 初始为 `REJECT`，再明确选择 `Claude-Dedicated/<node>`。

如果客户端版本提供“从剪贴板/直接创建 JSON Profile”的入口，也可以使用该入口；核心要求只是最终 Profile 内容等于生成的 JSON。

## TUN 与权限

Windows target 默认包含：

- `tun-in`：自动路由、strict route；
- `mixed-in`：`127.0.0.1:7890`，用于显式代理/调试；
- `dns-in`：`127.0.0.1:1053`。

Desktop daemon/TUN 需要相应系统权限。不要同时运行另一套占用相同 TUN、7890、1053 或 9090 的代理客户端。首次启用时重点检查 WSL、Docker、企业 VPN、Hyper-V/虚拟交换机以及现有私网路由是否冲突。

## 首次启动依赖

Windows Profile 不内嵌 DustinWin 的 SRS 二进制。Provider 在 router/rule-set 启动之前加载；普通机场 Provider 使用 `provider-download → DIRECT` 获取订阅，随后 remote rule-set 由 `ruleset-download → PROXY` 获取。若你的网络无法直连机场订阅地址，首先应解决 Provider 下载路径；若 GitHub ruleset 下载受限，可按实际网络修改 `ruleset-download` HTTP client，或继续使用 CLI 版本的 bootstrap 初始种子方案。

## 安全边界

`dist/windows-profile.json` 包含：

- 机场订阅 URL/token；
- Claude Provider 凭据；
- Clash API secret；
- 若使用 inline local Provider，还可能直接包含节点密码/密钥。

因此它是凭据文件，不是公开配置模板。公开分享应使用 `examples/windows-profile.template.json`，而不是 `dist/windows-profile.json`。

> **预留本地规则说明**：`rules/local/ai-extra.json`、`direct.json`、`proxy.json`、`reject.json`、`realip.json` 默认各含一条 `*.invalid` 哨兵规则，而不是空 `rules`。这是为了兼容 reF1nd 的 inline rule-set 校验；这些域名位于保留的 `.invalid` TLD 下，正常流量不会命中。需要自定义时直接替换对应文件中的 `rules` 即可。

## 冷启动与补丁迁移

参阅 [运行时修复整合](RUNTIME-FIXES.md)。离线 seed 路径可用 `scripts/build.py windows --keep-seed-paths` 保留；目标 Windows 路径需自行核对。
