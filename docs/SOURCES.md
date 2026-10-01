# 依据与版本锁定

核对日期：2026-09-30。主配置为本任务编写；第三方内核、域名数据和面板的许可归各自项目。本包不包含其可执行文件或远程规则二进制。

## 内核与官方分支文档

- reF1nd 发布仓库：https://github.com/reF1nd/sing-box-releases/releases
- 目标 release：`1.14.2-reF1nd`。
- 配置实现核对的源码 commit：`7c1ffd271cbc84fed23eaabdcd7e1cefb42a778e`。
- Provider 文档：https://sing-boxr.dustinwin.cc.cd/configuration/provider/
- URLTest 文档：https://sing-boxr.dustinwin.cc.cd/configuration/outbound/urltest/
- HTTP Client 字段：https://sing-boxr.dustinwin.cc.cd/configuration/shared/http-client/
- Rule-set 字段：https://sing-boxr.dustinwin.cc.cd/configuration/rule-set/
- DNS FakeIP server：https://sing-boxr.dustinwin.cc.cd/configuration/dns/server/fakeip/

网站文档会随版本更新，实际运行应使用目标二进制 check，不能因网站有某字段就假定旧版本支持。

## 已直接核对的源代码

下列路径均以该 commit 固定，基址：
https://github.com/reF1nd/sing-box/blob/7c1ffd271cbc84fed23eaabdcd7e1cefb42a778e/

| 文件 | 对本包的影响 |
|---|---|
| `box.go` | 自动附加 Compatible，类型为 direct |
| `protocol/group/provider_members.go` | 静态成员先加入；Provider 筛选结果为空且无静态成员时使用 Compatible |
| `protocol/group/selector.go` | 先尝试缓存选择，再 default；因此设置 CLAUDE 默认 REJECT |
| `protocol/block/outbound.go` | block 出站拒绝 TCP/UDP；该 fork 可用 |
| `include/registry.go` | 仍注册 block；不能套用另一个上游版本的删除结论 |
| `provider/parser/parser.go` | 多种订阅解析入口，remote/local 共用 |
| `provider/parser/sing_box.go` | 原生订阅可包含 outbounds/endpoints；过滤 selector/direct 等非节点类型 |
| `provider/local/lcoal.go` | local 读取订阅文本并注册文件变化监听 |
| `docs/configuration/experimental/clash-api.md` | 面板 /ui、HTTP client、缓存保存选择、mode 需要规则才有作用 |
| `docs/configuration/dns/index.md` | typed DNS、缓存和 reverse_mapping；不使用已弃用 independent_cache |
| `docs/configuration/index.md` | 原生 JSON、check、format、merge |

这些读取不替代实际二进制执行。39 项合成测试没有执行以上 Go 实现。

## 规则数据

- DustinWin 规则主仓：https://github.com/DustinWin/ruleset_geodata
- 动态 SRS 地址模板：https://github.com/DustinWin/ruleset_geodata/releases/download/sing-box-ruleset/{tag}.srs
- AI 集合按 DustinWin README，由 category-ai-!cn 与 ACL4SSR AI.list 等上游组成；实际随上游构建而变化。
- Claude 本地快照来源：https://github.com/v2fly/domain-list-community/blob/master/data/anthropic
- 此次读取的 Claude 文件 blob SHA：`f1d250c0f63442d757c4bbba7cd921817ab4adf3`。
- 本地转换：普通行映射为 domain_suffix；`full:` 行映射为 domain。共 7 个 suffix 和 1 个精确域名。
- 本地 Claude 快照需要人工审阅更新，未加入隐式自动同步或新增第三方运行时依赖。

## 面板

- MetaCubeXD：https://github.com/MetaCubeX/metacubexd
- 公共静态面板归档：https://github.com/MetaCubeX/metacubexd/archive/refs/heads/gh-pages.zip

bootstrap 只下载公开规则与上述面板。它不请求 private/providers.json 中的任何订阅 URL。


## Windows Desktop 适配核对

- reF1nd stable 构建工作流会 checkout `reF1nd/sing-box-for-desktop` 的 `reF1nd-main` 并与 reF1nd sing-box core 一起构建 Windows GUI。
- `sing-box-for-desktop/src/main/profiles.ts`：Profile 内容保存为单个 `<id>.json`，启动时将完整 `configContent` 交给 daemon；文件导入逻辑当前仅接受 `.bpf`。
- `sing-box-for-desktop/src/shared/ipc.ts`：Profile 类型包含 `local` / `remote`，Local Profile 创建接口可携带完整 `content`。
- reF1nd `option/provider.go`：remote Provider 的 `path` 可省略；同时存在 `ProviderInlineOptions`（`outbounds` / `endpoints`）。
- reF1nd `docs/configuration/rule-set/index.md`：inline rule-set 受支持；remote rule-set `initial_path` 仅用于无缓存时的初始内容，因此 Windows 单文件构建将其移除。
- reF1nd `docs/configuration/experimental/cache-file.md`：`cache_file.path` 为空时使用默认 `cache.db`。

Windows 构建转换逻辑因此不是把 CLI 目录路径直接带入 Desktop，而是把本地规则 inline、移除项目相对路径，并保持 Provider/策略/路由语义不变。
