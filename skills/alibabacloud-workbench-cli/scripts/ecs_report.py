#!/usr/bin/env python3
"""Generate a Markdown report for one Alibaba Cloud ECS instance (read-only).

Usage:
  python ecs_report.py --instance i-xxxxxxxx --region ap-northeast-1 \
      [--hours 24] [--period 300] [--with-eip] [--billing] \
      [--out DIR] [--stdout] [--json]

What it collects:
  * identity / spec / network / tags   -- ECS DescribeInstances
  * storage layout                     -- ECS DescribeDisks
  * security groups                    -- ECS DescribeSecurityGroups
  * resource usage (last N hours)      -- CloudMonitor DescribeMetricList
  * EIP detail (--with-eip)            -- ECS DescribeEipAddresses
  * traffic + free quota               -- CDT ListCdtInternetTraffic (falls back to CloudMonitor)
  * account billing (--billing)        -- BSS QueryAccountBalance / QueryAccountBill
  * rule-based risks and suggestions

Safety: only Describe*/Query*/List* calls are made. This script never starts, stops,
reboots or otherwise changes the instance. Metrics are historical, so a stopped
instance still reports its last points.

Exit codes: 0 success, 1 API/runtime error, 2 usage error.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ecs_stats import (  # noqa: E402  (sibling module, same directory)
    FREE_QUOTA_MAINLAND_GB,
    FREE_QUOTA_OVERSEAS_GB,
    billing_stats,
    call,
    cdt_month_groups,
    default_free_quota_gb,
    fetch,
    get_eip,
    load_credentials,
)

ECS_VERSION = "2014-05-26"
ECST = "ecs.{}.aliyuncs.com"
STATUS_HINT = {
    "Running": "运行中",
    "Stopped": "已停止",
    "Starting": "启动中",
    "Stopping": "停止中",
}


# ---------------------------------------------------------------- helpers
def utcnow():
    return datetime.now(timezone.utc)


def local_str(moment):
    return moment.astimezone(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")


def ecs_api(ak, sk, region, action, **params):
    extra = {"Action": action, "RegionId": region}
    extra.update(params)
    return call(ak, sk, ECST.format(region), ECS_VERSION, extra)


def gib(value):
    try:
        return "{:.2f} GiB".format(float(value) / 1024 ** 3)
    except (TypeError, ValueError):
        return "—"


def mbit(value):
    """bit/s -> Mbit/s."""
    try:
        return "{:.2f} Mbit/s".format(float(value) / 1e6)
    except (TypeError, ValueError):
        return "—"


def pct(value):
    try:
        return "{:.1f}%".format(float(value))
    except (TypeError, ValueError):
        return "—"


def stat(vals):
    if not vals:
        return None
    return {"avg": sum(vals) / len(vals), "min": min(vals), "max": max(vals), "n": len(vals)}


def cell(value, fallback="—"):
    if value in (None, "", {}, []):
        return fallback
    return value


# ---------------------------------------------------------------- collection
def collect_instance(ak, sk, region, instance_id):
    r = ecs_api(ak, sk, region, "DescribeInstances",
                InstanceIds=json.dumps([instance_id]))
    items = ((r.get("Instances") or {}).get("Instance") or [])
    if not items:
        return None, r
    return items[0], None


def collect_disks(ak, sk, region, instance_id):
    r = ecs_api(ak, sk, region, "DescribeDisks", InstanceId=instance_id)
    if "Disks" not in r:
        return None, r
    return (r["Disks"] or {}).get("Disk") or [], None


def collect_security_groups(ak, sk, region, group_ids):
    if not group_ids:
        return [], None
    r = ecs_api(ak, sk, region, "DescribeSecurityGroups",
                SecurityGroupIds=json.dumps(group_ids))
    if "SecurityGroups" not in r:
        return None, r
    return (r["SecurityGroups"] or {}).get("SecurityGroup") or [], None


def collect_eip_detail(ak, sk, region, allocation_id):
    if not allocation_id:
        return None, None
    r = ecs_api(ak, sk, region, "DescribeEipAddresses",
                AllocationId=allocation_id)
    if "EipAddresses" not in r:
        return None, r
    items = (r["EipAddresses"] or {}).get("EipAddress") or []
    return (items[0] if items else None), None


def collect_metrics(ak, sk, region, instance_id, hours, period):
    dims = [{"instanceId": instance_id}]
    wanted = {
        "CPUUtilization": "%",
        "MemoryUtilization": "%",
        "IntranetInRate": "bit/s",
        "IntranetOutRate": "bit/s",
        "InternetInRate": "bit/s",
        "InternetOutRate": "bit/s",
    }
    out = {}
    for name in wanted:
        vals, err = fetch(ak, sk, region, name, hours, period, dims)
        out[name] = {"points": stat(vals), "error": err}
    return out


def collect_traffic(ak, sk, region):
    groups, err = cdt_month_groups(ak, sk)
    if groups is None:
        return {"available": False, "error": err}, None
    quota_overseas = FREE_QUOTA_OVERSEAS_GB
    quota_mainland = FREE_QUOTA_MAINLAND_GB
    result = {"available": True, "source": "CDT ListCdtInternetTraffic", "buckets": {}}
    for bucket, g in groups.items():
        used = g["bytes"] / 1024 ** 3
        quota = quota_overseas if bucket == "overseas" else quota_mainland
        result["buckets"][bucket] = {
            "used_gib": round(used, 5),
            "quota_gib": quota,
            "remaining_gib": round(max(0.0, quota - used), 3),
            "over_gib": round(max(0.0, used - quota), 3),
            "regions": {rid: round(info["bytes"] / 1024 ** 3, 5)
                        for rid, info in g["regions"].items()},
        }
    return result, None


def collect_billing(ak, sk):
    try:
        return billing_stats(ak, sk), None
    except Exception as exc:  # noqa: BLE001 - billing is optional
        return None, {"__error": type(exc).__name__, "detail": str(exc)[:200]}


# ---------------------------------------------------------------- risks
def derive_risks(inst, disks, metrics, traffic, eip_detail):
    risks = []

    status = inst.get("Status")
    if status == "Stopped":
        risks.append(("中", "实例已停止：计算不计费，但云盘与已绑定的 EIP 通常仍计费；长期不用建议释放或转按量。"))
    if (inst.get("InstanceChargeType") or "").lower() == "postpaid" and \
            (inst.get("SpotStrategy") or "").lower() in ("spotaspricego", "spotwithprice"):
        risks.append(("中", "抢占式（spot）实例：可能被系统回收，不适合承载不可中断的服务。"))
    expired = inst.get("ExpiredTime")
    if expired and not expired.startswith("2099"):
        risks.append(("中", "实例有到期时间 {}：到期未续费会停机/释放。".format(expired)))
    if not (inst.get("PublicIpAddress") or {}).get("IpAddress") and \
            not (inst.get("EipAddress") or {}).get("IpAddress"):
        risks.append(("低", "无公网 IP：外部访问需经 Workbench CLI 或跳板；这是该插件的主要使用场景。"))
    # InternetMaxBandwidthOut is the instance's *own* public-IP field. With an EIP bound it is
    # legitimately 0 and the EIP carries the bandwidth, so only warn when there is no EIP either.
    if str(inst.get("InternetMaxBandwidthOut") or "0") in ("0", "") and \
            not (inst.get("EipAddress") or {}).get("IpAddress"):
        risks.append(("低", "公网出带宽上限为 0 且未绑定 EIP：实例不能主动出公网，需要带宽或 NAT/EIP。"))

    cpu = (metrics.get("CPUUtilization") or {}).get("points")
    if cpu and cpu["max"] is not None:
        if cpu["max"] >= 80:
            risks.append(("中", "CPU 峰值 {:.1f}%：规格可能偏小，或存在突发负载。".format(cpu["max"])))
        elif cpu["max"] < 5 and status == "Running":
            risks.append(("低", "CPU 峰值 {:.1f}%：长期低负载，可考虑降配以省成本。".format(cpu["max"])))
    mem = (metrics.get("MemoryUtilization") or {}).get("points")
    if mem is None:
        risks.append(("低", "未取到内存使用率：需实例内安装 CloudMonitor 插件；CPU/带宽指标不受影响。"))

    unencrypted = [d for d in disks if str(d.get("Encrypted", "")).lower() in ("false", "")]
    if unencrypted:
        risks.append(("中", "{} 块云盘未加密：涉及敏感数据时建议启用云盘加密。".format(len(unencrypted))))

    for bucket, info in (traffic.get("buckets") or {}).items():
        if info["over_gib"] > 0:
            risks.append(("高", "{} 公网流量已超额 {:.3f} GiB（免费额度 {} GiB 用尽），将按量计费。".format(
                bucket, info["over_gib"], info["quota_gib"])))
        elif info["quota_gib"] and info["remaining_gib"] <= info["quota_gib"] * 0.2:
            risks.append(("中", "{} 公网流量剩余仅 {:.3f} GiB（额度 {} GiB），接近超额。".format(
                bucket, info["remaining_gib"], info["quota_gib"])))

    if not (inst.get("Tags") or {}).get("Tag"):
        risks.append(("低", "未打标签：成本归属与批量筛选会不清楚。"))
    if not risks:
        risks.append(("—", "未发现明显风险项。"))
    return risks


# ---------------------------------------------------------------- rendering
def render_markdown(inst, region, disks, groups, metrics, traffic, eip_detail, billing,
                    hours, period, collected_at):
    eip = inst.get("EipAddress") or {}
    tags = ((inst.get("Tags") or {}).get("Tag") or [])
    tag_text = ", ".join("{}={}".format(t.get("TagKey"), t.get("TagValue")) for t in tags) or "—"
    lines = []
    add = lines.append

    title_name = inst.get("InstanceName") or inst.get("InstanceId")
    add("# ECS 实例报告 — {}".format(title_name))
    add("")
    add("> 采集时间：{}（Asia/Shanghai）｜仅只读 API ｜数据来源 ECS / CloudMonitor / CDT / BSS"
        .format(local_str(collected_at)))
    add("")

    add("## 1. 概览")
    add("")
    add("| 项 | 值 |")
    add("| --- | --- |")
    for label, value in (
        ("实例 ID", inst.get("InstanceId")),
        ("名称", inst.get("InstanceName")),
        ("描述", inst.get("Description")),
        ("状态", "{} ({})".format(STATUS_HINT.get(inst.get("Status"), inst.get("Status")),
                                  inst.get("Status"))),
        ("地域 / 可用区", "{} / {}".format(inst.get("RegionId"), cell(inst.get("ZoneId")))),
        ("付费方式", cell(inst.get("InstanceChargeType"))),
        ("抢占策略", cell(inst.get("SpotStrategy"))),
        ("创建时间", cell(inst.get("CreationTime"))),
        ("最近启动", cell(inst.get("StartTime"))),
        ("到期时间", cell(inst.get("ExpiredTime"))),
        ("标签", tag_text),
    ):
        add("| {} | {} |".format(label, cell(value)))
    add("")

    add("## 2. 规格与存储")
    add("")
    add("| 项 | 值 |")
    add("| --- | --- |")
    add("| 实例规格 | {} |".format(cell(inst.get("InstanceType"))))
    add("| vCPU / 内存 | {} / {} MB |".format(cell(inst.get("Cpu")), cell(inst.get("Memory"))))
    add("| 操作系统 | {} |".format(cell(inst.get("OSName"))))
    add("| 镜像 | {} |".format(cell(inst.get("ImageId"))))
    add("")
    if disks:
        add("| 云盘 | 类型 | 容量 | 属性 | 状态 | 加密 |")
        add("| --- | --- | --- | --- | --- | --- |")
        for disk in disks:
            add("| {} | {} | {} GiB | {} | {} | {} |".format(
                cell(disk.get("DiskId")), cell(disk.get("Category")), cell(disk.get("Size")),
                cell(disk.get("Type")), cell(disk.get("Status")),
                "是" if str(disk.get("Encrypted", "")).lower() == "true" else "否"))
        add("")
    else:
        add("_未取到云盘列表。_")
        add("")

    add("## 3. 网络")
    add("")
    private_ips = ((inst.get("VpcAttributes") or {}).get("PrivateIpAddress") or {}).get("IpAddress") or []
    add("| 项 | 值 |")
    add("| --- | --- |")
    add("| 私网 IP | {} |".format(", ".join(private_ips) or cell(inst.get("PrivateIpAddress"))))
    add("| 公网 IP | {} |".format(cell((inst.get("PublicIpAddress") or {}).get("IpAddress"))))
    add("| EIP | {} |".format(cell(eip.get("IpAddress"))))
    add("| 公网出带宽上限 | {} Mbit/s |".format(cell(inst.get("InternetMaxBandwidthOut"))))
    add("| 公网计费方式 | {} |".format(cell(inst.get("InternetChargeType"))))
    add("| VPC / 交换机 | {} / {} |".format(
        cell((inst.get("VpcAttributes") or {}).get("VpcId")),
        cell((inst.get("VpcAttributes") or {}).get("VSwitchId"))))
    if groups:
        def sg_label(group):
            gid = group.get("SecurityGroupId", "?")
            name = group.get("SecurityGroupName")
            return "{} ({})".format(gid, name) if name and name != gid else gid
        sg_text = "; ".join(sg_label(g) for g in groups)
    else:
        sg_text = ", ".join(group_ids) or "—"
    add("| 安全组 | {} |".format(sg_text))
    add("")
    if eip_detail:
        add("| EIP 明细 | 值 |")
        add("| --- | --- |")
        add("| 分配 ID | {} |".format(cell(eip_detail.get("AllocationId"))))
        add("| 状态 / 计费 | {} / {} |".format(cell(eip_detail.get("Status")),
                                              cell(eip_detail.get("InternetChargeType"))))
        add("| 带宽 | {} Mbit/s |".format(cell(eip_detail.get("Bandwidth"))))
        add("| 分配时间 | {} |".format(cell(eip_detail.get("AllocationTime"))))
        add("")

    add("## 4. 资源使用（最近 {} 小时，采样 {} 秒）".format(hours, period))
    add("")
    add("| 指标 | 均值 | 峰值 | 采样点 | 备注 |")
    add("| --- | --- | --- | --- | --- |")
    rows = (
        ("CPUUtilization", "CPU 使用率", pct),
        ("MemoryUtilization", "内存使用率", pct),
        ("IntranetInRate", "内网入带宽", mbit),
        ("IntranetOutRate", "内网出带宽", mbit),
        ("InternetInRate", "公网入带宽", mbit),
        ("InternetOutRate", "公网出带宽", mbit),
    )
    for key, label, fmt in rows:
        entry = metrics.get(key) or {}
        points = entry.get("points")
        if points:
            add("| {} | {} | {} | {} | — |".format(
                label, fmt(points["avg"]), fmt(points["max"]), points["n"]))
        else:
            add("| {} | — | — | 0 | {} |".format(
                label, "无数据（指标未上报或实例无该维度数据）"))
    add("")
    if eip.get("IpAddress"):
        add("注：上表的公网带宽指标是实例自身公网 IP 的维度。本实例经 EIP `{}` 出网，"
            "EIP 带宽请见 §3（{}）。".format(
                eip.get("IpAddress"),
                "{} Mbit/s".format(cell((eip_detail or {}).get("Bandwidth")))
                if eip_detail else "加 `--with-eip` 查看"))
        add("")

    add("## 5. 公网流量与免费额度")
    add("")
    if traffic.get("available"):
        add("来源：{}".format(traffic.get("source")))
        add("")
        add("| 流量区 | 本月已用 | 免费额度 | 剩余 | 超额 |")
        add("| --- | --- | --- | --- | --- |")
        for bucket, info in traffic["buckets"].items():
            add("| {} | {:.5f} GiB | {} GiB | {:.3f} GiB | {:.3f} GiB |".format(
                "大陆" if bucket == "cn" else "海外", info["used_gib"],
                info["quota_gib"], info["remaining_gib"], info["over_gib"]))
            for rid, used in info["regions"].items():
                add("|  └ {} | {:.5f} GiB | | | |".format(rid, used))
        add("")
    else:
        add("_未取到流量数据：{}_".format(json.dumps(traffic.get("error"), ensure_ascii=False)[:200]))
        add("")

    add("## 6. 账户费用")
    add("")
    if billing:
        balance = billing.get("balance") or {}
        add("| 项 | 值 |")
        add("| --- | --- |")
        add("| 可用余额 | {} {} |".format(cell(balance.get("available")), cell(balance.get("currency"))))
        add("| 昨日消费（{}） | {} CNY |".format(
            billing.get("yesterday"), cell((billing.get("yesterday_spend") or {}).get("pretax"))))
        add("| 本月累计（{}） | {} CNY |".format(
            billing.get("cycle"), cell((billing.get("month_spend") or {}).get("pretax"))))
        add("")
    else:
        add("_未采集（加 `--billing` 可输出账户余额与消费）。_")
        add("")

    add("## 7. 风险与建议")
    add("")
    for level, text in derive_risks(inst, disks, metrics, traffic, eip_detail):
        add("- **{}** {}".format(level, text))
    add("")

    add("## 8. 数据来源与限制")
    add("")
    add("- 实例 / 云盘 / 安全组 / EIP：ECS OpenAPI `DescribeInstances`、`DescribeDisks`、"
        "`DescribeSecurityGroups`、`DescribeEipAddresses`（地域 `{}`）".format(region))
    add("- 资源使用：CloudMonitor `DescribeMetricList`，命名空间 `acs_ecs_dashboard`，"
        "窗口最近 {} 小时、周期 {} 秒；历史点保留有限，实例停机后仍可查询但不会更新。".format(hours, period))
    add("- 流量：CDT `ListCdtInternetTraffic`（权威值，与控制台一致）；不可用时回退 CloudMonitor 估算。")
    add("- 费用：BSS `QueryAccountBalance` / `QueryAccountBill`（账户级，非单实例账单）。")
    add("- 本报告为只读采集，未对实例做任何变更；缺失项以 `—` 或说明标注，**不等于 0**。")
    add("")
    return "\n".join(lines) + "\n"


def render_console(inst, region, traffic, collected_at):
    """One-screen summary printed when only a file is written."""
    eip = inst.get("EipAddress") or {}
    lines = [
        "ECS 实例报告已生成",
        "  实例    : {} ({})".format(inst.get("InstanceName") or "?", inst.get("InstanceId")),
        "  地域    : {}".format(region),
        "  状态    : {} / {}".format(inst.get("Status"), inst.get("InstanceType")),
        "  网络    : 私网 {} | 公网 {} | EIP {}".format(
            ((inst.get("VpcAttributes") or {}).get("PrivateIpAddress") or {}).get("IpAddress") or "—",
            (inst.get("PublicIpAddress") or {}).get("IpAddress") or "—",
            eip.get("IpAddress") or "—"),
        "  采集于  : {}".format(local_str(collected_at)),
    ]
    if traffic.get("available"):
        for bucket, info in traffic["buckets"].items():
            lines.append("  流量    : {} 本月 {:.3f}/{:.0f} GiB（剩余 {:.3f}）".format(
                "大陆" if bucket == "cn" else "海外",
                info["used_gib"], info["quota_gib"], info["remaining_gib"]))
    return "\n".join(lines)


# ---------------------------------------------------------------- main
def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Generate a read-only Markdown report for one ECS instance.")
    parser.add_argument("--instance", required=True, help="ECS instance id, e.g. i-xxxxxxxx")
    parser.add_argument("--region", default=None,
                        help="region id, e.g. ap-northeast-1 (or set ECS_REGION)")
    parser.add_argument("--hours", type=float, default=24.0, help="metric window in hours (default 24)")
    parser.add_argument("--period", type=int, default=300, help="metric period in seconds (default 300)")
    parser.add_argument("--with-eip", action="store_true", help="include EIP detail")
    parser.add_argument("--billing", action="store_true", help="include account billing")
    parser.add_argument("--out", default=".", help="output directory (default current)")
    parser.add_argument("--stdout", action="store_true", help="print the Markdown instead of writing")
    parser.add_argument("--json", action="store_true", help="print the collected data as JSON")
    args = parser.parse_args(argv)
    args.region = args.region or os.environ.get("ECS_REGION")
    if not args.region:
        parser.error("--region is required (or set ECS_REGION)")

    collected_at = utcnow()
    try:
        ak, sk = load_credentials()
    except Exception as exc:  # noqa: BLE001
        print("cannot read credentials from ~/.workbench/config.json: {}".format(exc),
              file=sys.stderr)
        return 2

    inst, err = collect_instance(ak, sk, args.region, args.instance)
    if inst is None:
        print("instance {} not found in {}: {}".format(
            args.instance, args.region, json.dumps(err, ensure_ascii=False)[:300]), file=sys.stderr)
        return 1

    disks, _ = collect_disks(ak, sk, args.region, args.instance)
    disks = disks or []
    group_ids = [g for g in (inst.get("SecurityGroupIds") or {}).get("SecurityGroupId") or []]
    groups, _ = collect_security_groups(ak, sk, args.region, group_ids)
    groups = groups or []
    eip_detail = None
    if args.with_eip:
        eip = inst.get("EipAddress") or {}
        eip_detail, _ = collect_eip_detail(ak, sk, args.region, eip.get("AllocationId"))

    metrics = collect_metrics(ak, sk, args.region, args.instance, args.hours, args.period)
    traffic, _ = collect_traffic(ak, sk, args.region)
    billing = collect_billing(ak, sk)[0] if args.billing else None

    if args.json:
        payload = {
            "collected_at": collected_at.isoformat(),
            "region": args.region,
            "hours": args.hours,
            "period": args.period,
            "instance": inst,
            "disks": disks,
            "security_groups": groups,
            "eip": eip_detail,
            "metrics": metrics,
            "traffic": traffic,
            "billing": billing,
            "risks": derive_risks(inst, disks, metrics, traffic, eip_detail),
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        return 0

    markdown = render_markdown(inst, args.region, disks, groups, metrics, traffic,
                               eip_detail, billing, args.hours, args.period, collected_at)
    if args.stdout:
        print(markdown)
        return 0

    out_dir = os.path.abspath(args.out)
    os.makedirs(out_dir, exist_ok=True)
    safe_name = "".join(c if c.isalnum() or c in "-_." else "_"
                        for c in (inst.get("InstanceName") or inst.get("InstanceId")))
    filename = "ECS-实例报告-{}-{}.md".format(
        safe_name, collected_at.astimezone(timezone(timedelta(hours=8))).strftime("%Y%m%d-%H%M"))
    path = os.path.join(out_dir, filename)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(markdown)
    print(render_console(inst, args.region, traffic, collected_at))
    print("  文件    : {}".format(path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
