#!/usr/bin/env bash
set -euo pipefail

if [[ -n "${GITHUB_WORKSPACE:-}" && -d "${GITHUB_WORKSPACE}" ]]; then
  ROOT_DIR="${GITHUB_WORKSPACE}"
elif command -v git >/dev/null 2>&1 && git rev-parse --show-toplevel >/dev/null 2>&1; then
  ROOT_DIR="$(git rev-parse --show-toplevel)"
else
  ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
fi

TXT_DIR="${ROOT_DIR}/txt/shadowrocket"
OUT_DIR="${ROOT_DIR}/compilation/shadowrocket"
mkdir -p "${OUT_DIR}"

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "ERROR: missing dependency: $1" >&2
    exit 1
  }
}

require_cmd curl
require_cmd yq
require_cmd awk
require_cmd find
require_cmd sha256sum
require_cmd sed

CURL_COMMON_ARGS=(
  -fsSL
  --retry 3
  --retry-delay 2
  --retry-all-errors
  --connect-timeout 10
  --max-time 180
)

read_urls() {
  local file="$1"
  awk '
    NF == 0 { next }
    /^[[:space:]]*#/ { next }
    { gsub(/\r$/, "", $0); print $0 }
  ' "$file"
}

detect_rule_type() {
  local url="$1"

  if [[ "$url" == *"/geoip/"* ]]; then
    echo "IP-CIDR"
  elif [[ "$url" == *"/geosite/"* ]]; then
    echo "DOMAIN-SUFFIX"
  else
    # 无法识别时默认按 DOMAIN-SUFFIX
    echo "DOMAIN-SUFFIX"
  fi
}

download_with_cache() {
  local url="$1"
  local cache_dir="$2"
  local key out_file

  key="$(printf '%s' "$url" | sha256sum | awk '{print $1}')"
  out_file="${cache_dir}/${key}.yaml"

  if [[ ! -s "$out_file" ]]; then
    curl "${CURL_COMMON_ARGS[@]}" "$url" -o "$out_file"
  fi

  printf '%s\n' "$out_file"
}

# 高性能批量转换：
# - payload/rules 一次性提取
# - awk 批量补前缀
# - 已经带前缀的规则直接保留
append_rules_from_yaml() {
  local yaml_file="$1"
  local rule_type="$2"
  local merged_file="$3"

  yq -r '.payload // .rules // [] | .[]' "$yaml_file" 2>/dev/null \
    | sed '/^[[:space:]]*$/d' \
    | awk -v default_type="$rule_type" '
        BEGIN { FS=OFS="," }
        {
          gsub(/\r$/, "", $0)
          sub(/^[[:space:]]+/, "", $0)
          sub(/[[:space:]]+$/, "", $0)
          if ($0 == "") next

          # 已带 Shadowrocket/Mihomo 风格前缀则直接保留
          if ($0 ~ /^(DOMAIN|DOMAIN-SUFFIX|DOMAIN-KEYWORD|IP-CIDR|IP-CIDR6|URL-REGEX|USER-AGENT),/) {
            print $0
          } else {
            print default_type "," $0
          }
        }
      ' >> "$merged_file"
}

process_one_txt() {
  local txt_file="$1"
  local base_name out_file tmp_dir cache_dir merged_file final_file
  local count valid_count url yaml_file rule_type

  base_name="$(basename "$txt_file" .txt)"
  out_file="${OUT_DIR}/${base_name}.list"

  echo "==> Processing: ${txt_file}"
  echo "    Output    : ${out_file}"

  tmp_dir="$(mktemp -d)"
  cache_dir="${tmp_dir}/cache"
  merged_file="${tmp_dir}/merged.txt"
  final_file="${tmp_dir}/final.txt"
  mkdir -p "$cache_dir"
  : > "$merged_file"
  : > "$final_file"

  count=0
  valid_count=0

  while IFS= read -r url || [[ -n "$url" ]]; do
    count=$((count + 1))
    rule_type="$(detect_rule_type "$url")"

    echo "  - Download[${count}]: ${url} (${rule_type})"
    yaml_file="$(download_with_cache "$url" "$cache_dir")"

    append_rules_from_yaml "$yaml_file" "$rule_type" "$merged_file"
    valid_count=$((valid_count + 1))
  done < <(read_urls "$txt_file")

  if [[ "$valid_count" -eq 0 ]]; then
    echo "WARN: no valid URLs found in ${txt_file}"
    : > "$out_file"
    rm -rf "$tmp_dir"
    return 0
  fi

  echo "==> Stable dedup"

  # 保留首次出现顺序去重
  awk '
    NF == 0 { next }
    !seen[$0]++
  ' "$merged_file" > "$final_file"

  mv "$final_file" "$out_file"

  echo "==> Done: ${out_file}"
  wc -l "$out_file" || true

  rm -rf "$tmp_dir"
}

main() {
  local found=0
  local txt_file

  if [[ ! -d "$TXT_DIR" ]]; then
    echo "ERROR: input directory not found: ${TXT_DIR}" >&2
    exit 1
  fi

  while IFS= read -r txt_file; do
    found=1
    process_one_txt "$txt_file"
  done < <(find "$TXT_DIR" -maxdepth 1 -type f -name '*.txt' | sort)

  if [[ "$found" -eq 0 ]]; then
    echo "WARN: no txt files found under ${TXT_DIR}"
  fi

  echo "All done."
}

main "$@"