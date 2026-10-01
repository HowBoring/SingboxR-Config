# 验证记录

日期：2026-09-30。

## 已执行

- 标准 JSON 解析（检查重复键）。
- mixed 与 tun 两种 Profile 的静态引用和结构检查。
- 39 项 Python unittest：全部通过。原始输出见 static-tests.txt。测试在不提交 `private/*` 的 clean-clone 风格临时副本中先执行 `init` 再运行，验证公开仓库可自行生成私密占位配置。
- 管理脚本 Python 语法编译检查。

重点覆盖：Provider/tag 引用、组依赖无环、普通池与 Claude 隔离、显式 REJECT 兜底、本地规则绑定、地区正则、首次 init 和再次 init 不覆盖设置、Provider 同步、Claude/AI/广告/厂商直连的合成优先级、国内游戏优先、DNS FakeIP 的入口/查询类型/例外条件，以及 Windows single-file target 的本地规则 inline、Provider/seed 路径剥离、TUN+mixed 入口和 native JSON local Provider 内联。

## 测试语义边界

路由和 DNS 测试使用人工构造的“某目标属于哪些 ruleset”集合。它们验证本包表达的规则顺序，不加载或解码远程 SRS，也不是对 sing-box 的实现测试。它们不能证明所有实际域名均被正确分类。静态 lint 同样不是 sing-box 全量 JSON Schema 校验器。

## 未执行

目标版本的 sing-box check/run、真实订阅下载与协议解析、远程 SRS 下载/兼容性校验、Clash API 实时选点、TUN 操作系统路由、实际 DNS 答案、Claude/AI/游戏/媒体可用性，以及 reF1nd Windows Desktop 的实际 Profile 保存/启动和 daemon 权限行为。

原因：交付环境没有目标内核二进制，容器下载网络不可用，且用户尚未填写真实 Provider。配置没有被宣称为已经过实机验证。

## 用户侧最小验收

填好 Provider 并 init / bootstrap 后，执行 `python scripts/manage.py check`；只有返回成功，才运行 `run`。

通过 groups 确认 AUTO 的节点来自普通机场；CLAUDE 第一次为 REJECT，手选后为 Claude-Dedicated/节点。分别确认普通网页、Claude、其他 AI 的路由日志。暂时断开专用节点时，应失败而非使用 DIRECT/普通机场。用空地区或不匹配正则测试地区兜底时也应失败。此类故障测试建议在独立副本中做，避免影响正在使用的连接。

TUN 验证应后于 mixed，核查私网访问、系统 DNS、IPv6、FakeIP 和端口冲突。保留原可用配置便于回退，但不要让两个客户端同时占用相同端口。


## Windows target 静态验收

`windows_profile_config(template=True)` 已验证：

- 包含 `tun-in` 与 `mixed-in`；
- 6 个本地 rule-set 全部变成 inline；
- remote rule-set 不再含 `initial_path`；
- remote Provider 不再含 `path/initial_path`；
- cache file 不再绑定 `./state/cache.db`；
- MetaCubeXD `external_ui*` 路径已移除；
- 生成 JSON 不含 `./state/`、`./rules/`、`./private/`；
- 转换后仍通过本包 lint。

这只证明 Profile 自包含性和内部引用关系，不证明 Desktop/daemon 实机启动。
