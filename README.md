# reF1nd sing-box 多 Provider 配置 · V1.3

**多机场订阅 / Claude 专用出口 / DustinWin 折中分组方案 / Windows Desktop 单文件构建**

目标内核：`1.14.2-reF1nd`。配置版本：`1.3.0`。源码锁定核对日期：2026-09-30；配置审查日期：2026-10-01。

> 交付状态：CLI 多文件配置与 Windows Desktop 单文件构建均已完成；72 项静态/合成测试通过。尚未使用你的目标内核、真实订阅和 Windows TUN 环境做实机验收。填好 Provider 后仍应执行原生 `check`。静态测试通过不等于内核验证通过。

运行时 v1–v7 修复已整合；新用户无需逐个应用补丁。Provider seed / 规则 seed 冷启动与已有配置迁移见 [运行时修复说明](docs/RUNTIME-FIXES.md)。

## 0. Windows Desktop：推荐使用方式

如果你使用 **reF1nd sing-box Windows Desktop 客户端**，不需要把整个目录复制到客户端。这个版本新增了 Windows build target：以 `profiles/tun` 为基础，把多文件配置合并为一个完整 JSON，并自动完成以下适配：

- 保留 `TUN + mixed`，适合浏览器、Claude Code、Codex、终端等统一分流；
- 把 `rules/local/*.json` 转为 `inline` rule-set；
- remote Provider 去掉 CLI 专用 `./state/providers/*` 持久化路径，交给 Desktop daemon 的 `cache.db`；
- 默认删除 remote seed 路径；`scripts/build.py windows --keep-seed-paths` 可保留 `initial_path`；
- 规则下载通过 `RULESET-BOOTSTRAP → Airport-A`，TUN 显式使用 `system` 栈；
- 移除 MetaCubeXD 的本地文件目录依赖；Desktop 使用自身 GUI；
- 保留 `CLAUDE → REJECT + Claude-Dedicated/*` 的 fail-closed 设计；
- 保留本机 Clash API，便于需要时使用第三方面板/API，但 Windows Desktop 本身不依赖它。

首次仍先执行：

```powershell
py -3 scripts/manage.py init
```

编辑：

```text
private/providers.json
```

填好机场和 Claude 专用 Provider 后：

```powershell
py -3 scripts/manage.py sync-providers
py -3 scripts/build.py windows
```

生成：

```text
dist/windows-profile.json
```

该文件是 **single-file Profile**，已经包含真实订阅 URL 与本机 API 密钥，因此属于敏感文件，`dist/` 默认被 Git 忽略。不要把它上传到公开 GitHub、公开 gist 或第三方在线订阅转换服务。

若本机有目标 reF1nd CLI 内核，还可以在生成后立即检查：

```powershell
py -3 scripts/build.py windows --check --core .\bin\sing-box.exe
```

如果只是查看结构、不填写真实 Provider，可生成无敏感信息的模板：

```powershell
py -3 scripts/build.py windows --template
```

`--template` 使用 examples 中的 Provider/API 占位配置，不读取 private，未 init 的公开仓库也可生成模板。实际构建不加此参数。

仓库已附带同样逻辑生成的 [`examples/windows-profile.template.json`](examples/windows-profile.template.json)。

### 在 Windows Desktop 中导入

当前 Desktop 的“文件导入”路径面向 `.bpf` Profile 包，而不是任意 `.json`。本包因此输出标准 sing-box JSON，而不伪造 `.bpf`。推荐在 Desktop 中新建 **Local Profile**，使用 Profile Editor 将 `dist/windows-profile.json` 的完整内容粘贴进去并保存。另一种方式是把 JSON 放在你自己控制的私密 HTTPS 地址上创建 Remote Profile，但由于文件含机场 token，除非你能保证访问控制，否则不推荐。

完整说明见 [`docs/WINDOWS-DESKTOP.md`](docs/WINDOWS-DESKTOP.md)。

## 1. 从这里开始

本仓库不包含内核二进制、真实订阅、预置面板密钥或第三方规则二进制。你需要 Python 3.9+（仅标准库）和目标版本的 **reF1nd 分支**内核，不是官方 SagerNet 内核。内核发布入口见 [SOURCES.md](docs/SOURCES.md)。

把内核放在 `bin/sing-box`（Windows 为 `bin/sing-box.exe`），或安装到 PATH。也可以在 `check/run/export` 命令后加 `--core /你的路径/sing-box`。Linux 上确保内核可执行。

以下命令在本包根目录执行；`python` 必须指向 Python 3，Linux 上可换为 `python3`，Windows 上可换为 `py -3`。

```bash
python scripts/manage.py init
```

然后编辑 **`private/providers.json`** 的三个 `url`：

| Provider tag | 你要填写的内容 | 被哪些组使用 |
|---|---|---|
| `Airport-A` | 第一家机场的完整 HTTPS 订阅 URL | 普通节点池和地区组 |
| `Airport-B` | 第二家机场的完整 HTTPS 订阅 URL | 普通节点池和地区组 |
| `Claude-Dedicated` | 只包含 Claude 专用节点的 HTTPS 订阅 URL | `CLAUDE` 专用出口与 `MANUAL` 手动选择 |

直接替换整个占位 URL，不要保留 `.invalid/subscription` 后缀。URL 中的 token 属于凭据，不需要发给任何人。当前机场数量只是预留值，增减方法见第 3 节。

```bash
# 准备公开规则和面板，不会请求你填写的机场订阅 URL。
python scripts/manage.py bootstrap

# 静态检查 + 在你的设备调用真实内核检查。
python scripts/manage.py check

# 前台运行；Ctrl+C 停止。
python scripts/manage.py run
```

首次下载 GitHub 资源需要已有代理时，把 bootstrap 那一步改成：

```bash
python scripts/manage.py bootstrap --proxy http://127.0.0.1:7890
```

这里必须是**已经运行的旧代理**，不是尚未启动的新配置。脚本支持 HTTP 代理，不支持 SOCKS 代理参数。完成下载后，先退出占用 7890 / 9090 的旧客户端，再启动本配置。无 `--proxy` 时遵循 Python 的系统/环境 HTTP 代理设置。

启动成功后，在另一个终端执行：

```bash
python scripts/manage.py groups
python scripts/manage.py select-claude
```

`select-claude` **只有在专用 Provider 恰好有一个节点时才会选择它**；多个节点时拒绝猜测。此时使用面板，或根据 `groups` 输出的完整节点名称执行：

```bash
python scripts/manage.py select CLAUDE "Claude-Dedicated/你的专用节点名称"
```

`MANUAL` 中也可以直接选择专用节点：

```bash
python scripts/manage.py select MANUAL "Claude-Dedicated/你的专用节点名称"
```

若希望普通代理流量使用此选择，再执行 `python scripts/manage.py select PROXY MANUAL`。`CLAUDE` 的选择独立保存；在 MANUAL 选点不会修改它。`groups` 会列出 MANUAL 与 CLAUDE 的全部候选。

首次启动时 `CLAUDE → REJECT` 是刻意设计，不是节点失效。选好后通过内核缓存保存；节点消失后回到拒绝兜底，而不是普通机场或直连。完整原因见第 6 节。

## 2. 默认入口与面板

| 功能 | 本包默认值 |
|---|---|
| HTTP / SOCKS 混合代理 | `127.0.0.1:7890` |
| 本地 DNS 调试入口 | `127.0.0.1:1053`，TCP/UDP |
| Clash API | `127.0.0.1:9090` |
| 本地 MetaCubeXD | `http://127.0.0.1:9090/ui/` |
| API 密钥 | `private/api.json`；由 `init` 随机生成 |

面板首次连接时，后端填写 `http://127.0.0.1:9090`，密钥从本机 `private/api.json` 读取。不要把真实密钥复制到公开日志、截图或在线面板。默认仅允许本地面板来源，不暴露到局域网。

默认是 **mixed 显式代理模式**：需要在应用或操作系统中指定代理。它不会自动接管所有程序、容器、UDP 流量或系统 DNS。终端示例：

```bash
export HTTP_PROXY=http://127.0.0.1:7890
export HTTPS_PROXY=http://127.0.0.1:7890
# 只对支持这些变量的应用生效。
```

在 Windows/WSL/容器分别运行应用时，`127.0.0.1` 指向哪个网络命名空间要单独确认；不要为解决连接问题直接把无认证的代理入口改成 `0.0.0.0`。

本配置使用固定的 **Rule 路由**，没有加入 `clash_mode` 的全局/直连覆盖规则。面板上的 Global / Direct 模式选择不改变这里的路由策略；应通过 `PROXY`、`AI`、`MEDIA` 等策略组选择出口。这是为了避免一个全局按钮绕过 Claude 专用路由。

## 3. 修改 Provider

### 增加或删除普通机场

在 `private/providers.json` 的 `providers` 数组中增删完整对象。增加时参考 `examples/provider-extra.example.json`，使用唯一 tag 和独立缓存路径。之后执行：

```bash
python scripts/manage.py sync-providers
python scripts/manage.py lint
```

`sync-providers` 将普通机场同步到 `AUTO / HK / TW / JP / SG / US`；`MANUAL` 包含全部普通机场和 `Claude-Dedicated`，可直接手选专用节点。`CLAUDE` 仍只引用专用 Provider。规则下载组保留已选普通机场；该机场被删除或列表为空时改用第一家普通机场。至少保留一家普通机场，增删后均需同步。

如果机场订阅混入“官网、剩余流量、到期时间”假节点，可在该 Provider 上添加适合其命名的 `exclude` 正则。不要盲目复制过宽的排除条件。默认 User-Agent 为 `clash.meta`。机场要求其他 UA 时，为它创建独立 HTTP client，在 `headers.User-Agent` 中设置值，再修改 Provider 的 `http_client` 引用；不要同时设置 Provider.user_agent 和 http_client。

远程 Provider 下载默认使用无 detour 的 `provider-download` 直接拨号，域名解析显式使用系统 `dns-bootstrap`，避免“先有订阅节点才能下载同一份订阅”的循环。订阅域名无法直连时，先用已有可信代理获取 seed，为 remote Provider 配置 initial_path；步骤见 [运行时修复说明](docs/RUNTIME-FIXES.md)。也可使用 local Provider。不要直接让空订阅通过自己下载自己。协议和订阅格式由目标内核解析，本脚本不做在线第三方订阅转换。

### Claude 只有单节点链接或原生节点配置

不必为了单节点另建订阅服务。只把专用 Provider 对象替换为：

```json
{
  "type": "local",
  "tag": "Claude-Dedicated",
  "path": "./private/claude-nodes.txt",
  "health_check": { "enabled": false }
}
```

然后在 `private/claude-nodes.txt` 保存内核支持的节点分享链接，或合法的 sing-box 订阅内容，例如：

```json
{
  "outbounds": [
    {
      "type": "trojan",
      "tag": "Claude-Primary",
      "server": "REPLACE_NODE_SERVER",
      "server_port": 443,
      "password": "REPLACE_NODE_PASSWORD",
      "tls": {
        "enabled": true,
        "server_name": "REPLACE_TLS_SERVER_NAME"
      }
    }
  ]
}
```

上述只是 **Trojan 格式示例**，不是对你节点协议的判断；请使用服务商实际提供的协议、TLS、传输层和认证字段，不要只替换地址就套到其他协议上。保持证书校验开启。包内 `examples/providers.local-claude.example.json` 展示替换后的完整 Provider 结构；不要覆盖已经填好的其他机场 URL。

local 文件不在 `config/` 内，避免被当成主配置再次合并。远程和本地 Provider 最终使用同一订阅解析入口；具体协议能否被解析仍需目标内核实测。源码依据见 SOURCES。

## 4. 策略与规则

源配置包含 **29 个 DustinWin 远程规则集 + 6 个本地规则集**；Windows 构建会把这 6 个本地规则集转换为 inline；共 **15 个出站对象**，其中 13 个选择/测速组和 `DIRECT / REJECT` 两个基础出站。

| 业务组 | 默认选择 | 说明 |
|---|---|---|
| `PROXY` | `AUTO` | 通用代理和未匹配流量 |
| `MANUAL` | `AUTO` | 可手选普通机场或 Claude-Dedicated 节点 |
| `AI` | `US` | 非 Claude 的 AI；可改 JP / SG / PROXY / MANUAL |
| `CLAUDE` | `REJECT`，首次手选专用节点 | 不包含普通机场、不自动切普通出口 |
| `MEDIA` | `PROXY` | 各媒体细规则统一进入这个组 |
| `GAME` | `DIRECT` | 可在面板改成代理或地区组 |

地区组按名称正则筛选，而不是按真实出口 GeoIP 验证。US/JP/SG 标签及测速成功不代表某 AI 服务可用。`AI → US` 是可修改的初始偏好，不是“美国节点一定解锁全部 AI”的承诺。机场没有美国节点时 US 会拒绝连接，应改 AI 的选择或修正节点命名正则。

| 规则范围 | 规则集 | 行为 |
|---|---|---|
| 私网 | `private`、`privateip` | DIRECT |
| Claude | `local-ai-claude` | CLAUDE |
| 其他 AI | `ai`、`local-ai-extra` | AI |
| 广告 | `ads` | reject；AI 识别优先于广告拦截 |
| 应用 | `applications` 且属于 `cn / games-cn` | DIRECT，不按进程名放行所有流量 |
| 国内生态 | `microsoft-cn`、`apple-cn`、`google-cn`、`bilibili` | DIRECT |
| 游戏 | `games-cn` / `games` | 分别 DIRECT / GAME |
| 媒体域名 | `netflix`、`disney`、`max`、`primevideo`、`appletv`、`youtube`、`tiktok`、`spotify`、`media` | MEDIA |
| 媒体 IP | `netflixip`、`mediaip` | MEDIA |
| 工具与 Telegram IP | `networktest`、`telegramip` | PROXY |
| 基础分流 | `proxy`、`cn`、`cnip` | PROXY / DIRECT / DIRECT |
| DNS 例外 | `fakeip-filter`、`trackerslist` | 排除 FakeIP，不等于强制直连 |

策略顺序的权威内容是 `config/70-route.json`。关键关系是：私网 → 本地显式覆盖 → Claude → AI → 广告 → 受限应用直连 → 国内游戏 → 媒体/海外游戏/工具 → 国内服务 → proxy → cn → 解析未知域名 → 私网/CN IP → PROXY。

没有单独加载 `gfw` 或 `tld-proxy`，也没有为每家流媒体创建策略组。后续需要 Netflix 与 YouTube 分开选出口时，只需增加策略组并调整对应映射，无须更换规则源。

## 5. DNS 与可选 TUN

默认沿用已确认的“国内直连、其他代理”策略，与当前设备地理位置无关。DNS-bootstrap 使用系统 local resolver，DNS-cn 默认 `223.5.5.5`，海外 DoH 默认 `1.1.1.1` 并经对应的 PROXY / AI / CLAUDE / MEDIA / GAME 出站访问。可在 `config/40-dns.json` 修改。

**mixed 模式不向应用返回 FakeIP。** TUN 模式只对从 `tun-in` 接收、命中已知海外分类、且不在 FakeIP 例外列表中的 A / AAAA 查询使用 FakeIP。内部解析和 1053 调试入口不通过该入口匹配条件生成 FakeIP。未知域名获取真实 IP，再让 route 中的 CN IP 规则判断是否直连。

私有域名走系统本地解析器。TUN 环境下必须确认系统解析器没有重新指向被本进程接管的 DNS 路径而形成循环；使用公司/家庭内网 DNS 时，可将 `dns-local` 换成明确的 LAN DNS 地址，并按部署网络排除其流量。不能把公共 DNS 当作私有域名解析器。

可选 TUN 使用独立 Profile，**不要把两个 Profile 同时加载**：

```bash
python scripts/manage.py check --profile tun
python scripts/manage.py run --profile tun
```

`run --profile tun` 需要相应管理权限；先成功运行 mixed，再以管理员终端/适当权限测试 TUN。此 Profile 没有在你的 OS 上实测；请检查虚拟网段与现有 VPN/容器网段是否重叠、IPv6、系统 DNS 和物理网卡路由。接口名交给内核自动生成，不硬编码平台相关名称。TUN 不代表对企业安全代理、应用内 DoH 或所有系统功能都自动兼容，也不是系统级 kill switch。

该 Profile 同时保留 mixed 7890，便于调试。不要并行运行 mixed 和 tun 两个实例，它们会争用端口及同一个缓存数据库。

## 6. Claude 拒绝兜底为何不能省略

在本包核对的 commit 中，内核自动创建 `Compatible`，其类型是 `direct`；Provider 策略组没有成员时可能回落到它。因此“CLAUDE 只写 providers、不写 DIRECT”并不等价于保证不会直连。

这里使用该 reF1nd commit 仍支持的 `block` 出站作为 `REJECT`，并把它作为明确的静态成员。CLAUDE 默认 REJECT，专用节点经过一次明确选择才启用。缓存保存选择；缓存节点不存在时回到 REJECT。普通 URLTest 也有 REJECT 静态兜底，空地区组不借用隐式 Compatible。

这不是对任意未来版本的保证：源码、原生 `check` 和空组行为都需要随升级重新验证。管理脚本因此检查目标版本。此方案防的是配置内的隐式兜底；应用不使用本代理、用户添加更早的显式直连覆盖、第三方网关域名不在规则内等情况不属于这一保证。

`CLAUDE` 只允许专用 Provider，`MANUAL` 也允许明确手选其节点；专用节点不进入 AUTO、地区测速组或规则下载组。订阅内容本身仍需由你确认可信。只放你确认用于 Claude 的节点，不要把包含大量普通节点的整个机场塞进该 Provider。专用节点失效时不自动尝试另一家普通机场。

## 7. 本地规则与 AI 扩展

| 文件 | 用途 |
|---|---|
| `rules/local/ai-claude.json` | Anthropic 列表快照；含 MCP、用户内容域名和精确 CDN 主机 |
| `rules/local/ai-extra.json` | 添加综合 AI 集合未覆盖的具体 API/网关域名 |
| `rules/local/direct.json` | 手动直连覆盖，高于 AI 规则 |
| `rules/local/proxy.json` | 手动走 PROXY 的覆盖，高于 AI 规则 |
| `rules/local/reject.json` | 手动阻断覆盖 |
| `rules/local/realip.json` | 只禁用 FakeIP，保留正常出口路由 |

本地文件使用 source 规则集格式，初始空集合 `"rules": []` 不匹配任何流量。添加内容的示例：

```json
{
  "version": 3,
  "rules": [
    { "domain_suffix": ["your-ai-gateway.example"] }
  ]
}
```

把示例域名替换为真实的、你控制或明确识别的 API 域名。模型名不参与网络分流：通过第三方网关调用 Claude，请求目的地是网关，不会因为 JSON 里写了 Claude 自动匹配 Anthropic 域名。需要专用出口时，将该网关的精确域名补入 Claude 本地规则；需要普通 AI 出口时补入 ai-extra。

不要把整个 Cloudflare、AWS、Google 或通用 CDN 主域加入 Claude，否则会带走大量无关流量。当前 Claude 文件是经过核对的本地快照，**不会自动同步上游**，来源、blob SHA 和日期在 `docs/`；DustinWin 远程规则则由内核按 24h 更新。

本地 direct / proxy 覆盖有意优先于 AI，只应放确实需要改写的目标。私网规则更早，不用这里的 override 代理内网地址。

广告过滤需要关闭时，必须同步删除 route 和 dns 中的 `ads` 拒绝规则，而不只是修改其中一处。

## 8. 文件布局与命令

```text
config/                  主配置片段，不含订阅 token
profiles/mixed/          默认 HTTP/SOCKS + 本机 DNS
profiles/tun/            可选 TUN + mixed + 本机 DNS
private/providers.json   填写真实订阅；不入 Git
private/api.json         本机面板随机密钥；不入 Git
examples/                可公开的 Provider/密钥示例
rules/local/             可维护的本地 source 规则
scripts/manage.py        初始化、公开资源下载、校验、启动、面板选择、Windows 构建
scripts/build.py         可分发 target 构建入口（当前含 windows）
scripts/config_model.py  配置读取、合并与规则集展开
scripts/validation.py    引用、策略与运行时兼容性检查
scripts/desktop.py       Windows 单文件转换
scripts/provider_policy.py Provider 白名单与 HTTP 请求头
scripts/config_io.py     严格 JSON、原子写入与迁移备份
scripts/downloads.py     有界 HTTPS 下载与错误脱敏
targets/windows.json     Windows target 的转换约定说明
state/seeds/             首次启动的 SRS 文件
state/providers/         内核订阅缓存；可能含节点密码
state/cache.db           内核规则/选择/FakeIP 缓存
state/ui/                下载后的本地面板
bin/                     自行放入目标内核；不随本包提供
dist/                    合并导出结果；包含敏感信息
```

| 命令 | 行为 |
|---|---|
| `init` | 创建必要目录、生成本机密钥；不覆盖已有订阅 |
| `sync-providers` | 同步普通机场；MANUAL 额外包含专用 Provider；修复规则下载组悬空引用 |
| `lint --template` | 使用公开示例检查项目配置，不读取 private，不能据此运行 |
| `lint` | 项目静态检查，同时确认订阅和密钥已填写 |
| `bootstrap [--proxy ...]` | 下载公开 SRS 和面板，不请求机场订阅 |
| `build-windows [--template] [--keep-seed-paths]` | 生成 Windows Desktop 单文件 Profile |
| `scripts/build.py windows` | 与上项相同的 target-oriented 构建入口，可配 `--check` |
| `check [--profile ...]` | 调用目标内核 `sing-box check` |
| `run [--profile ...]` | 先 check，再前台运行 |
| `groups` | 读取本机 API 当前策略及 Claude 候选 |
| `select AI US` | 修改组选择；不更改配置文件 |
| `select-claude` | 专用 Provider 只有一个节点时明确选择它 |
| `export [--profile ...]` | 调用内核 merge 到 dist，输出包含真实凭据 |

Profile 默认 mixed。`check/run/export` 支持 `--core` 或环境变量 `SING_BOX_BINARY`。脚本不设置系统代理、不修改防火墙、不安装服务，也不需要第三方 Python 包。

`bootstrap --force` 更新的是初始文件，不会强制替换运行中的 `cache.db` 规则版本。`initial_path` 是冷启动种子，正常使用仍由核心缓存和 24h 更新控制。不要为了更新种子删除整个 cache.db：这同时会清除 Claude 选择和 FakeIP 状态。

`export` 生成的是 CLI 合并主配置，**不是完全自包含的单文件**；本地规则、缓存种子等仍按 `-D` 指向包根目录访问。Windows Desktop 请使用 `build-windows` / `scripts/build.py windows`，后者会内联本地规则并去除项目路径依赖。两者都不会把动态 Provider 内的节点固化成静态出站。

所有 JSON 是标准 JSON，无注释、无尾逗号。`private/` 只显式加载两个主配置文件，单节点文件不会被误合并。不需要把 JSON 手工拼接，也不依赖额外模板引擎；生产配置合并由内核原生命令执行，Python 内部合并用于静态检查与 Windows 单文件构建；CLI 的生产配置合并由内核处理。

模块职责、整体检查结果和扩展约定见 [架构说明](docs/ARCHITECTURE.md)。

## 9. 验证、故障定位和安全

随包提供 72 项测试；本次已执行：

```bash
python scripts/manage.py lint --template
python scripts/manage.py lint --template --profile tun
python -m unittest discover -s tests -v
```

结果见 `docs/VALIDATION.md` 和 `docs/static-tests.txt`。这些测试使用**合成的规则命中集合**检查优先级，不解析真实 SRS、不运行目标内核、不证明实时域名覆盖或节点可用。

| 现象 | 先检查 |
|---|---|
| 提示 Provider 未填写 | private/providers.json 是否仍有 REPLACE / .invalid |
| 找不到或拒绝内核版本 | bin、PATH、--core；不要使用官方上游或未核对版本 |
| 缺少公开初始规则 | 先 bootstrap；需要时借用已有 HTTP 代理 |
| Claude 不通但普通网页正常 | groups 查看是否仍为 REJECT；是否已选择专用节点 |
| AI/某地区不通 | 该地区是否有节点、正则是否匹配；速度测试不代表服务权限 |
| 面板未加载 | bootstrap 的 UI 下载是否成功；API 端口和密钥是否一致 |
| UI 下载失败但规则已就绪 | 重试 bootstrap，或直接使用 groups / select 命令 |
| 订阅初次下载失败 | 订阅能否直连、UA/返回格式是否正确；不要创建自依赖 |
| TUN 下内网域名异常 | 本地 DNS、路由、网段重叠，以及解析回环 |

`.gitignore` 排除了 private、state、dist 和 bin，但不能让已经被 Git 追踪的凭据自动消失；发生过公开泄露就轮换订阅 URL/节点凭据/API 密钥。state/providers 的缓存也可能包含密码，不能只保护订阅 URL。日志和面板截图也按敏感数据处理。

不关闭 TLS 证书校验，不将订阅发送到公开转换站点。公开 SRS 通过 HTTPS 获取；记录的 SHA-256 是本地完整性记录，不是上游签名认证。第三方规则及面板会影响路由或本机管理界面，应仅保留可信来源。

**未完成的实际验证**：目标内核 check/run、真实订阅格式/更新、实际 DNS 答案、TUN 跨平台路由、面板与内核的运行时交互、Claude/其他 AI/媒体访问。运行环境没有可用目标内核且下载网络不可用，不能把这些验证冒充为已通过。

> **预留本地规则说明**：`rules/local/ai-extra.json`、`direct.json`、`proxy.json`、`reject.json`、`realip.json` 默认各含一条 `*.invalid` 哨兵规则，而不是空 `rules`。这是为了兼容 reF1nd 的 inline rule-set 校验；这些域名位于保留的 `.invalid` TLD 下，正常流量不会命中。需要自定义时直接替换对应文件中的 `rules` 即可。
