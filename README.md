# alibabacloud-workbench-cli-skill-dsh

DeepSeek Harness skill bundle (bundle version 0.0.1) for the Alibaba Cloud
Workbench CLI skill in
[aliyun/alibabacloud-aiops-skills](https://github.com/aliyun/alibabacloud-aiops-skills).

[中文说明](README.zh.md)

It packages one model-callable DSH skill, `alibabacloud-workbench-cli`, rebuilt
from the upstream tag `alibabacloud-workbench-cli-0.0.1`
(`skills/developertools/solutions/alibabacloud-workbench-cli/`) and extended
locally. Skill-only bundle: no hooks, no native tools, no install scripts.

**The CLI itself is not part of this bundle.** `workbench` is an external
dependency the user installs separately (upstream's documentation covers the
official installer); nothing in this package downloads, ships or updates that
binary. The bundle contains skill text and dependency-free helper scripts only.

## What the skill does

Upstream's part: connecting to a target instance, running commands over the
session channel, uploading and downloading files, managing credentials and
profiles, and recovering from the error codes the CLI reports. The upstream text
is written for a generic Linux shell; the DSH notes at the end of `SKILL.md` map
that onto this host.

Local extensions on top of upstream — all read-only, all reading the same
AccessKey as the CLI (`~/.workbench/config.json`), none of them needing a
third-party package:

| Extension | What it adds |
|---|---|
| `### 10. Instance lifecycle & monitoring` | start / stop / status and CloudMonitor metrics, which `workbench` has no commands for |
| `### 11. Instance reports` | the one-command instance report described below |
| `scripts/ecs_instance.py` | `status` / `start` / `stop` through the ECS OpenAPI (`--wait`, `stop --yes`, `--stop-mode`, `--report`) |
| `scripts/ecs_metrics.py` | point queries against CloudMonitor (`--metric`, `--hours`, `--period`) |
| `scripts/ecs_stats.py` | resource / traffic / billing summary; works on a stopped instance (`--with-eip`, `--month`, `--billing`) |
| `scripts/ecs_report.py` | renders the Markdown instance report |
| `references/ecs-vpn-ops.md` | WireGuard server setup and stability notes |

The report collects ECS / CloudMonitor / CDT / BSS facts into eight sections
(overview, spec & storage, network, resource usage, traffic & free quota,
billing, rule-based risks, data provenance). Two conventions are deliberate: a
missing value is printed as `—` or with the reason it is missing rather than as
0, and every section names the API it came from. It never starts, stops or
changes anything.

```bash
python scripts/ecs_report.py --instance i-xxxxxxxx --region ap-northeast-1 \
    --with-eip --billing --out reports

# or print it, or get the raw collection as JSON
python scripts/ecs_report.py --instance i-xxxxxxxx --region ap-northeast-1 --stdout
python scripts/ecs_report.py --instance i-xxxxxxxx --region ap-northeast-1 --json
```

## Skills

| Skill | Contents |
|---|---|
| `alibabacloud-workbench-cli` | `SKILL.md` (usage, options, lifecycle & monitoring, reports, troubleshooting), `references/ram-policies.md` (the RAM policy the CLI's roles need), `references/ecs-vpn-ops.md`, and four helper scripts |

## Usage

> "Use `alibabacloud-workbench-cli` to run this command on the target instance."
>
> "Use `alibabacloud-workbench-cli` to write an ECS instance report for i-xxxxxxxx."

## Local modifications relative to upstream

- `SKILL.md` keeps upstream's body but changes three things: the frontmatter
  `description` is rewritten (so a DSH skill catalog reads it in the user's
  language), two sections are inserted before `## Exit Codes`
  (`### 10.` lifecycle & monitoring, `### 11.` reports), and one troubleshooting
  row plus the `## DeepSeek Harness notes` section are appended at the end.
- Bundled `SKILL.md`: 19911 bytes. Upstream's file is 13062 bytes (sha256
  `5554809f…f4c2a9`); the difference is exactly those local additions.
- `references/ram-policies.md` (1550 bytes) is an untouched upstream copy.
  `references/ecs-vpn-ops.md` (2867 bytes) and everything under `scripts/` are
  local files.
- The DSH notes record the real deviations from upstream's assumptions: the CLI
  is used as a portable `tools\workbench\workbench.exe` instead of `workbench`
  on `PATH`, the sandbox cannot write `~\.workbench\`, and `list`/`config` work
  inside the sandbox while `exec`, `upload`, `download` and `connect` need the
  background daemon outside it.
- Upstream is a **monorepo**: ~200 skills under `skills/developertools/solutions/`
  and 561 tags, one per skill. This bundle tracks only the
  `alibabacloud-workbench-cli-` tag prefix and ships only that one directory, so
  the `0.0.1` version line is the skill's own — not the repository's.
- Pre-release tags (`-beta.N`, `-rc.N`) are skipped when `skill-sync` looks for
  the newest upstream release, so a beta never triggers an update.

## Licence

Skill content: Apache-2.0 — see [LICENSE](LICENSE) and
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Upstream's repository root
carries no `LICENSE` file; the licence statement comes from the skill's own
frontmatter and from the well-known licence of the surrounding project.
