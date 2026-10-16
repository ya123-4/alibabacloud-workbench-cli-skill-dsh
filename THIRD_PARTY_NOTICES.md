# Third-Party Notices

The skill content in this package is copied from the Alibaba Cloud AIOps Skills
monorepo:

- Project: Alibaba Cloud AIOps Skills
- Repository: https://github.com/aliyun/alibabacloud-aiops-skills
- Revision: tag `alibabacloud-workbench-cli-0.0.1`
- Source directory: `skills/developertools/solutions/alibabacloud-workbench-cli/`
- Licence: Apache-2.0

The repository root carries **no `LICENSE` file**. The licence statement above
comes from the skill's own frontmatter (`license: Apache-2.0` in upstream
`SKILL.md`), which is the per-skill licence declaration this monorepo uses.

Upstream files taken, unmodified:

| File | Size | SHA-256 |
|---|---|---|
| `SKILL.md` | 13062 bytes | `5554809f5c7fbeb57500315fc7750960328585027bd9a78e10c01a1979f4c2a9` |
| `references/ram-policies.md` | 1550 bytes | `78da22ca4367dc44c4b07b8bf4c35271713e4859a59745a1f190a3fd0b370d13` |

## Local modifications

Exactly one, and it is deliberate:

- `skills/alibabacloud-workbench-cli/SKILL.md` gains a section headed
  `## DeepSeek Harness notes`, appended after the last row of upstream's
  Troubleshooting table. Its text lives in the `skill-sync-dsh` bundle at
  `skills/skill-sync/scripts/recipes/overlays/alibabacloud-workbench-cli/dsh-notes.txt`.
  The bundled file is therefore 14354 bytes, sha256
  `46f807f6bec32418355ad6f7b3e6917a532150be11b4364060041b98f8c483fe`
  (upstream's 13062 bytes plus the 1292-byte note, with everything before the
  note byte-identical to upstream).

Nothing else differs: `references/ram-policies.md` and every other byte of
`SKILL.md` are upstream's.

## Not bundled

- Only the one directory above ships. The other ~200 skills of the monorepo, and
  the repository's own documentation, CI configuration and tooling, are not part
  of this package.
- **The Workbench CLI binary itself is not part of this package.** It is an
  external dependency the user installs separately (upstream's installer writes
  `%ProgramFiles%\workbench` and edits the user `PATH`); the bundle ships skill
  text only and never downloads, repackages or updates that binary.
- Upstream `-beta.N` tags of the same skill are not tracked. This bundle follows
  the `alibabacloud-workbench-cli-` release line only.

Apache-2.0 is reproduced in full in `LICENSE` at the package root.
