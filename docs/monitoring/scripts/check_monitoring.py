#!/usr/bin/env python3
"""Dependency-free validation for VILTARA monitoring templates."""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {
    "ViltaraApiUnavailable": ("critical", "2m"),
    "ViltaraMiniAppUnavailable": ("critical", "3m"),
    "ViltaraBotUnhealthy": ("critical", "2m"),
    "ViltaraPostgresUnavailable": ("critical", "1m"),
    "ViltaraRedisUnavailable": ("critical", "1m"),
    "ViltaraHostDiskHigh": ("warning", "10m"),
    "ViltaraHostDiskCritical": ("critical", "5m"),
    "ViltaraPostgresStorageHigh": ("warning", "10m"),
    "ViltaraPostgresStorageCritical": ("critical", "5m"),
    "ViltaraBackupStale": ("critical", "5m"),
    "ViltaraBackupJobFailed": ("critical", "1m"),
    "ViltaraTlsCertificateExpiring": ("warning", "15m"),
    "ViltaraTlsCertificateCritical": ("critical", "5m"),
}
FORBIDDEN = re.compile(
    r"telegram[_ -]?id|wallet[_ -]?address|order[_ -]?id|payment[_ -]?id|"
    r"listing[_ -]?id|connection[_ -]?string|bot[_ -]?token|database_url|authorization",
    re.IGNORECASE,
)
SECRET_URL = re.compile(r"https?://[^\s'\"]*(?:token|secret|password|api[_-]?key)=[^\s'\"]+", re.I)


def parse_alerts(text: str) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    current: str | None = None
    for line in text.splitlines():
        match = re.match(r"^      - alert: ([A-Za-z0-9_]+)$", line)
        if match:
            current = match.group(1)
            if current in result:
                raise ValueError(f"duplicate alert rule: {current}")
            result[current] = {}
            continue
        if current:
            match = re.match(r"^        for: (\S+)$", line)
            if match:
                result[current]["for"] = match.group(1)
            match = re.match(r"^          severity: (warning|critical)$", line)
            if match:
                result[current]["severity"] = match.group(1)
    return result


def validate() -> int:
    rules = (ROOT / "rules/alerts.yml").read_text(encoding="utf-8")
    prom = (ROOT / "prometheus.yml.example").read_text(encoding="utf-8")
    blackbox = (ROOT / "blackbox.yml.example").read_text(encoding="utf-8")
    alertmanager = (ROOT / "alertmanager.yml.example").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    actual = parse_alerts(rules)
    expected = {name: {"severity": severity, "for": duration} for name, (severity, duration) in EXPECTED.items()}
    if actual != expected:
        raise ValueError(f"alert inventory/threshold mismatch: {actual!r}")
    for name in EXPECTED:
        block = rules.split(f"alert: {name}", 1)[1].split("\n      - alert:", 1)[0]
        for field in ("expr:", "labels:", "annotations:", "summary:", "description:", "runbook:"):
            if field not in block:
                raise ValueError(f"{name}: missing {field}")
    for token in ("blackbox-exporter:9115", "node-exporter:9100", "postgres-exporter:9187", "redis-exporter:9121", "backup-metadata-exporter:9200"):
        if token not in prom:
            raise ValueError(f"missing Prometheus scrape target {token}")
    if "https_2xx:" not in blackbox or "http_2xx_no_redirect:" not in blackbox:
        raise ValueError("blackbox HTTP/TLS modules missing")
    if 'group_by: ["alertname", "service", "severity"]' not in alertmanager:
        raise ValueError("Alertmanager deduplication group_by missing")
    if "send_resolved: true" not in readme or "repeat_interval: 4h" not in alertmanager:
        raise ValueError("resolved delivery or repeat policy missing")
    for name, content in (("rules", rules), ("prometheus", prom), ("blackbox", blackbox), ("alertmanager", alertmanager)):
        if FORBIDDEN.search(content) or SECRET_URL.search(content):
            raise ValueError(f"privacy/secret pattern found in {name} template")
    if "26h" not in readme and "26 hours" not in readme:
        raise ValueError("backup freshness threshold is not documented")
    if "secret manager" not in readme.lower():
        raise ValueError("secret manager guidance missing")
    print(f"Monitoring static validation passed: {len(actual)} alert rules, thresholds, annotations and privacy checks.")
    return len(actual)


def simulate() -> None:
    """Verify pending -> firing after the for-duration, and firing -> resolved on recovery."""
    fixtures = {
        "api": (120, [(0, True), (60, True), (120, True), (180, False)]),
        "disk-warning": (600, [(0, True), (300, True), (600, True), (660, False)]),
        "backup-stale": (300, [(0, True), (180, True), (300, True), (360, False)]),
    }
    for name, (debounce, samples) in fixtures.items():
        breach_started: int | None = None
        firing = False
        fired = False
        transitions: list[str] = []
        for timestamp, breached in samples:
            if breached:
                if breach_started is None:
                    breach_started = timestamp
                    transitions.append("pending")
                firing = timestamp - breach_started >= debounce
                if firing and not fired:
                    transitions.append("firing")
                    fired = True
            else:
                if firing:
                    transitions.append("resolved")
                breach_started, firing = None, False
        if not fired or transitions[-1] != "resolved":
            raise ValueError(f"{name}: expected pending/firing/resolved, got {transitions}")
    print("Alert simulation passed: pending -> firing -> resolved for API, disk and backup.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--simulate", action="store_true", help="simulate alert firing and recovery")
    args = parser.parse_args()
    try:
        count = validate()
        if args.simulate:
            simulate()
        return 0 if count else 1
    except (OSError, ValueError) as exc:
        print(f"monitoring validation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
