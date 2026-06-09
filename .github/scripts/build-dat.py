#!/usr/bin/env python3
"""
Build GeoSite.dat (geosite) and GeoIP.dat (geoip) from mihomo rule sources.

Core categories (always built):
  GeoSite.dat → AIGC / COMMUNITY / DIRECT / PROXY  (from txt/mihomo/<Group>.txt)
  GeoIP.dat   → one category per URL in txt/mihomo/ip.txt, named from filename

Extra categories (user-defined in txt/mihomo/extra.yaml):
  sites: [{name: <code>, urls: [...]}]  → appended to GeoSite.dat
  ips:   [{name: <code>, urls: [...]}]  → appended to GeoIP.dat

  Multiple URLs under the same name are merged + deduplicated into ONE category.
  A single URL produces one standalone category.

Both files use the v2ray/xray GeoSite/GeoIP protobuf wire format.
No third-party dependencies beyond PyYAML.
"""

import ipaddress
import os
import re
import sys
import urllib.request
import urllib.error

import yaml  # pyyaml

# ── Repo root ─────────────────────────────────────────────────────────────────

ROOT = os.environ.get("GITHUB_WORKSPACE") or os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
TXT_DIR = os.path.join(ROOT, "txt", "mihomo")
OUT_DIR = os.path.join(ROOT, "compilation")

EXTRA_CONFIG = os.path.join(TXT_DIR, "extra.yaml")

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
    if r.startswith("DOMAIN-SUFFIX,"):
        v = r[14:].split(",")[0].strip().lstrip(".")
        return (DOMAIN, v) if v else None
    if r.startswith("DOMAIN,"):
        v = r[7:].split(",")[0].strip()
        return (FULL, v) if v else None
    if r.startswith("DOMAIN-KEYWORD,"):
        v = r[15:].split(",")[0].strip()
        return (PLAIN, v) if v else None
    if r.startswith("DOMAIN-REGEX,"):
        v = r[13:].split(",")[0].strip()
        return (REGEX, v) if v else None
    if r.startswith("+."):
        v = r[2:].strip()
        return (DOMAIN, v) if v else None
    # Bare domain — treat as subdomain match
    if "," not in r and _BARE_DOMAIN.match(r):
        return (DOMAIN, r)
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
    """Extract the payload/rules list from a mihomo YAML string."""
    try:
        data = yaml.safe_load(content)
        if isinstance(data, dict):
            return data.get("payload") or data.get("rules") or []
        if isinstance(data, list):
            return data
    except Exception as exc:
        print(f"  WARN: YAML parse error: {exc}", file=sys.stderr)
    return []


def load_extra_config() -> dict:
    """
    Load txt/mihomo/extra.yaml.
    Returns {'sites': [...], 'ips': [...]} or empty lists if file is absent/empty.
    """
    if not os.path.isfile(EXTRA_CONFIG):
        return {"sites": [], "ips": []}
    try:
        with open(EXTRA_CONFIG) as f:
            data = yaml.safe_load(f) or {}
        return {
            "sites": data.get("sites") or [],
            "ips":   data.get("ips")   or [],
        }
    except Exception as exc:
        print(f"WARN: cannot parse extra.yaml: {exc}", file=sys.stderr)
        return {"sites": [], "ips": []}


def read_urls(path: str) -> list:
    """Read non-empty, non-comment lines from a plain text file."""
    urls = []
    with open(path) as f:
        for line in f:
            s = line.strip()
            if s and not s.startswith("#"):
                urls.append(s)
    return urls


# ── Network helpers ───────────────────────────────────────────────────────────

_HEADERS = {"User-Agent": "curl/7.88.1"}


def fetch(url: str, retries: int = 3) -> str:
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
    for url in urls:
        print(f"  [{label}] {url}")
        try:
            content = fetch(url)
        except Exception as exc:
            print(f"  ERROR: {exc}", file=sys.stderr)
            continue
        for rule in load_payload(content):
            if not isinstance(rule, str):
                continue
            parsed = parse_domain_rule(rule)
            if parsed and parsed[1] not in seen:
                seen.add(parsed[1])
                domains.append(parsed)
    return domains


def collect_cidrs(urls: list, label: str) -> list:
    """
    Download each URL, parse IP/CIDR rules, deduplicate.
    Returns [(ip_bytes, prefix), ...].
    """
    seen: set = set()
    cidrs: list = []
    for url in urls:
        print(f"  [{label}] {url}")
        try:
            content = fetch(url)
        except Exception as exc:
            print(f"  ERROR: {exc}", file=sys.stderr)
            continue
        for rule in load_payload(content):
            if not isinstance(rule, str):
                continue
            parsed = parse_ip_rule(rule)
            if parsed and parsed not in seen:
                seen.add(parsed)
                cidrs.append(parsed)
    return cidrs


# ── Builders ─────────────────────────────────────────────────────────────────


def build_susite(extra_sites: list):
    """
    Build compilation/GeoSite.dat.

    Core categories  : AIGC / COMMUNITY / DIRECT / PROXY  (txt/mihomo/<Group>.txt)
    Extra categories : from extra.yaml  →  sites: [{name, urls}]
    """
    print("==> Building GeoSite.dat")
    entries = []

    # ── Core groups ──────────────────────────────────────────────────────────
    for group in ["AIGC", "Community", "Direct", "Proxy"]:
        txt_path = os.path.join(TXT_DIR, f"{group}.txt")
        urls = read_urls(txt_path)
        code = group.upper()
        domains = collect_domains(urls, code)
        print(f"  {code}: {len(domains):,} domain rules")
        entries.append((code, domains))

    # ── Extra groups ─────────────────────────────────────────────────────────
    if extra_sites:
        print("  -- extra sites --")
    for item in extra_sites:
        name = str(item.get("name", "")).strip()
        urls = item.get("urls") or []
        if not name or not urls:
            print(f"  WARN: skipping malformed extra site entry: {item}", file=sys.stderr)
            continue
        code = name.upper()
        domains = collect_domains(urls, code)
        print(f"  {code}: {len(domains):,} domain rules  [extra]")
        entries.append((code, domains))

    out = os.path.join(OUT_DIR, "GeoSite.dat")
    data = encode_geosite_list(entries)
    with open(out, "wb") as f:
        f.write(data)
    print(f"  -> {out} ({len(data):,} bytes)\n")


def build_suip(extra_ips: list):
    """
    Build compilation/GeoIP.dat.

    Core categories  : one per URL in txt/mihomo/ip.txt, named from filename
    Extra categories : from extra.yaml  →  ips: [{name, urls}]
    """
    print("==> Building GeoIP.dat")
    entries = []

    # ── Core categories from ip.txt ───────────────────────────────────────────
    ip_txt = os.path.join(TXT_DIR, "ip.txt")
    for url in read_urls(ip_txt):
        fname = url.rstrip("/").rsplit("/", 1)[-1]
        code = os.path.splitext(fname)[0].upper().replace("-", "_")
        cidrs = collect_cidrs([url], code)
        print(f"  {code}: {len(cidrs):,} CIDR rules")
        entries.append((code, cidrs))

    # ── Extra groups ─────────────────────────────────────────────────────────
    if extra_ips:
        print("  -- extra ips --")
    for item in extra_ips:
        name = str(item.get("name", "")).strip()
        urls = item.get("urls") or []
        if not name or not urls:
            print(f"  WARN: skipping malformed extra ip entry: {item}", file=sys.stderr)
            continue
        code = name.upper()
        cidrs = collect_cidrs(urls, code)
        print(f"  {code}: {len(cidrs):,} CIDR rules  [extra]")
        entries.append((code, cidrs))

    out = os.path.join(OUT_DIR, "GeoIP.dat")
    data = encode_geoip_list(entries)
    with open(out, "wb") as f:
        f.write(data)
    print(f"  -> {out} ({len(data):,} bytes)\n")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    os.makedirs(OUT_DIR, exist_ok=True)

    extra = load_extra_config()
    print(
        f"Extra config: {len(extra['sites'])} site group(s), "
        f"{len(extra['ips'])} ip group(s)\n"
    )

    build_susite(extra["sites"])
    build_suip(extra["ips"])
    print("All done.")
