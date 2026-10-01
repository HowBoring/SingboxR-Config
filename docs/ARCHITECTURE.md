# 架构与整体检查

配置版本：1.3.0。审查日期：2026-10-01。目标内核继续锁定 1.14.2-reF1nd。

## 模块边界

配置内容继续保存在 config、profiles、private 和 rules/local 中；Python 仅使用标准库，没有引入框架或额外依赖。命令入口保持兼容。

| 模块 | 职责 | 依赖 |
| --- | --- | --- |
| config_io.py | 严格 JSON、原子文件写入、保留迁移备份 | 标准库 |
| config_model.py | 合并配置、路径限制、tag 检查、规则集展开 | config_io |
| provider_policy.py | Provider 组成员规则、客户端请求头、更新客户端命名 | config_io |
| validation.py | 引用、出站依赖环、Claude 策略、已知运行时配置冲突 | config_model、provider_policy |
| desktop.py | 将已加载的配置转换为 Windows 单文件 Profile | 配置模型与校验 |
| downloads.py | HTTPS 下载、HTTP 代理、有界响应、错误脱敏 | config_io |
| manage.py / build.py | 参数解析、初始化、同步、下载编排、构建、调用内核或 API | 上述模块 |
| fix_*.py / seed_*.py / fetch_provider_seed.py | 迁移已有单文件 Profile，准备启动种子 | 共享文件、下载与 Provider 逻辑 |

校验器和 Windows 转换函数显式接收配置与项目根目录。manage.py 保留原有辅助函数入口，将具体工作委托给这些模块。CLI 原生 check/run/export 的配置合并仍由 sing-box 执行；Windows 打包使用 Python 合并。

## Provider 选择关系

| 组 | Provider 节点来源 | 选择方式 |
| --- | --- | --- |
| AUTO / HK / TW / JP / SG / US | 普通机场 | 自动测速；空组 REJECT |
| MANUAL | 普通机场 + Claude-Dedicated | 明确手选；默认 AUTO |
| CLAUDE | Claude-Dedicated | 明确手选；默认 REJECT |
| RULESET-BOOTSTRAP | 配置的普通机场 | 用于资源下载；不经过 AUTO |

MANUAL 中选定专用节点只改变 MANUAL 的选择。普通代理流量只有在 PROXY 或其他业务组指向 MANUAL 时才使用它；Claude 路由仍独立指向 CLAUDE。sync-providers 与 lint 使用同一 Provider 策略模块，避免同步后生成校验器不接受的配置。

## 本轮检查与修复

| 发现的问题 | 当前处理 |
| --- | --- |
| MANUAL 白名单与专用 Provider 禁用规则阻止用户手选 | 允许专用 Provider 进入 MANUAL / CLAUDE 两个 selector，继续禁止进入自动组和下载组 |
| manage.py 同时实现文件、校验、构建和命令编排 | 提取共享模块，保留原有命令入口 |
| Windows 转换后未再次校验；inline Provider 无法通过运行配置校验 | 构建前后均检查；支持有效 inline Provider |
| --template 会读取本机 private/providers.json，可能包含订阅凭据 | 模板只使用公开 Provider/API 示例，无需 init |
| 运行时 UA/HTTP client、resolver、seed/cache、空 DIRECT DNS 等错误没有被 lint 提前发现 | 添加对应的引用和兼容性检查 |
| 本地空规则转换为 inline 后导致启动失败 | 打包时转换为保留 .invalid 域名的惰性规则 |
| local Provider 转 inline 静默丢弃 override_* | 明确拒绝此转换，要求将覆盖写入节点；按原生解析器过滤非节点对象 |
| 更新客户端 tag 清洗后可能重名 | 改写过的 tag 带原始名称哈希，避免覆盖另一 Provider 的客户端 |
| 迁移脚本覆盖同名备份，直接写入可能损坏 Profile | 每次有效修改保留独立备份；完整写入临时文件后替换；重复修复不改写 |
| seed 下载未保留内联 HTTP client 的 UA，异常可能输出订阅 URL | 共用请求头解析，保留配置请求头；下载失败不回显 URL；seed 原子写入 |
| seed 文件名直接使用规则 tag，可能越过 seed 目录 | 限制文件名字符并拒绝重复 tag |
| 部分迁移测试在 import 时执行，未计入 unittest 用例数量 | 改为正常 unittest 用例；全部进入 discover |
| Windows 重定向输出使用 cp1252 时中文提示失败，seed 路径未规范化 | CLI 明确输出 UTF-8；CI 使用 Python UTF-8 模式；seed 路径统一 resolve |
| 文档仍包含旧 UA、bootstrap、节点隔离与测试数量说明 | 更新 README、Windows 说明、验证记录和公开模板 |

## 验证与后续扩展

已执行 72 项标准 unittest、mixed/tun 模板 lint、Windows 模板生成、语法检查与 git diff 检查。新增 CI 对 Python 3.9/3.13 Linux 和 Python 3.11 Windows 运行相同静态检查，并检查公开模板是否与源码一致；CI 结果以 GitHub Actions 为准。

新增 Provider 时，修改 private/providers.json 并执行 sync-providers。新增可手选组时，在配置中声明明确成员，不使用 use_all_providers。修改专用 Provider 的允许范围时，需要同时更新 provider_policy 和相关测试。新增构建目标时应采用接收配置和根目录的转换函数，并校验输入与成品。

静态检查不是完整 JSON Schema 校验，也没有执行远程 Provider 的实际订阅解析。Provider 冷启动、缓存恢复、运行期更新、空组行为、实时 API 选择、Windows TUN/DNS 和真实节点服务可用性仍需要目标内核和用户网络验收。Provider-only 的 RULESET-BOOTSTRAP 依赖先加载普通机场；如果其内容为空或不可用，应修复该 Provider 或使用规则 seed，而不能据此推断下载路径一定可用。
