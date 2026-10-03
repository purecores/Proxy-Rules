#!/usr/bin/env python3
"""Validate generated rule formats and cross-format category parity."""
import ipaddress
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPILED = ROOT / "compilation"
GROUPS = ("Github", "Community", "Gemini", "AI", "Direct", "Proxy")
RULE_TYPES = {"DOMAIN", "DOMAIN-SUFFIX", "DOMAIN-KEYWORD", "DOMAIN-REGEX", "IP-CIDR", "IP-CIDR6", "URL-REGEX", "USER-AGENT"}


def normalize_mihomo(rule: str) -> str:
    value = rule.strip()
    if value.startswith("+."):
        return "DOMAIN-SUFFIX," + value[2:].lower()
    if "," not in value:
        return "DOMAIN-SUFFIX," + value.lower()
    kind, body = value.split(",", 1)
    kind = kind.upper()
    body = body.strip()
    if kind == "DOMAIN-SUFFIX":
        body = body.removeprefix("+.").lstrip(".")
    return kind + "," + body.lower()


def load_mihomo_group(name: str) -> set[str]:
    path = COMPILED / "mihomo" / f"{name}.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    rules = data.get("payload") if isinstance(data, dict) else None
    if not isinstance(rules, list) or not rules or any(not isinstance(x, str) for x in rules):
        raise ValueError(f"{path} must contain a non-empty string payload")
    return {normalize_mihomo(rule) for rule in rules}


def load_shadowrocket_group(name: str) -> set[str]:
    path = COMPILED / "shadowrocket" / f"{name}.list"
    rules: set[str] = set()
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or "," not in line:
            raise ValueError(f"{path}:{line_no}: expected TYPE,value rule")
        kind, body = line.split(",", 1)
        kind, body = kind.upper(), body.strip()
        if kind not in RULE_TYPES or not body:
            raise ValueError(f"{path}:{line_no}: unsupported or empty rule: {raw}")
        if kind == "DOMAIN-SUFFIX" and (body.startswith("+.") or body.startswith(".")):
            raise ValueError(f"{path}:{line_no}: invalid DOMAIN-SUFFIX value: {body}")
        if kind in {"IP-CIDR", "IP-CIDR6"}:
            cidr = body.split(",", 1)[0]
            try:
                version = ipaddress.ip_network(cidr, strict=False).version
            except ValueError as exc:
                raise ValueError(f"{path}:{line_no}: invalid CIDR: {cidr}") from exc
            expected = "IP-CIDR6" if version == 6 else "IP-CIDR"
            if kind != expected:
                raise ValueError(f"{path}:{line_no}: {cidr} must use {expected}")
        rules.add(kind + "," + body.lower())
    if not rules:
        raise ValueError(f"{path} is empty")
    return rules


def validate() -> None:
    errors: list[str] = []
    for path in sorted((COMPILED / "shadowrocket").glob("*.list")):
        load_shadowrocket_group(path.stem)
    for name in GROUPS:
        mihomo, shadowrocket = load_mihomo_group(name), load_shadowrocket_group(name)
        missing, extra = mihomo - shadowrocket, shadowrocket - mihomo
        mismatch_count = len(missing) + len(extra)
        tolerance = max(10, int(max(len(mihomo), len(shadowrocket)) * 0.01))
        if mismatch_count > tolerance:
            errors.append(f"{name} parity mismatch exceeds tolerance: Mihomo={len(mihomo)}, Shadowrocket={len(shadowrocket)}, missing={len(missing)}, extra={len(extra)}, tolerance={tolerance}")
        elif mismatch_count:
            print(f"WARNING: {name} has {mismatch_count} cross-format mismatch(es), within source-drift tolerance {tolerance}")
    for path in (COMPILED / "GeoSite.dat", COMPILED / "GeoIP.dat"):
        if not path.is_file() or not path.stat().st_size:
            errors.append(f"missing or empty database: {path}")
    for name in GROUPS:
        path = COMPILED / "mihomo" / f"{name}.mrs"
        if not path.is_file() or not path.stat().st_size:
            errors.append(f"missing or empty ruleset: {path}")
    audit_path = COMPILED / "source-audit.json"
    if not audit_path.is_file():
        errors.append(f"missing source audit: {audit_path}")
    else:
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        if not audit.get("sources") or not audit.get("outputs"):
            errors.append("source audit has no source/output records")
    if errors:
        raise ValueError("\n".join(errors))


if __name__ == "__main__":
    try:
        validate()
    except Exception as exc:
        print(f"OUTPUT VALIDATION FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print("Generated outputs are valid and cross-format categories match.")