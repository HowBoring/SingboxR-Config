# 验证记录

日期：2026-10-01。配置版本：1.3.0。执行环境：Linux，Python 3.12。

## 已执行

- 72 项 Python unittest：全部通过，包含正常发现的 v5/v7 迁移测试；原始用例结果见 [static-tests.txt](static-tests.txt)。
- mixed 与 tun 两种公开 Profile 的静态 lint。
- 未 init 的临时公开副本生成 Windows 模板；模板在本机 private 配置存在、变化或损坏时均保持一致。
- Windows 模板重新生成，构建输入与成品均通过静态校验。
- Python 语法编译、git diff --check。

重点覆盖 Provider/tag 引用、selector 与 detour 依赖无环、MANUAL 手选专用节点、CLAUDE 拒绝普通节点、专用节点不进入自动/地区/下载组、已删除 Provider 同步、resolver 引用、UA 冲突、seed/cache 与路径冲突、TUN system 栈、规则优先级及 FakeIP 例外、本地/inline Provider、空本地规则打包、转换后校验、迁移备份保留、失败写入保护、下载错误脱敏、HTTP client 请求头和 seed 文件路径限制。

新增 GitHub Actions 配置，覆盖 Python 3.9/3.13 Linux 与 Python 3.11 Windows，并检查公开模板是否与源码一致。这里不预先声明远程 CI 通过；结果以仓库 Actions 为准。

## 测试语义边界

路由和 DNS 测试使用人工构造的规则集命中集合，检查本包的规则顺序；不加载或解码远程 SRS，也不测试 sing-box 的 Go 实现。下载失败和 API 选择回归使用 mock，不代表真实网络下载或实时选点通过。lint 只检查本项目的结构、引用和已知冲突，不是完整 JSON Schema 校验。

## 未执行

目标 1.14.2-reF1nd 的原生 check/run、真实订阅下载与协议解析、Provider 缓存恢复/运行期更新、远程 SRS 的内核兼容性、Clash API 实时选点、Windows Desktop Profile 保存与 daemon 行为、TUN 路由/系统 DNS/IPv6，以及实际 Claude/AI/游戏/媒体访问。

本环境没有目标内核二进制及用户的 Windows 网络，不能把静态检查视为实机验收。

## Windows target 静态结果

生成 Profile 包含 tun-in、mixed-in 与 dns-in；本地规则全部转为 inline。默认删除 remote Provider path/initial_path 和 remote rule-set initial_path，--keep-seed-paths 可保留 initial_path。缓存使用默认 cache.db，MetaCubeXD 外部文件路径被移除。MANUAL 含普通机场与 Claude-Dedicated，CLAUDE 仍只有专用 Provider 与 REJECT。

## 用户侧最小验收

填好 Provider 后 init、sync-providers；CLI 准备规则 seed 后执行 manage.py check。Windows 构建可用 build.py windows --check --core 调用目标内核；使用 seed 时加 --keep-seed-paths 并核对目标主机路径。

启动后确认 MANUAL 能列出 Claude-Dedicated/节点，并手选；若要用于普通代理流量，将 PROXY 选为 MANUAL。CLAUDE 另行选择专用节点；检查 Claude 域名流量仍进入 CLAUDE。专用节点失效时应失败，而不切到普通机场或 DIRECT。最后检查内网、系统 DNS、IPv6、FakeIP 和端口冲突。
