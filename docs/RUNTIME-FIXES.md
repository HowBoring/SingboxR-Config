# 运行时修复整合（v1–v7）

所有补丁的有效修复已进入源码与生成的 Windows 模板，旧 ZIP 不再是安装前提。

| 问题 | 主干行为 |
| --- | --- |
| Provider.user_agent 与 http_client 冲突 | UA 位于 provider-download.headers.User-Agent |
| 空 DIRECT detour | Provider 下载客户端及直连 DNS 不配置 DIRECT detour |
| 公共 bootstrap DNS 不可达 | dns-bootstrap 使用 local；provider-download 显式引用它 |
| 订阅无法直连冷启动 | 提供 fetch_provider_seed.py、fix_provider_bootstrap.py，启用 cache 与 initial_path |
| 规则下载经 AUTO 命中 REJECT | ruleset-download 使用 Provider 专属 RULESET-BOOTSTRAP |
| 规则冷启动仍无网络 | seed_rulesets.py 提供本地 SRS initial_path |
| 内核没有 gVisor | TUN 默认显式 system |

v3 的 Cloudflare 直连 DoH 已被 v4 的 local resolver 替代，不重复应用旧补丁。普通 AUTO/CLAUDE 的 REJECT 兜底保持原有策略。RULESET-BOOTSTRAP 默认使用 Airport-A；替换 Provider 时需修改该组，或对生成配置运行下列脚本。

## 已有 Windows Profile 迁移

关闭客户端，在仓库根目录运行（用实际 Provider tag 替换 Airport-A）：

```powershell
py -3 scripts/fix_windows_profile.py .\windows-profile.json
py -3 scripts/fix_tun_stack.py .\windows-profile.json
py -3 scripts/fetch_provider_seed.py .\windows-profile.json Airport-A .\private\Airport-A.seed --proxy http://127.0.0.1:7891
py -3 scripts/fix_provider_bootstrap.py .\windows-profile.json Airport-A "C:\Users\me\Documents\reF1nd-private\Airport-A.seed"
py -3 scripts/fix_ruleset_bootstrap.py .\windows-profile.json Airport-A
```

下载后先将 seed 移到上述稳定路径。7891 必须是另一套已可用客户端的 HTTP 代理；可直连下载时省略 --proxy。所有无法直连、无缓存的 remote Provider 均需独立 seed。脚本先备份再原子写入；已有 .bak 时使用 .bak-2、.bak-3 等，保留各次迁移前的内容。重复应用同一修复不改写 Profile。请保留整个 scripts 目录，迁移入口依赖同目录下的共享模块。

若规则集冷启动下载仍失败：

```powershell
py -3 scripts/seed_rulesets.py .\windows-profile.json "C:\Users\me\Documents\reF1nd-private\rules" --proxy http://127.0.0.1:7891
```

## 从源码重建

默认构建仍不依赖项目 seed 文件路径。需要保留源码里的 Provider / remote rule-set initial_path 时：

```powershell
py -3 scripts/build.py windows --keep-seed-paths
```

此选项保留原路径，导入客户端前应确认所有路径在目标 Windows 主机和 daemon 工作目录下可访问。也可每次构建后对生成文件应用 bootstrap 脚本。远程 Provider 的 path 始终从 Desktop 输出删除。

## MANUAL 选择 Claude 专用节点

新生成的配置中，MANUAL 同时包含普通机场与 Claude-Dedicated 的节点；AUTO、地区组、RULESET-BOOTSTRAP 仍仅包含普通机场。CLAUDE 仍只有 REJECT 与 Claude-Dedicated 节点。

从源码更新已有配置：

```powershell
py -3 scripts/manage.py sync-providers
py -3 scripts/build.py windows --keep-seed-paths
```

未使用 seed 时可省略 --keep-seed-paths。重新导入生成的 Profile 后，在 MANUAL 中直接选择 Claude-Dedicated/节点名称。若要让普通代理流量使用该节点，还要将 PROXY 选择为 MANUAL；CLAUDE 的选择单独控制。

直接维护单文件 Profile 时，在 MANUAL.providers 数组中追加 Claude-Dedicated 即可。保留 MANUAL 的 selector 类型与原 default，不要在 AUTO 或地区组中追加专用 Provider。

local DNS 的可用性取决于系统网络；下载超时本身不足以证明 DNS 已成功。运行期更新、真实订阅、Windows TUN 与防火墙仍需实机验证。

## 可选 LAN 访问

将 mixed-in.listen 改为 0.0.0.0，并按需配置 users 认证；Windows 防火墙在 Private 网络对实际 LAN 来源放行 TCP 7890。Clash 管理 API 保持 127.0.0.1:9090。本机访问 LAN 如需绕过 TUN，可在 route_exclude_address 填写实际 LAN 子网。主干默认仅本机监听。
