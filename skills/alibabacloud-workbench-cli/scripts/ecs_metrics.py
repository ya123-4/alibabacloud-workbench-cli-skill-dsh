#!/usr/bin/env python3
"""Query CloudMonitor metrics for an ECS instance (OpenAPI RPC, no SDK).

Uses the same AccessKey as the workbench CLI (~/.workbench/config.json).

Usage:
  python ecs_metrics.py --instance i-xxxxxxxx --region ap-northeast-1 \
      --metric CPUUtilization --hours 3 --period 300 --limit 12

Common metrics (namespace acs_ecs_dashboard):
  CPUUtilization, MemoryUtilization,
  InternetOutRate / InternetInRate (bit/s),
  IntranetOutRate / IntranetInRate,
  DiskReadBPS / DiskWriteBPS

Note: metrics.aliyuncs.com occasionally times out from some hosts; this script retries.
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
ENDPOINT = "metrics.aliyuncs.com"


def load_credentials():
    with open(CONFIG, encoding="utf-8") as f:
        cfg = json.load(f)
    prof = cfg["profiles"][cfg.get("current", "default")]
    return prof["access_key_id"], prof["access_key_secret"]


def pe(s):
    return urllib.parse.quote(str(s), safe="~")


def call(ak, sk, extra, timeout=25, retries=2):
    params = {
        "Version": "2019-01-01", "Format": "JSON", "AccessKeyId": ak,
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
    url = "https://{}/?{}&Signature={}".format(ENDPOINT, canon, pe(sig))
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
                last = {"__http_error": e.code, "body": body[:400]}
        except Exception as e:  # noqa: BLE001
            last = {"__error": type(e).__name__, "detail": str(e)[:200]}
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
    skip = {"timestamp", "instanceId", "userId", "ownerId", "accountId",
            "region", "namespace", "metricName", "dimensions"}
    for k, v in p.items():
        if k in skip:
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    return None


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--instance", required=True)
    ap.add_argument("--region", default=os.environ.get("ECS_REGION"), help="or set ECS_REGION")
    ap.add_argument("--metric", default="CPUUtilization")
    ap.add_argument("--namespace", default="acs_ecs_dashboard")
    ap.add_argument("--hours", type=float, default=3.0)
    ap.add_argument("--period", type=int, default=300, choices=[60, 300, 900, 3600])
    ap.add_argument("--limit", type=int, default=12, help="show last N points")
    args = ap.parse_args()

    if not args.region:
        print("ERROR: --region is required (or set ECS_REGION)", file=sys.stderr)
        return 2

    ak, sk = load_credentials()
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=args.hours)
    r = call(ak, sk, {
        "Action": "DescribeMetricList",
        "Namespace": args.namespace,
        "MetricName": args.metric,
        "Dimensions": json.dumps([{"instanceId": args.instance}]),
        "Period": str(args.period),
        "StartTime": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "EndTime": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "RegionId": args.region,
    })
    if "Datapoints" not in r:
        print("query failed: {}".format(json.dumps(r, ensure_ascii=False)[:500]), file=sys.stderr)
        return 1

    pts = json.loads(r.get("Datapoints") or "[]")
    print("metric: {} | points: {}".format(args.metric, len(pts)))
    shown = pts[-args.limit:] if args.limit > 0 else pts
    for p in shown:
        ts = p.get("timestamp")
        try:
            when = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
        except (TypeError, ValueError):
            when = str(ts)
        print("  {:<20} {}".format(when, value_of(p)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
