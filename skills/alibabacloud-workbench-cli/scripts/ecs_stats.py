#!/usr/bin/env python3
"""Summarize CloudMonitor stats for an ECS instance (works while running AND after stop).

Usage:
  python ecs_stats.py --instance i-xxxxxxxx --region ap-northeast-1 \
      [--hours 6] [--period 300] [--with-eip] [--free-quota-gb 220] [--month] [--json]

ECS metrics (namespace acs_ecs_dashboard):
  CPUUtilization, IntranetInRate, IntranetOutRate, InternetInRate, InternetOutRate

EIP metrics (namespace acs_vpc_eip, with --with-eip; auto-detected from the instance):
  net_tx.rate / net_rx.rate (bit/s), packet rates and rate-limit drops,
  plus month-to-date outbound traffic from the net.tx "Sum" field.

Free quota:
  CDT (Cloud Data Transfer) public-traffic free quota differs per account/plan.
  Set it explicitly with --free-quota-gb (default 220). The script reports
  used / remaining / over for the current Beijing month.

Historical points remain queryable after the instance stops.
"""
import argparse
import base64
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone

CONFIG = os.path.join(os.path.expanduser("~"), ".workbench", "config.json")
METRIC_ENDPOINT = "metrics.aliyuncs.com"
# CDT grant since 2025-06-01: 20 GB/month for mainland China, 200 GB/month elsewhere
FREE_QUOTA_MAINLAND_GB = 20.0
FREE_QUOTA_OVERSEAS_GB = 200.0
DEFAULT_FREE_QUOTA_GB = FREE_QUOTA_OVERSEAS_GB


def default_free_quota_gb(region):
    return FREE_QUOTA_MAINLAND_GB if region and region.startswith("cn-") else FREE_QUOTA_OVERSEAS_GB


def load_credentials():
    with open(CONFIG, encoding="utf-8") as f:
        cfg = json.load(f)
    prof = cfg["profiles"][cfg.get("current", "default")]
    return prof["access_key_id"], prof["access_key_secret"]


def pe(s):
    return urllib.parse.quote(str(s), safe="~")


def call(ak, sk, endpoint, version, extra, timeout=25, retries=2):
    params = {
        "Version": version, "Format": "JSON", "AccessKeyId": ak,
        "SignatureMethod": "HMAC-SHA1", "SignatureVersion": "1.0",
        "SignatureNonce": str(uuid.uuid4()),
        "Timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    params.update(extra)
    canon = "&".join(f"{pe(k)}={pe(v)}" for k, v in sorted(params.items()))
    sts = "GET&" + pe("/") + "&" + pe(canon)
    sig = base64.b64encode(
        hmac.new((sk + "&").encode(), sts.encode(), hashlib.sha1).digest()
    ).decode()
    url = "https://{}/?{}&Signature={}".format(endpoint, canon, pe(sig))
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    last = None
    for attempt in range(retries + 1):
        try:
            return json.loads(urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            try:
                return json.loads(body)
            except Exception:
                last = {"__http_error": e.code, "body": body[:300]}
        except Exception as e:  # noqa: BLE001
            last = {"__error": type(e).__name__, "detail": str(e)[:150]}
        if attempt < retries:
            time.sleep(2)
    return last


def value_of(p):
    for k in ("Average", "Value", "Maximum", "Minimum"):
        if k in p:
            try:
                return float(p[k])
            except (TypeError, ValueError):
                pass
    return None


def fetch(ak, sk, region, metric, hours, period, dims, namespace="acs_ecs_dashboard"):
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=hours)
    extra = {
        "Action": "DescribeMetricList",
        "Namespace": namespace,
        "MetricName": metric,
        "Dimensions": json.dumps(dims),
        "Period": str(period),
        "StartTime": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "EndTime": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "RegionId": region,
    }
    r = call(ak, sk, METRIC_ENDPOINT, "2019-01-01", extra)
    if "Datapoints" not in r:
        return None, r
    pts = json.loads(r.get("Datapoints") or "[]")
    vals = [value_of(p) for p in pts]
    return [v for v in vals if v is not None], None


def fetch_sum(ak, sk, region, eip_id, metric, start, end, period):
    """Sum the 'Sum' field (bytes per period) of a metric over [start, end]."""
    token = None
    total = 0.0
    points = 0
    pages = 0
    while True:
        extra = {
            "Action": "DescribeMetricList", "Namespace": "acs_vpc_eip",
            "MetricName": metric, "Dimensions": json.dumps([{"instanceId": eip_id}]),
            "Period": str(period),
            "StartTime": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "EndTime": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "RegionId": region,
        }
        if token:
            extra["NextToken"] = token
        r = call(ak, sk, METRIC_ENDPOINT, "2019-01-01", extra)
        if "Datapoints" not in r:
            return None, r, points
        pts = json.loads(r.get("Datapoints") or "[]")
        for p in pts:
            s = p.get("Sum")
            if s is not None:
                total += float(s)
                points += 1
        token = r.get("NextToken")
        pages += 1
        if not token or pages > 40:
            break
    return total, None, points


def month_start_utc():
    now = datetime.now(timezone.utc)
    local = now + timedelta(hours=8)
    start_local = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return start_local - timedelta(hours=8), now


def month_out_bytes(ak, sk, region, eip_id):
    """Month-to-date EIP outbound bytes.

    Uses 1h granularity for the older part and 5min for the last 2 days
    (5min points are only retained ~2 days).
    """
    start, end = month_start_utc()
    split = max(start, end - timedelta(days=2))
    total = 0.0
    parts = []
    if start < split:
        t, err, n = fetch_sum(ak, sk, region, eip_id, "net.tx", start, split, 3600)
        if t is None:
            return None, err
        total += t
        parts.append(("1h", n))
    t, err, n = fetch_sum(ak, sk, region, eip_id, "net.tx", split, end, 300)
    if t is None:
        return None, err
    total += t
    parts.append(("5m", n))
    return total / 1024 ** 3, parts


def get_eip(ak, sk, region, instance):
    r = call(ak, sk, "ecs.{}.aliyuncs.com".format(region), "2014-05-26", {
        "Action": "DescribeInstances", "RegionId": region,
        "InstanceIds": json.dumps([instance]),
    })
    try:
        inst = r["Instances"]["Instance"][0]
    except Exception:
        return None
    eip = inst.get("EipAddress") or {}
    if not eip.get("AllocationId"):
        return None
    return {"allocation_id": eip["AllocationId"], "ip": eip.get("IpAddress") or ""}


def print_metric(name, vals, period, unit, scale=1.0, show_total=False, err=None):
    if vals is None:
        print("  {:<24} unavailable: {}".format(name, json.dumps(err, ensure_ascii=False)[:100]))
        return {"available": False, "error": err}
    if not vals:
        print("  {:<24} no data points".format(name))
        return {"available": True, "points": 0}
    avg = sum(vals) / len(vals)
    peak = max(vals)
    total = sum(vals) * period / 8.0 / 1024 / 1024
    line = "  {:<24} points={:<3} avg={:>10.3f} peak={:>10.3f}".format(
        name, len(vals), avg / scale, peak / scale)
    if show_total:
        line += " total≈{:>8.1f} MB".format(total)
    line += "  [{}]".format(unit)
    print(line)
    out = {"available": True, "points": len(vals), "avg": round(avg / scale, 3),
           "peak": round(peak / scale, 3), "unit": unit}
    if show_total:
        out["total_mb"] = round(total, 1)
    return out


CDT_ENDPOINT = "cdt.aliyuncs.com"
CDT_VERSION = "2021-08-13"


def cdt_month_groups(ak, sk):
    """Authoritative CDT month-to-date traffic (same numbers as the CDT console).

    Returns ({bucket: {"bytes": float, "regions": {rid: {"bytes", "products"}}}}, None)
    or (None, error).
    """
    r = call(ak, sk, CDT_ENDPOINT, CDT_VERSION,
             {"Action": "ListCdtInternetTraffic", "PageNumber": "1", "PageSize": "100"})
    if "TrafficDetails" not in r:
        return None, r
    groups = {}
    for d in r.get("TrafficDetails") or []:
        rid = d.get("BusinessRegionId") or ""
        bucket = "cn" if rid.startswith("cn-") else "overseas"
        total = float(d.get("Traffic") or 0)
        g = groups.setdefault(bucket, {"bytes": 0.0, "regions": {}})
        g["bytes"] += total
        products = {}
        for pt in d.get("ProductTrafficDetails") or []:
            name = pt.get("Product")
            products[name] = products.get(name, 0.0) + float(pt.get("Traffic") or 0)
        g["regions"][rid] = {"bytes": total, "products": products}
    return groups, None


def print_month(ak, sk, region, eip_id, free_quota_gb):
    groups, err = cdt_month_groups(ak, sk)
    if groups is not None:
        print("  source: CDT OpenAPI ListCdtInternetTraffic (authoritative, matches console)")
        cur_bucket = "cn" if (region or "").startswith("cn-") else "overseas"
        result = {"source": "cdt", "groups": {}}
        for bucket in ("overseas", "cn"):
            g = groups.get(bucket)
            if not g:
                continue
            used = g["bytes"] / 1024 ** 3
            default_quota = FREE_QUOTA_OVERSEAS_GB if bucket == "overseas" else FREE_QUOTA_MAINLAND_GB
            quota = free_quota_gb if bucket == cur_bucket else default_quota
            remaining = max(0.0, quota - used)
            over = max(0.0, used - quota)
            label = "overseas (non-cn)" if bucket == "overseas" else "mainland china"
            print("  {:<16}: used {:.5f} GiB | quota {:.0f} GiB | remaining {:.3f} GiB | over {:.3f} GiB".format(
                label, used, quota, remaining, over))
            for rid, info in g["regions"].items():
                prods = ", ".join("{}={:.3f}".format(p, b / 1024 ** 3)
                                  for p, b in info["products"].items())
                print("    {}: total {:.5f} GiB ({} )".format(
                    rid, info["bytes"] / 1024 ** 3, prods))
            result["groups"][bucket] = {"used_gib": round(used, 5), "quota_gib": quota,
                                        "remaining_gib": round(remaining, 3),
                                        "over_gib": round(over, 3)}
        return result

    print("  source: CloudMonitor estimate (CDT API unavailable: {})".format(
        json.dumps(err, ensure_ascii=False)[:120]))
    gb, detail = month_out_bytes(ak, sk, region, eip_id)
    if gb is None:
        print("  month-to-date: unavailable: {}".format(json.dumps(detail, ensure_ascii=False)[:150]))
        return {"available": False, "error": detail}
    remaining = max(0.0, free_quota_gb - gb)
    over = max(0.0, gb - free_quota_gb)
    print("  month-to-date outbound : {:.3f} GB".format(gb))
    print("  free quota             : {:.1f} GB".format(free_quota_gb))
    print("  remaining              : {:.3f} GB".format(remaining))
    print("  over quota             : {:.3f} GB".format(over))
    return {"available": True, "used_gb": round(gb, 3), "free_quota_gb": free_quota_gb,
            "remaining_gb": round(remaining, 3), "over_gb": round(over, 3),
            "parts": detail}


def bss_call(ak, sk, action, extra):
    return call(ak, sk, "business.aliyuncs.com", "2017-12-14", dict(extra, Action=action))


def billing_stats(ak, sk):
    """Account balance + yesterday spend + month-to-date spend (BSS OpenAPI)."""
    now_local = datetime.now(timezone(timedelta(hours=8)))
    cycle = now_local.strftime("%Y-%m")
    yesterday = (now_local - timedelta(days=1)).strftime("%Y-%m-%d")
    result = {"cycle": cycle, "yesterday": yesterday}

    bal = bss_call(ak, sk, "QueryAccountBalance", {})
    data = bal.get("Data", {}) or {}
    result["balance"] = {
        "available": data.get("AvailableAmount"),
        "cash": data.get("AvailableCashAmount"),
        "currency": data.get("Currency", "CNY"),
    }

    def day_bill(day):
        r = bss_call(ak, sk, "QueryAccountBill", {
            "BillingCycle": cycle, "BillingDate": day, "Granularity": "DAILY",
            "PageNum": "1", "PageSize": "100"})
        items = ((r.get("Data", {}) or {}).get("Items", {}) or {}).get("Item", []) or []
        gross = sum(float(i.get("PretaxGrossAmount") or 0) for i in items)
        pretax = sum(float(i.get("PretaxAmount") or 0) for i in items)
        return round(gross, 6), round(pretax, 6)

    g, p = day_bill(yesterday)
    result["yesterday_spend"] = {"gross": g, "pretax": p}

    r = bss_call(ak, sk, "QueryAccountBill", {"BillingCycle": cycle, "PageNum": "1", "PageSize": "100"})
    items = ((r.get("Data", {}) or {}).get("Items", {}) or {}).get("Item", []) or []
    result["month_spend"] = {
        "gross": round(sum(float(i.get("PretaxGrossAmount") or 0) for i in items), 6),
        "pretax": round(sum(float(i.get("PretaxAmount") or 0) for i in items), 6),
    }
    return result


def print_billing(ak, sk):
    b = billing_stats(ak, sk)
    print("== billing (BSS OpenAPI) ==")
    print("  balance (available)   : {} {}".format(b["balance"]["available"], b["balance"]["currency"]))
    print("  yesterday {}          : {} CNY (gross {})".format(
        b["yesterday"], b["yesterday_spend"]["pretax"], b["yesterday_spend"]["gross"]))
    print("  month {}              : {} CNY (gross {})".format(
        b["cycle"], b["month_spend"]["pretax"], b["month_spend"]["gross"]))
    return b


def report(instance, region, hours=6.0, period=300, as_json=False,
           with_eip=False, free_quota_gb=DEFAULT_FREE_QUOTA_GB):
    ak, sk = load_credentials()
    result = {"instance": instance, "region": region, "hours": hours, "period": period,
              "metrics": {}, "eip": None, "month": None}
    dims = [{"instanceId": instance}]

    def add(name, unit, scale, show_total):
        vals, err = fetch(ak, sk, region, name, hours, period, dims)
        result["metrics"][name] = print_metric(name, vals, period, unit, scale, show_total, err)

    print("instance {} | region {} | last {}h @ {}s".format(instance, region, hours, period))
    add("CPUUtilization", "%", 1.0, False)
    add("IntranetInRate", "Mbit/s", 1e6, True)
    add("IntranetOutRate", "Mbit/s", 1e6, True)
    add("InternetInRate", "Mbit/s", 1e6, True)
    add("InternetOutRate", "Mbit/s", 1e6, True)

    if with_eip:
        eip = get_eip(ak, sk, region, instance)
        if not eip:
            print("== no EIP bound to this instance ==")
            result["eip"] = {"bound": False}
        else:
            print("== EIP {} ({}) ==".format(eip["allocation_id"], eip["ip"]))
            edims = [{"instanceId": eip["allocation_id"]}]
            result["eip"] = {"bound": True, "allocation_id": eip["allocation_id"],
                             "ip": eip["ip"], "metrics": {}}
            for name, unit, scale in [
                ("net_tx.rate", "Mbit/s", 1e6),
                ("net_rx.rate", "Mbit/s", 1e6),
                ("net_txPkgs.rate", "pps", 1.0),
                ("net_rxPkgs.rate", "pps", 1.0),
                ("out_ratelimit_drop_speed", "pps", 1.0),
                ("in_ratelimit_drop_speed", "pps", 1.0),
            ]:
                vals, err = fetch(ak, sk, region, name, hours, period, edims, "acs_vpc_eip")
                result["eip"]["metrics"][name] = print_metric(
                    name, vals, period, unit, scale, False, err)
            print("== month-to-date traffic ==")
            result["month"] = print_month(ak, sk, region, eip["allocation_id"], free_quota_gb)

    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def month_only(instance, region, free_quota_gb, as_json):
    ak, sk = load_credentials()
    eip = get_eip(ak, sk, region, instance)
    if not eip:
        print("no EIP bound to instance {}".format(instance))
        return {"bound": False}
    print("instance {} | EIP {} ({})".format(instance, eip["allocation_id"], eip["ip"]))
    month = print_month(ak, sk, region, eip["allocation_id"], free_quota_gb)
    if as_json:
        print(json.dumps({"instance": instance, "eip": eip["allocation_id"], "month": month},
                         ensure_ascii=False, indent=2))
    return month


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--instance", default=None)
    ap.add_argument("--region", default=os.environ.get("ECS_REGION"), help="or set ECS_REGION")
    ap.add_argument("--hours", type=float, default=6.0)
    ap.add_argument("--period", type=int, default=300, choices=[60, 300, 900, 3600])
    ap.add_argument("--with-eip", action="store_true",
                    help="also report EIP metrics + month-to-date traffic")
    ap.add_argument("--free-quota-gb", type=float, default=None,
                    help="CDT free quota in GB (default: 20 for cn-* regions, 200 elsewhere)")
    ap.add_argument("--month", action="store_true",
                    help="only print month-to-date EIP traffic + free quota status")
    ap.add_argument("--billing", action="store_true",
                    help="show account balance, yesterday spend and month-to-date spend (BSS OpenAPI)")
    ap.add_argument("--json", action="store_true", help="emit JSON")
    args = ap.parse_args()

    quota = args.free_quota_gb if args.free_quota_gb is not None else default_free_quota_gb(args.region)

    if args.billing:
        print_billing(*load_credentials())
        if not (args.month or args.with_eip):
            return 0

    if args.month:
        if not (args.instance and args.region):
            print("ERROR: --month needs --instance and --region", file=sys.stderr)
            return 2
        month_only(args.instance, args.region, quota, args.json)
        return 0

    if not (args.instance and args.region):
        print("ERROR: --instance and --region are required", file=sys.stderr)
        return 2
    report(args.instance, args.region, args.hours, args.period, args.json,
           args.with_eip, quota)
    return 0


if __name__ == "__main__":
    sys.exit(main())
