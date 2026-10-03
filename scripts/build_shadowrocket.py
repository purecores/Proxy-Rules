#!/usr/bin/env python3
"""Build Shadowrocket lists from configured YAML rule sources."""
import hashlib
import ipaddress
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(os.environ.get("GITHUB_WORKSPACE", Path(__file__).resolve().parents[1]))
SOURCE_DIR = ROOT / "config" / "sources" / "shadowrocket"
OUT_DIR = ROOT / "compilation" / "shadowrocket"
AUDIT_PATH = ROOT / "compilation" / "source-audit.json"
RULE_TYPES = {"DOMAIN", "DOMAIN-SUFFIX", "DOMAIN-KEYWORD", "DOMAIN-REGEX", "IP-CIDR", "IP-CIDR6", "URL-REGEX", "USER-AGENT"}


def read_urls(path: Path) -> list[str]:
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")]


def fetch(url: str, retries: int = 3) -> bytes:
    if url.startswith("local://personal/"):
        relative = url.removeprefix("local://personal/")
        local_path = (ROOT / "config" / "personal" / relative).resolve()
        if ROOT.joinpath("config", "personal").resolve() not in local_path.parents:
            raise ValueError(f"invalid local personal source path: {url}")
        return local_path.read_bytes()
    request = urllib.request.Request(url, headers={"User-Agent": "proxy-rules-builder/1.0"})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.read()
        except (urllib.error.URLError, TimeoutError):
            if attempt + 1 == retries:
                raise
            time.sleep(attempt + 1)
    raise RuntimeError(f"failed to fetch {url}")


def load_rules(content: bytes, url: str) -> list[str]:
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid YAML from {url}: {exc}") from exc
    rules = data.get("payload", data.get("rules")) if isinstance(data, dict) else data
    if not isinstance(rules, list) or not rules:
        raise ValueError(f"{url} has no non-empty payload/rules list")
    if any(not isinstance(rule, str) for rule in rules):
        raise ValueError(f"{url} contains a non-string rule")
    return rules


def normalize_rule(rule: str, default_type: str) -> str | None:
    """Translate Mihomo suffixes and infer CIDR family for Shadowrocket."""
    value = rule.strip()
    if not value or value.startswith("#"):
        return None
    if "," in value:
        kind, body = value.split(",", 1)
        kind = kind.strip().upper()
        if kind in RULE_TYPES:
            body = body.strip()
            if kind == "DOMAIN-SUFFIX":
                body = body.removeprefix("+.").lstrip(".")
            if kind in {"IP-CIDR", "IP-CIDR6"}:
                cidr, *options = body.split(",")
                try:
                    network = ipaddress.ip_network(cidr.strip(), strict=False)
                except ValueError as exc:
                    raise ValueError(f"invalid {kind} rule: {rule}") from exc
                kind = "IP-CIDR6" if network.version == 6 else "IP-CIDR"
                body = str(network) + ("," + ",".join(options) if options else "")
            if not body:
                raise ValueError(f"empty {kind} rule: {rule}")
            return f"{kind},{body}"
    if value.startswith("+."):
        value = value[2:]
    if default_type == "IP-CIDR":
        try:
            network = ipaddress.ip_network(value, strict=False)
        except ValueError as exc:
            raise ValueError(f"invalid IP rule: {rule}") from exc
        kind = "IP-CIDR6" if network.version == 6 else "IP-CIDR"
        return f"{kind},{network}"
    if not value:
        raise ValueError(f"empty domain rule: {rule}")
    return f"{default_type},{value}"


def build_one(path: Path, audit_sources: list[dict]) -> tuple[Path, int]:
    output = OUT_DIR / f"{path.stem}.list"
    rules: list[str] = []
    seen: set[str] = set()
    urls = read_urls(path)
    if not urls:
        raise ValueError(f"no source URLs configured in {path}")
    for url in urls:
        default_type = "IP-CIDR" if "/geoip/" in url else "DOMAIN-SUFFIX"
        print(f"  [{path.stem}] {url}")
        content = fetch(url)
        source_rules = load_rules(content, url)
        parsed = [normalized for rule in source_rules
                  if (normalized := normalize_rule(rule, default_type)) is not None]
        audit_sources.append({"category": path.stem, "url": url,
                              "sha256": hashlib.sha256(content).hexdigest(),
                              "source_rules": len(source_rules), "accepted_rules": len(parsed)})
        for rule in parsed:
            if path.stem == "Direct" and rule == "DOMAIN-SUFFIX,micu.hk":
                continue
            if rule not in seen:
                seen.add(rule)
                rules.append(rule)
    if not rules:
        raise ValueError(f"no rules produced for {path}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text("\n".join(rules) + "\n", encoding="utf-8", newline="\n")
    temporary.replace(output)
    print(f"  -> {output} ({len(rules):,} rules)")
    return output, len(rules)


def check_source_drift(previous_audit: dict, sources: list[dict], consumer: str) -> None:
    previous = {
        (item.get("category"), item.get("url")): item.get("source_rules")
        for item in previous_audit.get("sources", [])
        if item.get("consumer", "shadowrocket") == consumer
    }
    max_change = float(os.environ.get("MAX_SOURCE_RULE_CHANGE", "0.5"))
    for item in sources:
        old_count = previous.get((item["category"], item["url"]))
        new_count = item["source_rules"]
        if old_count and abs(new_count - old_count) / old_count > max_change:
            raise ValueError(
                f"source size changed by more than {max_change:.0%}: {item['url']} "
                f"({old_count:,} -> {new_count:,}); inspect upstream change before publishing"
            )


def main() -> None:
    previous_audit = {}
    compare_drift = AUDIT_PATH.is_file()
    if AUDIT_PATH.is_file():
        try:
            previous_audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            compare_drift = False
            print("WARNING: previous source audit is unreadable; skipping drift comparison", file=sys.stderr)
    audit_sources: list[dict] = []
    outputs: dict[str, dict] = {}
    for path in sorted(SOURCE_DIR.glob("*.txt")):
        output, count = build_one(path, audit_sources)
        content = output.read_bytes()
        outputs[output.name] = {"rules": count, "bytes": len(content),
                                "sha256": hashlib.sha256(content).hexdigest()}
    if not outputs:
        raise ValueError(f"no source lists found under {SOURCE_DIR}")
    if compare_drift:
        check_source_drift(previous_audit, audit_sources, "shadowrocket")
    mihomo_audit_path = OUT_DIR.parent / "source-audit-mihomo.json"
    mihomo_records = json.loads(mihomo_audit_path.read_text(encoding="utf-8")).get("sources", []) if mihomo_audit_path.is_file() else []
    previous_mihomo_records = [item for item in previous_audit.get("sources", []) if item.get("consumer") == "mihomo"]
    if compare_drift and previous_mihomo_records:
        check_source_drift(previous_audit, mihomo_records, "mihomo")
    audit = {"sources": mihomo_records + audit_sources, "outputs": outputs}
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = AUDIT_PATH.with_suffix(AUDIT_PATH.suffix + ".tmp")
    temporary.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8", newline="\n")
    temporary.replace(AUDIT_PATH)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc