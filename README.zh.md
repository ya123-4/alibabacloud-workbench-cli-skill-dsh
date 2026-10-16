# alibabacloud-workbench-cli-skill-dsh（中文说明）

[aliyun/alibabacloud-aiops-skills](https://github.com/aliyun/alibabacloud-aiops-skills)
里 Alibaba Cloud Workbench CLI 这个 skill 的 DeepSeek Harness 插件包（bundle 版本 0.0.1）。

[English](README.md)

它把上游 tag `alibabacloud-workbench-cli-0.0.1`
（`skills/developertools/solutions/alibabacloud-workbench-cli/`）重建为一个可由
模型调用的 DSH skill：`alibabacloud-workbench-cli`。纯 skill 插件——不含 hooks、
不含原生工具、不含安装脚本。

**CLI 本身不在本包里。** `workbench` 是需要用户另行安装的外部依赖（安装方式见上游
文档）；本包不会下载、分发或升级那个二进制，包里只有 skill 文本。

## 这个 skill 做什么

它讲清楚 Alibaba Cloud Workbench CLI 的用法：连接目标实例、通过会话通道执行命令、
上传下载文件、管理凭证与 profile，以及 CLI 报出各类错误码后的处理办法。上游正文是按
通用 Linux shell 写的；映射到本机的差异见下面的 DSH 说明。

## 包含的 skill

| Skill | 内容 |
|---|---|
| `alibabacloud-workbench-cli` | `SKILL.md`（用法、参数、故障排查表）与 `references/ram-policies.md`（CLI 所需角色对应的 RAM 策略） |

## 使用示例

> "Use `alibabacloud-workbench-cli` to run this command on the target instance."
>
> "Use `alibabacloud-workbench-cli` to look up which RAM policy the workbench role needs."

## DeepSeek Harness 适配说明

- 本包**逐字节原样**装载上游内容，只在上游故障排查表最后一行之后追加一节
  `## DeepSeek Harness notes`。这是本包唯一的本地改动；该段文本位于 `skill-sync-dsh`
  插件的 `recipes/overlays/alibabacloud-workbench-cli/dsh-notes.txt`，不在本包内。
- 打包后的 `SKILL.md`：14354 字节，sha256 `46f807f6…c483fe`——上游 13062 字节
  （sha256 `5554809f…f4c2a9`）加上 1292 字节的说明段。`references/ram-policies.md`
  （1550 字节）是未经改动的副本。
- 说明段写明了与上游假设的唯一实质偏离：CLI 在本机是以 `tools\workbench\workbench.exe`
  便携方式调用，而不是 `PATH` 上的 `workbench`；沙箱无法写 `~\.workbench\`；
  `list`、`config` 在沙箱内可用，而 `exec`、`upload`、`download`、`connect` 需要
  沙箱外的后台守护进程。
- 上游是**单体仓库**：`skills/developertools/solutions/` 下约 200 个 skill、561 个
  按 skill 命名的 tag。本包只跟踪 `alibabacloud-workbench-cli-` 前缀，并且只装那一个
  目录，所以下面的 0.0.1 是这个 skill 自己的版本线，不是仓库的版本。
- 同一 skill 上游还有 `-beta.N` tag，本包**有意不跟**：`check` 比较的是匹配前缀的
  最新 tag，beta 永远不会触发更新。

## 许可证

skill 内容：Apache-2.0——见 [LICENSE](LICENSE) 与
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。上游仓库根目录没有 `LICENSE`
文件；许可声明来自该 skill 自己的 frontmatter 与所处项目的公开许可。
