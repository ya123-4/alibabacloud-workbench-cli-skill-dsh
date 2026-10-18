---
name: alibabacloud-workbench-cli
description: '面向 agent 的 CLI，用于管理没有公网 IP 的 ECS 实例，主要面向单实例操作。支持毫秒级远程命令执行、最大 1GB 的文件传输和 TCP 端口转发，提供四种认证方式：AK、RamRoleArn、CredentialsCmd 和 CredentialsURI。可用它执行命令、部署代码、查看日志、检查进程、传输文件、配置端口转发，或查询和筛选 ECS 实例列表。'
license: Apache-2.0
metadata:
  domain: cloud-infrastructure
compatibility: Requires workbench CLI binary installed. Cross-platform Linux/macOS (amd64/arm64), Windows (amd64). Network access to *.aliyuncs.com and Workbench backend WebSocket endpoints required.
allowed-tools: Bash
---

# Workbench CLI Expert

Help users operate Alibaba Cloud ECS instances — especially those **without public IP addresses** — using the `workbench` command-line tool. Core capabilities for Agent workflows: millisecond-level remote command execution (`exec`), file transfer up to 1GB (`upload`/`download`), and port forwarding. This skill covers: install → configure credentials → exec/transfer/forward → manage sessions → troubleshoot errors.

## Instructions

### 1. Install the Workbench CLI

**Pre-check:**

```bash
workbench version     # Should print version, commit, build date
```

**Linux / macOS:**

```bash
curl -fsSL https://workbench-cli.oss-cn-hangzhou.aliyuncs.com/install.sh | bash
```

**Windows (PowerShell):**

```powershell
irm https://workbench-cli.oss-cn-hangzhou.aliyuncs.com/install.ps1 | iex
```

**Upgrade:**

```bash
workbench upgrade                        # Upgrade to latest
workbench upgrade --version 0.2.0        # Upgrade to specific version
```

### 2. Configure credentials

Credentials are stored in `~/.workbench/config.json` with `0600` permissions. As an Agent, write this file directly instead of using the interactive `workbench config` command.

```bash
# Create config directory
mkdir -p ~/.workbench

# Write config file (example: AK mode)
cat > ~/.workbench/config.json << 'EOF'
{
  "current": "default",
  "profiles": {
    "default": {
      "mode": "AK",
      "access_key_id": "<AccessKeyID>",
      "access_key_secret": "<AccessKeySecret>"
    }
  }
}
EOF

# Set secure permissions
chmod 600 ~/.workbench/config.json
```

**Config file schema by mode:**

AK mode:
```json
{
  "current": "default",
  "profiles": {
    "default": {
      "mode": "AK",
      "access_key_id": "LTAI...",
      "access_key_secret": "..."
    }
  }
}
```

RamRoleArn mode (auto-refreshes STS tokens):
```json
{
  "current": "default",
  "profiles": {
    "default": {
      "mode": "RamRoleArn",
      "access_key_id": "LTAI...",
      "access_key_secret": "...",
      "ram_role_arn": "acs:ram::123456789:role/WorkbenchRole",
      "role_session_name": "workbench-session"
    }
  }
}
```

CredentialsURI mode (HTTP endpoint returns credentials):
```json
{
  "current": "default",
  "profiles": {
    "default": {
      "mode": "CredentialsURI",
      "credentials_uri": "http://localhost:8080/credentials"
    }
  }
}
```

| Mode | When to use |
| --- | --- |
| **AK** (default) | Development, long-lived credentials |
| **StsToken** | Temporary security credentials (AccessKey + STS Token) |
| **RamRoleArn** | Production, cross-account, least-privilege via STS role assumption (auto-refreshes tokens) |
| **CredentialsCmd** | Zero-trust / Vault integration — external command outputs credential JSON |
| **CredentialsURI** | Metadata service / sidecar — HTTP endpoint returns credential JSON |

**Profile management (non-interactive):**

```bash
workbench config list                     # List all profiles (* marks active)
workbench config switch --profile prod    # Switch active profile
workbench config get                      # Show current profile details (JSON)
workbench config get --profile prod       # Show specific profile details
workbench config delete --profile old     # Delete a profile (cannot delete active)
```

### 3. Command reference

```
workbench
├── exec             # Execute remote command (non-interactive, millisecond-level)
├── upload           # Upload local file to instance (up to 1GB, via OSS relay)
├── download         # Download file from instance (up to 1GB, via OSS relay)
├── list             # List ECS instances
├── session          # Session management (list / close)
├── daemon           # Daemon lifecycle (start / status / stop)
├── config           # Credential configuration & profile management
│   ├── set          # Set a single config field
│   ├── list         # List all profiles
│   ├── switch       # Switch active profile
│   ├── get          # Show profile details
│   └── delete       # Delete a profile
├── upgrade          # Self-update
└── version          # Print version info
```

**Global flags:**

| Flag | Purpose | Default |
| --- | --- | --- |
| `--output` / `-o` | Output format: `text|json` | `text` |
| `--region` / `-r` | Alibaba Cloud region (e.g., `cn-hangzhou`) | auto-inferred from instance ID prefix |
| `--profile` / `-P` | Use a specific profile (overrides active profile) | current active profile |

### 4. List instances

```bash
workbench list ecs --region cn-hangzhou
workbench list ecs --region cn-hangzhou --status Running
workbench list ecs --region cn-hangzhou --tag env=prod --tag team=infra
workbench list ecs --region cn-hangzhou --instance-type ecs.g7.large
workbench list ecs --region cn-hangzhou --instance-name my-instance
workbench list ecs --region cn-hangzhou --image-id ubuntu_22_04_x64_20G_alibase_20230907.vhd
workbench list ecs --region cn-hangzhou --output json
```

`--region` is **required** for `list ecs`. Filters: `--status` (Running|Stopped|Starting|Stopping), `--tag` (key=value or key, repeatable, AND logic), `--instance-type` (e.g. ecs.g7.large), `--instance-name` (supports wildcards `*`), `--image-id`, `--vpc-id`, `--zone-id`, `--vswitch-id`, `--private-ip` (comma-separated), `--limit` (1-100, default 50), `--next-token` (pagination).

JSON output schema:

```json
[{
  "instance_id": "i-bp1xxxxx",
  "instance_name": "web-prod-01",
  "instance_type": "ecs.g7.large",
  "region_id": "cn-hangzhou",
  "status": "Running",
  "private_ip": "172.16.0.10",
  "public_ip": "",
  "os_type": "linux",
  "image_id": "ubuntu_22_04_x64_20G_alibase_20230907.vhd",
  "tags": {"env": "prod"}
}]
```

### 5. Remote command execution

**Built-in safety**: The CLI is a non-interactive executor — it does NOT provide a persistent shell. Each invocation is isolated and stateless, which prevents accidental cascading damage from lingering shell sessions.

**Agent pre-check requirement**: Before executing destructive commands (e.g., `rm -rf`, `shutdown`, `reboot`, `mkfs`, `dd`, service stop/restart, or any command that deletes data or halts the system), the Agent MUST confirm with the user by describing the intended action, the target instance, and the potential impact. Do NOT execute destructive commands without explicit user approval.

```bash
workbench exec --instance-id i-bp1xxxxx --command "df -h"
workbench exec --instance-id i-bp1xxxxx --command "sleep 30" --timeout 10
workbench exec --instance-id i-bp1xxxxx --command "df -h" --output json
```

| Flag | Required | Description | Default |
| --- | --- | --- | --- |
| `--instance-id` / `-i` | Yes | ECS instance ID | — |
| `--command` / `-c` | Yes | Command to execute | — |
| `--timeout` | No | Timeout in seconds | `30` |

**Important**: Each `exec` invocation runs in an independent shell context. State (cd, export) is NOT preserved between calls. Use `&&` or `;` to chain commands that need shared context in a single invocation.

JSON output schema:

```json
{
  "output": "Filesystem ...\n",
  "stderr": "",
  "exit_code": 0
}
```

### 6. File transfer

**Built-in safety**: The `upload` command has a built-in overwrite protection. When the remote destination file already exists, the CLI prompts for confirmation before overwriting:

```
Remote file "/root/id.txt" already exists (728 B, modified Jul 27 10:42). Overwrite? [y/N]
```

The default answer is **No** — if the user does not explicitly confirm, the upload is aborted. This prevents accidental overwriting of existing remote files.

**Agent pre-check requirement**: When using `upload` in automated/Agent workflows where interactive confirmation is not possible, the Agent MUST first check whether the target file exists on the remote instance (e.g., via `workbench exec --command "ls -la <path>"`) and inform the user if a file will be overwritten.

```bash
workbench upload ./app.jar /opt/app/app.jar --instance-id i-bp1xxxxx
workbench download /var/log/app.log ./ --instance-id i-bp1xxxxx
workbench download /var/log/app.log /tmp/local-copy.log --instance-id i-bp1xxxxx
```

Transfer goes through OSS as intermediary — transparent to the user, no OSS configuration needed. `download` second arg (local-path) is optional, defaults to current directory.

### 7. Session management

```bash
workbench session list
workbench session list --output json
workbench session close <session-id>
workbench session close --all
```

**Session lifecycle**: OPEN → RECONNECTING → BROKEN → CLOSED. Idle timeout 30min → auto CLOSED. Multiple operations on same instance share one session (transparent multiplexing).

### 8. Daemon management

```bash
workbench daemon start      # Manual start (usually not needed)
workbench daemon status
workbench daemon stop       # Closes all sessions
```

- **Auto-start**: Spawned on first CLI invocation.
- **Auto-exit**: 60 seconds after last session closes.
- **Singleton**: One per OS user (PID file lock).
- **IPC**: JSON-RPC over Unix socket (`~/.workbench/run/daemon.sock`).

### 9. Region inference

The CLI auto-infers region from the instance ID 3-character prefix (covers 290+ regions). If inference fails, `--region` is required. For `list` command, `--region` is always required.

### 10. Instance lifecycle & monitoring (ECS OpenAPI)

`workbench` has no start/stop/metrics commands — use the ECS and CloudMonitor OpenAPI directly. The plugin ships three dependency-free scripts under `scripts/` (they read the same AK from `~/.workbench/config.json`):

```bash
# status / start / stop (stop needs --yes; both accept --wait)
python scripts/ecs_instance.py status --instance i-xxxxxxxx --region ap-northeast-1
python scripts/ecs_instance.py start  --instance i-xxxxxxxx --region ap-northeast-1 --wait
python scripts/ecs_instance.py stop   --instance i-xxxxxxxx --region ap-northeast-1 --wait --yes

# CloudMonitor metrics (CPU, bandwidth, ...)
python scripts/ecs_metrics.py --instance i-xxxxxxxx --region ap-northeast-1 \
    --metric CPUUtilization --hours 3 --period 300 --limit 12

# post-stop stats: CPU avg/peak + intranet/internet traffic totals
# (works on a stopped instance too — CloudMonitor keeps historical points)
python scripts/ecs_stats.py --instance i-xxxxxxxx --region ap-northeast-1 --hours 6

# same + EIP bandwidth / packet rates / rate-limit drops (auto-detects the bound EIP)
python scripts/ecs_stats.py --instance i-xxxxxxxx --region ap-northeast-1 --hours 6 --with-eip

# month-to-date EIP outbound traffic + free-quota status (used / remaining / over)
python scripts/ecs_stats.py --instance i-xxxxxxxx --region ap-northeast-1 --month --free-quota-gb 220

# account balance + yesterday spend + month-to-date spend (BSS OpenAPI)
python scripts/ecs_stats.py --billing

# stop and print the stats in one shot
python scripts/ecs_instance.py stop --instance i-xxxxxxxx --region ap-northeast-1 --wait --yes --report
```

Notes:

- Required RAM actions: `ecs:DescribeInstances`, `ecs:StartInstance`, `ecs:StopInstance`, plus `cms:DescribeMetricList` (or `AliyunCloudMonitorReadOnlyAccess`). A missing CloudMonitor grant returns `403 NoPermission`.
- `StartInstance` on an already-Running instance succeeds as a no-op — useful as a safe permission probe.
- Spot instances may fail to start with `InsufficientSpotCapacity`; that is capacity, not permission.
- After a start, Cloud Assistant needs a few seconds before `workbench exec` succeeds.
- `stop --stop-mode` defaults to `StopCharging` (节省停机模式: no vCPU/memory charge; disk/EIP still billed). Use `KeepCharging` when the instance must stay resumable. `stop --report` prints the CloudMonitor summary after stopping.
- `--month` uses the CDT OpenAPI `ListCdtInternetTraffic` (version **2021-08-13**) — the same numbers as the CDT console — and falls back to CloudMonitor `net.tx` Sum only if the CDT call fails. Free quota (since 2025-06-01): 20 GB/month mainland China, 200 GB/month elsewhere; picked by region prefix, override with `--free-quota-gb`. Requires `cdt:ListCdtInternetTraffic`.
- `--billing` uses BSS OpenAPI `QueryAccountBalance` and `QueryAccountBill` (`Granularity=DAILY` + `BillingDate` for yesterday); requires BSS read permission such as `AliyunBSSReadOnlyAccess`.
- All scripts take `--region` (or `ECS_REGION`) because they cannot infer it from the instance id; `workbench` itself infers it from the id prefix.

See `references/ecs-vpn-ops.md` for WireGuard server setup and stability troubleshooting notes.

### 11. Instance reports

`workbench` has no reporting command either. `scripts/ecs_report.py` collects one instance's
facts from ECS / CloudMonitor / CDT / BSS and renders a Markdown report. It is **read-only**:
only `Describe*` / `Query*` / `List*` calls are made, so it never starts, stops or changes
anything — and it still works on a stopped instance, from CloudMonitor's historical points.

```bash
# default: last 24h of metrics, writes ./ECS-实例报告-<name>-<YYYYMMDD-HHmm>.md
python scripts/ecs_report.py --instance i-xxxxxxxx --region ap-northeast-1

# EIP detail + account billing, 72h window, print instead of writing a file
python scripts/ecs_report.py --instance i-xxxxxxxx --region ap-northeast-1 \
    --with-eip --billing --hours 72 --stdout

# machine-readable collection for downstream processing
python scripts/ecs_report.py --instance i-xxxxxxxx --region ap-northeast-1 --json
```

Eight sections: overview, spec & storage, network (with an EIP drill-down), resource usage,
public traffic & free quota, account billing, rule-based risks and suggestions, and data
provenance. Two conventions are deliberate: a missing value is printed as `—` or with the
reason it is missing (**never silently 0**), and every section names the API it came from.
`--out DIR` chooses the output directory; `--json` skips rendering entirely.

Two risk rules are worth knowing because both are easy to get wrong by hand: an instance with
`InternetMaxBandwidthOut=0` can still reach the internet through a bound EIP (the report warns
only when there is no EIP either), and the instance-level public-bandwidth metrics are a
different dimension from EIP bandwidth — the report says so instead of implying zero traffic.

## Exit Codes

| Code | Constant | Trigger |
| --- | --- | --- |
| **0** | `ExitSuccess` | Successful execution |
| **1** | `ExitGeneral` | Unclassified runtime error (includes instance not found, API errors, etc.) |
| **2** | `ExitArgument` | Missing, malformed, or invalid flag value |
| **3** | `ExitSessionNotFound` | Session ID invalid or expired |
| **4** | `ExitAuth` | Authentication or authorization failed |
| **5** | `ExitNetwork` | Network timeout, WebSocket exception |
| **6** | `ExitDaemonUnreach` | Local daemon not running or socket invalid |
| **7** | `ExitSessionBusy` | Session attached by another TTY |
| **N** | *(exec only)* | `exec` transparently passes through the remote command's exit code |

Error JSON output (on failure with `--output json`):

```json
{
  "code": 1,
  "message": "InvalidParameter.InstanceId: the specified instance does not exist"
}
```

## RAM Permissions

Minimum RAM policy required:

```json
{
  "Version": "1",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ecs-workbench:LoginECSInstance",
        "ecs-workbench:ChatMessages"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "ecs:DescribeInstances",
        "ecs:DescribeCloudAssistantStatus",
        "ecs:StartTerminalSession"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": "ram:CreateServiceLinkedRole",
      "Resource": "*",
      "Condition": {
        "StringEquals": {
          "ram:ServiceName": "workbench.ecs.aliyuncs.com"
        }
      }
    }
  ]
}
```

Restrict to specific instances: replace `"Resource": "*"` in each statement with the corresponding format:
- ecs-workbench:LoginECSInstance : `acs:ecs:<region>:<account-id>:ecs/<instance-id>`
- ecs actions: `acs:ecs:<region>:<account-id>:instance/<instance-id>`

## Troubleshooting

| Error message pattern | Exit Code | First Action |
| --- | --- | --- |
| `InvalidAccessKeyId` / authentication errors | 4 | Verify AK/SK in `~/.workbench/config.json`. Re-run `workbench config`. |
| `profile not found` | 1 | Check profile name with `workbench config list`. |
| `not found in <region>` / instance not found | 1 | Verify instance ID and region. Use `workbench list --region <region>` to confirm. |
| Network timeout / WebSocket errors | 5 | Check network connectivity to `*.aliyuncs.com`. Verify security group rules. |
| Session busy / attach errors | 7 | Another terminal is attached. Close it first, or use `workbench session close <id>`. |
| `cannot start daemon` / socket errors | 6 | Run `workbench daemon status`. If stopped, any command will auto-restart it. |
| Permission denied (RAM) | 4 | Attach the RAM policy from `## RAM Permissions` to the user or role. |
| `insecure permissions` | 2 | Run `chmod 600 ~/.workbench/config.json`. |
| STS token expired | 4 | If using `RamRoleArn` mode, the CLI auto-refreshes. If using static STS, update the token. |
| `CloudAssistantInvokeTimeout` / `ExecutionTimeout` from `exec` | 1 | Workbench's login helper runs `acs-plugin-manager -e -P config_ecs_instance_connect --params --install` under a 10s Cloud Assistant timeout. On some VPCs `service.axt.aliyuncs.com` resolves to the unreachable `100.100.100.10`, costing 2×5s so the command lands right at the limit. Fix: add `127.0.0.1 service.axt.aliyuncs.com` to the instance's `/etc/hosts` (back up first) so the probe fails fast and falls back to the regional endpoint (`<region>.axt.aliyun.com`). Verify with `RunCommand`, `tcpdump`, and logs under `/usr/local/share/aliyun-assist/<ver>/log/`. |

## DeepSeek Harness notes

This skill was written for a generic Linux shell. In DeepSeek Harness on this host:

1. **The CLI is portable, not on PATH.** Run `tools\workbench\workbench.exe` from the workspace.
   The official installer writes `%ProgramFiles%\workbench` and appends to the *user PATH registry
   value* — do not run it unless the human asks.
2. **Credentials** live in `~\.workbench\config.json` (mode `AK`). The DSH sandbox cannot write the
   home directory: to change that file, ask for a one-shot permission escalation, or pass
   `ALIBABA_CLOUD_ACCESS_KEY_ID` / `ALIBABA_CLOUD_ACCESS_KEY_SECRET` for the single invocation.
3. **`list` and `config` work inside the sandbox; `exec`, `upload`, `download` and `connect` do not.**
   Those need the background daemon, which requires `~/.workbench/run` to be writable and its IPC
   pipe to be reachable; inside the sandbox the daemon reports `self-dial check failed` /
   `Access is denied`. Run them with a one-shot permission escalation, or from a terminal outside
   DeepSeek Harness. Do not retry in a loop when it fails this way.
4. **Destructive commands still require explicit human approval** — `rm -rf`, `shutdown`, `reboot`,
   `mkfs`, `dd`, service stop/restart. State the target instance and the impact first.
