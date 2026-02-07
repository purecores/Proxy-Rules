#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT_JSON="${ROOT_DIR}/compilation/ad/ad-singbox.json"
OUT_SRS="${ROOT_DIR}/compilation/ad/ad-singbox.srs"

WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

mkdir -p "$(dirname "$OUT_JSON")"

# Sources
YAML_DOMAIN_URL="https://anti-ad.net/clash.yaml"

CLASSICAL_TXT_URLS=(
  "https://ruleset.skk.moe/Clash/non_ip/reject-no-drop.txt"
  "https://ruleset.skk.moe/Clash/non_ip/reject-drop.txt"
  "https://ruleset.skk.moe/Clash/non_ip/reject.txt"
  "https://ruleset.skk.moe/Clash/ip/reject.txt"
)

DOMAIN_TXT_URLS=(
  "https://ruleset.skk.moe/Clash/domainset/reject.txt"
  "https://ruleset.skk.moe/Clash/domainset/reject_extra.txt"
)

RAW_ALL="${WORKDIR}/all.txt"
: > "$RAW_ALL"

fetch() {
  local url="$1"
  # -f: fail on http errors, -S: show error, -L: follow redirect
  curl -fsSL "$url"
}

echo "[1/4] Fetching rules..."
# YAML (Clash ruleset yaml) - keep only meaningful lines
fetch "$YAML_DOMAIN_URL" >> "$RAW_ALL" || true
printf "\n" >> "$RAW_ALL"

# TXT classical
for u in "${CLASSICAL_TXT_URLS[@]}"; do
  fetch "$u" >> "$RAW_ALL" || true
  printf "\n" >> "$RAW_ALL"
done

# TXT domainset
for u in "${DOMAIN_TXT_URLS[@]}"; do
  fetch "$u" >> "$RAW_ALL" || true
  printf "\n" >> "$RAW_ALL"
done

# Normalize CRLF, strip BOM
sed -i 's/\r$//g' "$RAW_ALL"
sed -i '1s/^\xEF\xBB\xBF//' "$RAW_ALL"

# Output buckets
DOM="${WORKDIR}/domain.txt"
DOMSFX="${WORKDIR}/domain_suffix.txt"
DOMKW="${WORKDIR}/domain_keyword.txt"
IP4="${WORKDIR}/ip_cidr.txt"
IP6="${WORKDIR}/ip_cidr6.txt"
ASN="${WORKDIR}/ip_asn.txt"

: > "$DOM"; : > "$DOMSFX"; : > "$DOMKW"; : > "$IP4"; : > "$IP6"; : > "$ASN"

echo "[2/4] Parsing & categorizing..."

# 说明：
# - 兼容 Clash YAML（payload: / rules: / 以及 - 'DOMAIN-SUFFIX,xxx' 这种）
# - 兼容 TXT 中的：
#   DOMAIN,xxx / DOMAIN-SUFFIX,xxx / DOMAIN-KEYWORD,xxx / IP-CIDR,... / IP-CIDR6,... / IP-ASN,...
# - 兼容 domainset 的：
#   +.example.com  -> domain_suffix: example.com
#   example.com    -> domain_suffix: example.com
# - 过滤无效行（注释、空行、奇怪字符串等）
awk -v FDOM="$DOM" -v FDOMSFX="$DOMSFX" -v FDOMKW="$DOMKW" -v FIP4="$IP4" -v FIP6="$IP6" -v FASN="$ASN" '
function trim(s){ gsub(/^[ \t]+|[ \t]+$/, "", s); return s }

function is_domain(s,   t){
  t=s
  # 基本合法性：至少一个点、仅允许 [A-Za-z0-9.-]，且不以点/连字符开头结尾
  if (t !~ /^[A-Za-z0-9][A-Za-z0-9.-]*[A-Za-z0-9]$/) return 0
  if (t !~ /\./) return 0
  if (t ~ /\.\./) return 0
  return 1
}

{
  line=$0
  line=trim(line)

  # skip empty
  if (line=="") next

  # remove inline comments (common patterns)
  # If a line starts with comment markers, drop it
  if (line ~ /^[;#]/) next
  if (line ~ /^\/\//) next

  # strip YAML list dash/prefix and quotes:  - "DOMAIN-SUFFIX,xxx"
  gsub(/^-\s*/, "", line)
  gsub(/^'\''|'\''$/, "", line)
  gsub(/^"|"$/, "", line)

  line=trim(line)
  if (line=="") next

  # Classical formats
  if (line ~ /^DOMAIN,/) {
    n=split(line, a, ",")
    v=trim(a[2])
    if (is_domain(v)) print v >> FDOM
    next
  }
  if (line ~ /^DOMAIN-SUFFIX,/) {
    n=split(line, a, ",")
    v=trim(a[2])
    if (is_domain(v)) print v >> FDOMSFX
    next
  }
  if (line ~ /^DOMAIN-KEYWORD,/) {
    n=split(line, a, ",")
    v=trim(a[2])
    # keyword 允许更宽松，但排除明显垃圾
    if (v!="" && length(v) <= 256) print v >> FDOMKW
    next
  }
  if (line ~ /^IP-CIDR,/) {
    n=split(line, a, ",")
    v=trim(a[2])
    if (v ~ /^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+\/[0-9]+$/) print v >> FIP4
    next
  }
  if (line ~ /^IP-CIDR6,/) {
    n=split(line, a, ",")
    v=trim(a[2])
    # 简单判断：包含冒号和前缀
    if (v ~ /:/ && v ~ /\/[0-9]+$/) print v >> FIP6
    next
  }
  if (line ~ /^IP-ASN,/) {
    n=split(line, a, ",")
    v=trim(a[2])
    if (v ~ /^[0-9]+$/) print v >> FASN
    next
  }

  # domainset formats: +.example.com
  if (line ~ /^\+\./) {
    v=substr(line, 3)
    v=trim(v)
    if (is_domain(v)) print v >> FDOMSFX
    next
  }

  # domainset formats: example.com
  if (is_domain(line)) {
    print line >> FDOMSFX
    next
  }

  # otherwise ignore
  next
}
' "$RAW_ALL"

echo "[3/4] Deduplicating..."
# 高效去重：sort -u（规则量大时非常稳）
# domain / suffix / keyword: 纯字符串去重
LC_ALL=C sort -u "$DOM" -o "$DOM"
LC_ALL=C sort -u "$DOMSFX" -o "$DOMSFX"
LC_ALL=C sort -u "$DOMKW" -o "$DOMKW"
LC_ALL=C sort -u "$IP4" -o "$IP4"
LC_ALL=C sort -u "$IP6" -o "$IP6"
# ASN 数字去重
LC_ALL=C sort -n -u "$ASN" -o "$ASN"

echo "[4/4] Writing sing-box ruleset v2 JSON & compiling SRS..."

# 直接从文件读取，避免命令行参数过长
jq -n \
  --rawfile domain_txt "$DOM" \
  --rawfile domain_suffix_txt "$DOMSFX" \
  --rawfile domain_keyword_txt "$DOMKW" \
  --rawfile ip_cidr_txt "$IP4" \
  --rawfile ip_cidr6_txt "$IP6" \
  --rawfile ip_asn_txt "$ASN" \
  '
  def lines($s): ($s | split("\n") | map(select(length>0)));
  def asn_lines($s): (lines($s) | map(tonumber));

  {
    "version": 2,
    "rules": [
      {
        "domain":        lines($domain_txt),
        "domain_suffix": lines($domain_suffix_txt),
        "domain_keyword":lines($domain_keyword_txt),
        "ip_cidr":       lines($ip_cidr_txt),
        "ip_cidr6":      lines($ip_cidr6_txt),
        "ip_asn":        asn_lines($ip_asn_txt)
      }
    ]
  }' > "$OUT_JSON"

# Compile to .srs (sing-box must exist in PATH)
sing-box rule-set compile --output "$OUT_SRS" "$OUT_JSON"

echo "Done:"
echo "  - $OUT_JSON"
echo "  - $OUT_SRS"
