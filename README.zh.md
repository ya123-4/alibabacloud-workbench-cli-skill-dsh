# alibabacloud-workbench-cli-skill-dsh（中文说明）

[aliyun/alibabacloud-aiops-skills](https://github.com/aliyun/alibabacloud-aiops-skills)
里 Alibaba Cloud Workbench CLI 这个 skill 的 DeepSeek Harness 插件包（bundle 版本 0.0.1）。

[English](README.md)

它把上游 tag `alibabacloud-workbench-cli-0.0.1`
（`skills/developertools/solutions/alibabacloud-workbench-cli/`）重建为一个可由
模型调用的 DSH skill：`alibabacloud-workbench-cli`，并在其之上做了本地扩展。纯 skill
插件——不含 hooks、不含原生工具、不含安装脚本。

**CLI 本身不在本包里。** `workbench` 是需要用户另行安装的外部依赖（安装方式见上游
文档）；本包不会下载、分发或升级那个二进制，包里只有 skill 文本与无第三方依赖的辅助脚本。

## 这个 skill 做什么

上游部分：讲清楚 CLI 的用法——连接目标实例、通过会话通道执行命令、上传下载文件、
管理凭证与 profile，以及各类错误码的处理办法。上游正文是按通用 Linux shell 写的；
映射到本机的差异见 `SKILL.md` 末尾的 DSH 说明。

在上游之上新增的本地扩展——**全部只读**，都复用 CLI 同一份 AccessKey
（`~/.workbench/config.json`），都不需要安装第三方包：

| 扩展 | 作用 |
|---|---|
| `### 10. Instance lifecycle & monitoring` | `workbench` 没有的开关机与 CloudMonitor 指标查询 |
| `### 11. Instance reports` | 一条命令生成实例报告（见下） |
| `scripts/ecs_instance.py` | 通过 ECS OpenAPI 做 `status` / `start` / `stop`（`--wait`、`stop --yes`、`--stop-mode`、`--report`） |
| `scripts/ecs_metrics.py` | 查询 CloudMonitor 指标点（`--metric`、`--hours`、`--period`） |
| `scripts/ecs_stats.py` | 资源 / 流量 / 费用汇总；实例停机后仍可用（`--with-eip`、`--month`、`--billing`） |
| `scripts/ecs_report.py` | 渲染 Markdown 实例报告 |
| `references/ecs-vpn-ops.md` | WireGuard 服务端搭建与稳定性笔记 |

报告把 ECS / CloudMonitor / CDT / BSS 的事实整理成八节（概览、规格与存储、网络、
资源使用、流量与免费额度、费用、规则化风险、数据来源）。两条刻意的约定：缺失值一律
写成 `—` 或注明缺失原因，**不会被悄悄当成 0**；每一节都写明数据来自哪个 API。它不会
启动、停止或改动任何东西。

```bash
python scripts/ecs_report.py --instance i-xxxxxxxx --region ap-northeast-1 \
    --with-eip --billing --out reports

# 也可以直接打印，或取 JSON 原始采集结果
python scripts/ecs_report.py --instance i-xxxxxxxx --region ap-northeast-1 --stdout
python scripts/ecs_report.py --instance i-xxxxxxxx --region ap-northeast-1 --json
```

## 包含的 skill

| Skill | 内容 |
|---|---|
| `alibabacloud-workbench-cli` | `SKILL.md`（用法、参数、生命周期与监控、报告、故障排查）、`references/ram-policies.md`（CLI 所需角色对应的 RAM 策略）、`references/ecs-vpn-ops.md`，以及四个辅助脚本 |

## 使用示例

> "Use `alibabacloud-workbench-cli` to run this command on the target instance."
>
> "用 `alibabacloud-workbench-cli` 给 i-xxxxxxxx 生成一份 ECS 实例报告。"

## 与上游的差异（本地改动）

- `SKILL.md` 保留了上游正文，但改了三处：frontmatter 的 `description` 被改写（让 DSH
  的 skill 目录按用户语言显示）、在 `## Exit Codes` 之前插入了两节
  （`### 10.` 生命周期与监控、`### 11.` 报告）、末尾追加了一行故障排查与
  `## DeepSeek Harness notes` 说明段。
- 打包后的 `SKILL.md`：19911 字节。上游文件 13062 字节（sha256 `5554809f…f4c2a9`），
  差额正是上述本地新增。
- `references/ram-policies.md`（1550 字节）是未经改动的上游副本；
  `references/ecs-vpn-ops.md`（2867 字节）与 `scripts/` 下全部文件都是本地新增。
- DSH 说明段记录了与上游假设的真实偏离：CLI 在本机是以
  `tools\workbench\workbench.exe` 便携方式调用，而不是 `PATH` 上的 `workbench`；
  沙箱无法写 `~\.workbench\`；`list`、`config` 在沙箱内可用，而 `exec`、`upload`、
  `download`、`connect` 需要沙箱外的后台守护进程。
- 上游是**单体仓库**：`skills/developertools/solutions/` 下约 200 个 skill、561 个
  按 skill 命名的 tag。本包只跟踪 `alibabacloud-workbench-cli-` 前缀，并且只装那一个
  目录，所以 `0.0.1` 是这个 skill 自己的版本线，不是仓库的版本。
- 预发布 tag（`-beta.N`、`-rc.N`）在 `skill-sync` 查找上游最新版本时会被跳过，
  因此 beta 不会触发更新。

## 许可证

skill 内容：Apache-2.0——见 [LICENSE](LICENSE) 与
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。上游仓库根目录没有 `LICENSE`
文件；许可声明来自该 skill 自己的 frontmatter 与所处项目的公开许可。
