#!/usr/bin/env python3
"""
Build GeoSite.dat (geosite) and GeoIP.dat (geoip) from mihomo rule sources.

Core categories (always built):
  GeoSite.dat → GITHUB / COMMUNITY / GEMINI / AI / DIRECT / PROXY  (config/sources/mihomo/<Group>.txt)
  GeoIP.dat   → one category per URL in config/sources/mihomo/ip.txt, named from filename

Extra categories (user-defined in config/sources/mihomo/extra.yaml):
  sites: [{name: <code>, urls: [...]}]  → appended to GeoSite.dat
  ips:   [{name: <code>, urls: [...]}]  → appended to GeoIP.dat

  Multiple URLs under the same name are merged + deduplicated into ONE category.
  A single URL produces one standalone category.

Both files use the v2ray/xray GeoSite/GeoIP protobuf wire format.
No third-party dependencies beyond PyYAML.
"""

import hashlib
import ipaddress
import json
import os
import re
import sys
import urllib.request
import urllib.error

import yaml  # pyyaml

# ── Repo root ─────────────────────────────────────────────────────────────────

ROOT = os.environ.get("GITHUB_WORKSPACE") or os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")
)
SOURCE_DIR = os.path.join(ROOT, "config", "sources", "mihomo")
OUT_DIR = os.path.join(ROOT, "compilation")

EXTRA_CONFIG = os.path.join(SOURCE_DIR, "extra.yaml")
SOURCE_AUDIT = os.path.join(OUT_DIR, "source-audit-mihomo.json")
SOURCE_RECORDS = []

# ── Minimal protobuf encoder ──────────────────────────────────────────────────
# Wire types: 0 = varint, 2 = length-delimited


def _varint(n: int) -> bytes:
    buf = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        buf.append(0x80 | b if n else b)
        if not n:
            break
    return bytes(buf)


def _tag(field: int, wtype: int) -> bytes:
    return _varint((field << 3) | wtype)


def pb_varint(field: int, v: int) -> bytes:
    return _tag(field, 0) + _varint(v)


def pb_str(field: int, s: str) -> bytes:
    b = s.encode()
    return _tag(field, 2) + _varint(len(b)) + b


def pb_bytes(field: int, b: bytes) -> bytes:
    return _tag(field, 2) + _varint(len(b)) + b


def pb_msg(field: int, data: bytes) -> bytes:
    return _tag(field, 2) + _varint(len(data)) + data


# ── GeoSite protobuf ─────────────────────────────────────────────────────────
# GeoSiteList { repeated GeoSite entry = 1 }
# GeoSite     { string country_code = 1; repeated Domain domain = 2 }
# Domain      { Type type = 1; string value = 2 }
#   Type: Plain=0 (keyword), Regex=1, Domain=2 (subdomain), Full=3 (exact)

PLAIN, REGEX, DOMAIN, FULL = 0, 1, 2, 3


def encode_geosite_list(entries: list) -> bytes:
    """entries: [(code, [(dtype, value), ...]), ...]"""
    out = b""
    for code, domains in entries:
        gs = pb_str(1, code.upper())
        for dtype, val in domains:
            gs += pb_msg(2, pb_varint(1, dtype) + pb_str(2, val))
        out += pb_msg(1, gs)
    return out


# ── GeoIP protobuf ────────────────────────────────────────────────────────────
# GeoIPList { repeated GeoIP entry = 1 }
# GeoIP     { string country_code = 1; repeated CIDR cidr = 2 }
# CIDR      { bytes ip = 1; uint32 prefix = 2 }


def encode_geoip_list(entries: list) -> bytes:
    """entries: [(code, [(ip_bytes, prefix), ...]), ...]"""
    out = b""
    for code, cidrs in entries:
        gi = pb_str(1, code.upper())
        for ip_b, prefix in cidrs:
            gi += pb_msg(2, pb_bytes(1, ip_b) + pb_varint(2, prefix))
        out += pb_msg(1, gi)
    return out


# ── Rule parsers ──────────────────────────────────────────────────────────────

_BARE_DOMAIN = re.compile(r"^[a-zA-Z0-9*._-]+\.[a-zA-Z]{2,}$")


def parse_domain_rule(rule: str):
    """Return (dtype, value) or None for non-domain / unrecognised rules."""
    r = rule.strip()
    if r.upper().startswith("DOMAIN-SUFFIX,"):
        v = r[14:].split(",")[0].strip().lstrip(".").lower()
        return (DOMAIN, v) if v else None
    if r.upper().startswith("DOMAIN,"):
        v = r[7:].split(",")[0].strip().lower()
        return (FULL, v) if v else None
    if r.upper().startswith("DOMAIN-KEYWORD,"):
        v = r[15:].split(",")[0].strip().lower()
        return (PLAIN, v) if v else None
    if r.upper().startswith("DOMAIN-REGEX,"):
        v = r[13:].split(",")[0].strip()
        return (REGEX, v) if v else None
    if r.startswith("+."):
        v = r[2:].strip()
        return (DOMAIN, v.lower()) if v else None
    # Bare domain — treat as subdomain match.
    if "," not in r and _BARE_DOMAIN.match(r):
        return (DOMAIN, r.lower())
    return None


def parse_ip_rule(rule: str):
    """Return (ip_bytes, prefix) or None."""
    r = rule.strip()
    cidr_str = None

    u = r.upper()
    if u.startswith("IP-CIDR6,") or u.startswith("IP-CIDR,"):
        # IP-CIDR,1.2.3.0/24[,no-resolve]
        cidr_str = r.split(",")[1].strip()
    elif "/" in r and "," not in r:
        # Bare CIDR — MetaCubeX geo-lite geoip format
        cidr_str = r

    if not cidr_str:
        return None
    try:
        net = ipaddress.ip_network(cidr_str, strict=False)
        return (net.network_address.packed, net.prefixlen)
    except ValueError:
        return None


# ── YAML / config helpers ─────────────────────────────────────────────────────


def load_payload(content: str) -> list:
    """Extract and validate a rule list from a YAML source."""
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid YAML payload: {exc}") from exc
    if isinstance(data, dict):
        payload = data.get("payload")
        if payload is None:
            payload = data.get("rules")
    else:
        payload = data
    if not isinstance(payload, list) or not payload:
        raise ValueError("source does not contain a non-empty payload/rules list")
    if any(not isinstance(rule, str) for rule in payload):
        raise ValueError("payload/rules entries must all be strings")
    return payload


def load_extra_config() -> dict:
    """Load and validate optional named GeoSite/GeoIP sources."""
    if not os.path.isfile(EXTRA_CONFIG):
        return {"sites": [], "ips": []}
    try:
        with open(EXTRA_CONFIG, encoding="utf-8") as stream:
            data = yaml.safe_load(stream) or {}
    except Exception as exc:
        raise ValueError(f"cannot parse extra.yaml: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("extra.yaml must be a mapping")
    sites, ips = data.get("sites") or [], data.get("ips") or []
    if not isinstance(sites, list) or not isinstance(ips, list):
        raise ValueError("extra.yaml sites and ips must be lists")
    return {"sites": sites, "ips": ips}


def read_urls(path: str) -> list:
    """Read non-empty, non-comment lines from a plain text file."""
    urls = []
    with open(path, encoding="utf-8") as stream:
        for line in stream:
            s = line.strip()
            if s and not s.startswith("#"):
                urls.append(s)
    return urls


# ── Network helpers ───────────────────────────────────────────────────────────

_HEADERS = {"User-Agent": "curl/7.88.1"}


def fetch(url: str, retries: int = 3) -> str:
    if url.startswith("local://personal/"):
        relative = url.removeprefix("local://personal/")
        local_path = os.path.realpath(os.path.join(ROOT, "config", "personal", relative))
        personal_root = os.path.realpath(os.path.join(ROOT, "config", "personal"))
        if os.path.commonpath([personal_root, local_path]) != personal_root:
            raise ValueError(f"invalid local personal source path: {url}")
        with open(local_path, encoding="utf-8") as stream:
            return stream.read()
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers=_HEADERS)
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.URLError as exc:
            print(f"  attempt {attempt}/{retries} failed: {exc}", file=sys.stderr)
            if attempt == retries:
                raise
    return ""


# ── Shared collectors ─────────────────────────────────────────────────────────


def collect_domains(urls: list, label: str) -> list:
    """
    Download each URL, parse domain rules, deduplicate (first-seen order).
    Returns [(dtype, value), ...].
    """
    seen: set = set()
    domains: list = []
    if not urls:
        raise ValueError(f"no source URLs configured for {label}")
    for url in urls:
        print(f"  [{label}] {url}")
        try:
            content = fetch(url)
        except Exception as exc:
            raise RuntimeError(f"failed source {url}: {exc}") from exc
        source_rules = load_payload(content)
        parsed_count = 0
        for rule in source_rules:
            if not isinstance(rule, str):
                continue
            parsed = parse_domain_rule(rule)
            if parsed:
                parsed_count += 1
                if parsed not in seen:
                    seen.add(parsed)
                    domains.append(parsed)
        SOURCE_RECORDS.append({"consumer": "mihomo", "category": label, "url": url,
                               "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                               "source_rules": len(source_rules), "accepted_rules": parsed_count})
        print(f"    source_rules={len(source_rules):,}, domain_rules={parsed_count:,}, unique_total={len(domains):,}")
    return domains


def collect_cidrs(urls: list, label: str) -> list:
    """
    Download each URL, parse IP/CIDR rules, deduplicate.
    Returns [(ip_bytes, prefix), ...].
    """
    if not urls:
        raise ValueError(f"no source URLs configured for {label}")
    seen: set = set()
    cidrs: list = []
    for url in urls:
        print(f"  [{label}] {url}")
        try:
            content = fetch(url)
        except Exception as exc:
            raise RuntimeError(f"failed source {url}: {exc}") from exc
        source_rules = load_payload(content)
        parsed_count = 0
        for rule in source_rules:
            if not isinstance(rule, str):
                continue
            parsed = parse_ip_rule(rule)
            if parsed:
                parsed_count += 1
                if parsed not in seen:
                    seen.add(parsed)
                    cidrs.append(parsed)
        SOURCE_RECORDS.append({"consumer": "mihomo", "category": label, "url": url,
                               "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                               "source_rules": len(source_rules), "accepted_rules": parsed_count})
        print(f"    source_rules={len(source_rules):,}, cidr_rules={parsed_count:,}, unique_total={len(cidrs):,}")
    return cidrs


# ── Builders ─────────────────────────────────────────────────────────────────


def build_susite(extra_sites: list):
    """
    Build compilation/GeoSite.dat.

    Core categories  : GITHUB / COMMUNITY / GEMINI / AI / DIRECT / PROXY
    Extra categories : from extra.yaml  →  sites: [{name, urls}]
    """
    print("==> Building GeoSite.dat")
    entries = []

    # ── Core groups ──────────────────────────────────────────────────────────
    for group in ["Github", "Community", "Gemini", "AI", "Direct", "Proxy"]:
        txt_path = os.path.join(SOURCE_DIR, f"{group}.txt")
        urls = read_urls(txt_path)
        code = group.upper()
        domains = collect_domains(urls, code)
        if not domains:
            raise RuntimeError(f"required category {code} is empty")
        print(f"  {code}: {len(domains):,} domain rules")
        entries.append((code, domains))

    # ── Extra groups ─────────────────────────────────────────────────────────
    if extra_sites:
        print("  -- extra sites --")
    extra_by_name = {}
    for item in extra_sites:
        name = str(item.get("name", "")).strip()
        urls = item.get("urls") or []
        if not name or not urls:
            raise ValueError(f"malformed extra site entry: {item}")
        code = name.upper()
        extra_by_name.setdefault(code, []).extend(urls)
    for code, urls in extra_by_name.items():
        domains = collect_domains(urls, code)
        if not domains:
            raise RuntimeError(f"extra category {code} is empty")
        print(f"  {code}: {len(domains):,} domain rules  [extra]")
        entries.append((code, domains))

    out = os.path.join(OUT_DIR, "GeoSite.dat")
    if not any(domains for _, domains in entries):
        raise RuntimeError("GeoSite output would be empty")
    return out, encode_geosite_list(entries)


def build_suip(extra_ips: list):
    """
    Build compilation/GeoIP.dat.

    Core categories  : one per URL in config/sources/mihomo/ip.txt, named from filename
    Extra categories : from extra.yaml  →  ips: [{name, urls}]
    """
    print("==> Building GeoIP.dat")
    entries = []

    # ── Core categories from ip.txt ───────────────────────────────────────────
    ip_txt = os.path.join(SOURCE_DIR, "ip.txt")
    for url in read_urls(ip_txt):
        fname = url.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1]
        code = os.path.splitext(fname)[0].upper().replace("-", "_")
        cidrs = collect_cidrs([url], code)
        if not cidrs:
            raise RuntimeError(f"required category {code} is empty")
        print(f"  {code}: {len(cidrs):,} CIDR rules")
        entries.append((code, cidrs))

    # ── Extra groups ─────────────────────────────────────────────────────────
    if extra_ips:
        print("  -- extra ips --")
    extra_by_name = {}
    for item in extra_ips:
        name = str(item.get("name", "")).strip()
        urls = item.get("urls") or []
        if not name or not urls:
            raise ValueError(f"malformed extra IP entry: {item}")
        code = name.upper()
        extra_by_name.setdefault(code, []).extend(urls)
    for code, urls in extra_by_name.items():
        cidrs = collect_cidrs(urls, code)
        if not cidrs:
            raise RuntimeError(f"extra category {code} is empty")
        print(f"  {code}: {len(cidrs):,} CIDR rules  [extra]")
        entries.append((code, cidrs))

    out = os.path.join(OUT_DIR, "GeoIP.dat")
    if not any(cidrs for _, cidrs in entries):
        raise RuntimeError("GeoIP output would be empty")
    return out, encode_geoip_list(entries)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    os.makedirs(OUT_DIR, exist_ok=True)
    try:
        extra = load_extra_config()
        print(
            f"Extra config: {len(extra['sites'])} site group(s), "
            f"{len(extra['ips'])} ip group(s)\n"
        )
        site_path, site_data = build_susite(extra["sites"])
        ip_path, ip_data = build_suip(extra["ips"])
        outputs = [(site_path, site_data), (ip_path, ip_data)]
        with open(SOURCE_AUDIT, "w", encoding="utf-8") as stream:
            json.dump({"sources": SOURCE_RECORDS}, stream, indent=2)
            stream.write("\n")
        temporary_paths = []
        try:
            for path, data in outputs:
                temporary = path + ".tmp"
                with open(temporary, "wb") as stream:
                    stream.write(data)
                temporary_paths.append((temporary, path))
            backups = []
            for _, path in temporary_paths:
                backup = path + ".bak"
                if os.path.exists(path):
                    os.replace(path, backup)
                    backups.append((backup, path))
            try:
                for temporary, path in temporary_paths:
                    os.replace(temporary, path)
            except Exception:
                for _, path in temporary_paths:
                    if os.path.exists(path):
                        os.remove(path)
                for backup, path in backups:
                    if os.path.exists(backup):
                        os.replace(backup, path)
                raise
            for backup, _ in backups:
                if os.path.exists(backup):
                    os.remove(backup)
            for _, path in temporary_paths:
                print(f"  -> {path} ({os.path.getsize(path):,} bytes)")
        except Exception:
            for temporary, _ in temporary_paths:
                if os.path.exists(temporary):
                    os.remove(temporary)
            raise
    except Exception as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print("All done.")
