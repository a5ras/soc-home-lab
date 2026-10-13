#!/usr/bin/env python3
import json
from collections import defaultdict
from datetime import datetime

ALERTS = "/var/ossec/logs/alerts/alerts.json"
WINDOW = 600
THRESHOLD = 3
SUCCESS_WINDOW = 3600


def get_ip(alert):
    data = alert.get("data", {})
    return data.get("srcip") or data.get("src_ip")


def parse_time(ts):
    return datetime.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S")


by_ip = defaultdict(list)
with open(ALERTS, errors="ignore") as f:
    for line in f:
        try:
            alert = json.loads(line)
        except ValueError:
            continue

        rule_id = alert["rule"]["id"]
        groups = alert["rule"].get("groups", [])
        desc = alert["rule"]["description"]

        if rule_id == "86601":
            kind = "SCAN"
        elif "sshd" in groups:
            kind = "SSH_OK" if "success" in desc.lower() else "SSH_FAIL"
        else:
            continue

        ip = get_ip(alert)
        if ip is None:
            continue

        by_ip[ip].append((parse_time(alert["timestamp"]), kind))

for ip, evs in by_ip.items():
    evs.sort()
    scans = [t for t, k in evs if k == "SCAN"]
    fails = [t for t, k in evs if k == "SSH_FAIL"]
    oks = [t for t, k in evs if k == "SSH_OK"]

    found_any = False
    for s in scans:
        after = [t for t in fails if 0 <= (t - s).total_seconds() <= WINDOW]
        if len(after) < THRESHOLD:
            continue

        last_fail = max(after)
        wins = [t for t in oks if 0 <= (t - last_fail).total_seconds() <= SUCCESS_WINDOW]

        found_any = True
        if wins:
            print("BREACH STORY from", ip)
        else:
            print("ATTACK STORY from", ip)
        print("  1. scan at", s)
        print("  2.", len(after), "failed SSH logins within", WINDOW, "seconds")
        if wins:
            print("  3. successful login at", wins[0])

    if not found_any:
        print("no story for", ip)
