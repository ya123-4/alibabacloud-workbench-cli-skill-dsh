# alibabacloud-workbench-cli-skill-dsh

DeepSeek Harness skill bundle (bundle version 0.0.1) for the Alibaba Cloud
Workbench CLI skill in
[aliyun/alibabacloud-aiops-skills](https://github.com/aliyun/alibabacloud-aiops-skills).

[中文说明](README.zh.md)

It packages one model-callable DSH skill, `alibabacloud-workbench-cli`, rebuilt
from the upstream tag `alibabacloud-workbench-cli-0.0.1`
(`skills/developertools/solutions/alibabacloud-workbench-cli/`). Skill-only
bundle: no hooks, no native tools, no install scripts.

**The CLI itself is not part of this bundle.** `workbench` is an external
dependency the user installs separately (upstream's documentation covers the
official installer); nothing in this package downloads, ships or updates that
binary. The bundle contains skill text only.

## What the skill does

It teaches the Alibaba Cloud Workbench CLI: connecting to a target instance,
running commands over the session channel, uploading and downloading files,
managing credentials and profiles, and recovering from the error codes the CLI
reports. The upstream text is written for a generic Linux shell; see the DSH
notes below for how that maps onto this host.

## Skills

| Skill | Contents |
|---|---|
| `alibabacloud-workbench-cli` | `SKILL.md` (usage, options, troubleshooting table) plus `references/ram-policies.md` (the RAM policy the CLI's roles need) |

## Usage

> "Use `alibabacloud-workbench-cli` to run this command on the target instance."
>
> "Use `alibabacloud-workbench-cli` to look up which RAM policy the workbench role needs."

## DeepSeek Harness notes

- The bundle **vendors upstream byte for byte** and then appends exactly one
  section, `## DeepSeek Harness notes`, after the last row of upstream's
  Troubleshooting table. That note is the bundle's only local modification; its
  text lives in `recipes/overlays/alibabacloud-workbench-cli/dsh-notes.txt` in
  the `skill-sync-dsh` bundle, not inside this package.
- Bundled `SKILL.md`: 14354 bytes, sha256 `46f807f6…c483fe` — upstream's 13062
  bytes (sha256 `5554809f…f4c2a9`) plus the 1292-byte note.
  `references/ram-policies.md` (1550 bytes) is an untouched copy.
- The note names the one real deviation from upstream's assumptions: the CLI is
  used as a portable `tools\workbench\workbench.exe` instead of `workbench` on
  `PATH`, the sandbox cannot write `~\.workbench\`, and `list`/`config` work
  inside the sandbox while `exec`, `upload`, `download` and `connect` need the
  background daemon outside it.
- Upstream is a **monorepo**: ~200 skills under `skills/developertools/solutions/`
  and 561 tags, one per skill. This bundle tracks only the
  `alibabacloud-workbench-cli-` tag prefix and ships only that one directory, so
  the 0.0.1 version line below is the skill's own — not the repository's.
- `-beta.N` tags of the same skill exist upstream and are deliberately not
  tracked: `check` compares the newest matching tag, so a beta never triggers an
  update.

## Licence

Skill content: Apache-2.0 — see [LICENSE](LICENSE) and
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Upstream's repository root
carries no `LICENSE` file; the licence statement comes from the skill's own
frontmatter and from the well-known licence of the surrounding project.
