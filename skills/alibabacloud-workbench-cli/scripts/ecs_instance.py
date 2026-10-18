#!/usr/bin/env python3
"""Start / stop / query an Alibaba Cloud ECS instance via OpenAPI RPC (no SDK).

Uses the same AccessKey as the workbench CLI (~/.workbench/config.json).

Usage:
  python ecs_instance.py status --instance i-xxxxxxxx --region ap-northeast-1
  python ecs_instance.py start  --instance i-xxxxxxxx --region ap-northeast-1 --wait
  python ecs_instance.py stop   --instance i-xxxxxxxx --region ap-northeast-1 --wait --yes

Exit codes: 0 success, 1 API/runtime error, 2 usage error.
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
from datetime import datetime, timezone

CONFIG = os.path.join(os.path.expanduser("~"), ".workbench", "config.json")


def load_credentials():
    with open(CONFIG, encoding="utf-8") as f:
        cfg = json.load(f)
    prof = cfg["profiles"][cfg.get("current", "default")]
    return prof["access_key_id"], prof["access_key_secret"]


def pe(s):
    return urllib.parse.quote(str(s), safe="~")


def call(ak, sk, region, action, extra, timeout=20):
    params = {
        "Action": action, "Version": "2014-05-26", "Format": "JSON",
        "RegionId": region, "AccessKeyId": ak,
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
    url = "https://ecs.{}.aliyuncs.com/?{}&Signature={}".format(region, canon, pe(sig))
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        return json.loads(urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            return json.loads(body)
        except Exception:
            return {"__http_error": e.code, "body": body[:500]}


def instance_status(ak, sk, region, instance):
    r = call(ak, sk, region, "DescribeInstances", {"InstanceIds": json.dumps([instance])})
    try:
        return r["Instances"]["Instance"][0]["Status"]
    except Exception:
        raise SystemExit("DescribeInstances failed: " + json.dumps(r, ensure_ascii=False)[:500])


def wait_for(ak, sk, region, instance, target, timeout=300, interval=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        s = instance_status(ak, sk, region, instance)
        print("  status: {}".format(s))
        if s == target:
            return True
        time.sleep(interval)
    return False


def _stats(instance, region):
    print("\n== CloudMonitor stats ==")
    try:
        import ecs_stats
        ecs_stats.report(instance, region, with_eip=True)
    except Exception as e:  # noqa: BLE001
        print("stats unavailable: {}".format(e))


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("action", choices=["status", "start", "stop"])
    ap.add_argument("--instance", required=True, help="ECS instance id, e.g. i-bp1xxxx")
    ap.add_argument("--region", default=os.environ.get("ECS_REGION"),
                    help="region id, e.g. ap-northeast-1 (or set ECS_REGION)")
    ap.add_argument("--wait", action="store_true", help="wait until target status is reached")
    ap.add_argument("--yes", action="store_true", help="confirm a destructive action (stop)")
    ap.add_argument("--stop-mode", choices=["StopCharging", "KeepCharging"], default="StopCharging",
                    help="StopInstance mode: StopCharging = cost-saving stop (default, no vCPU/mem charge), "
                         "KeepCharging = keep resources charged")
    ap.add_argument("--report", action="store_true",
                    help="after stop, print CloudMonitor stats (CPU / traffic)")
    args = ap.parse_args()

    if not args.region:
        print("ERROR: --region is required (or set ECS_REGION)", file=sys.stderr)
        return 2
    if args.action == "stop" and not args.yes:
        print("REFUSED: stop needs --yes (it halts the instance).", file=sys.stderr)
        return 2

    ak, sk = load_credentials()
    print("instance: {} | region: {}".format(args.instance, args.region))
    cur = instance_status(ak, sk, args.region, args.instance)
    print("current status: {}".format(cur))

    if args.action == "status":
        return 0

    action = "StartInstance" if args.action == "start" else "StopInstance"
    if (args.action == "start" and cur == "Running") or (args.action == "stop" and cur == "Stopped"):
        print("already in target state, nothing to do")
        if args.report:
            _stats(args.instance, args.region)
        return 0

    extra = {"InstanceId": args.instance}
    if action == "StopInstance":
        extra["StoppedMode"] = args.stop_mode
    r = call(ak, sk, args.region, action, extra)
    if "__http_error" in r or "__error" in r:
        print("{} failed: {}".format(action, json.dumps(r, ensure_ascii=False)[:500]), file=sys.stderr)
        return 1
    print("{} accepted, request id: {}".format(action, r.get("RequestId")))

    if args.wait:
        target = "Running" if args.action == "start" else "Stopped"
        print("waiting for {}...".format(target))
        if not wait_for(ak, sk, args.region, args.instance, target):
            print("TIMEOUT waiting for {}".format(target), file=sys.stderr)
            return 1
        print("done: {}".format(target))
    if args.report and args.action == "stop":
        _stats(args.instance, args.region)
    return 0


if __name__ == "__main__":
    sys.exit(main())
