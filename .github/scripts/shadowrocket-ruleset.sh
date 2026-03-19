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
require_cmd jq
require_cmd yq
require_cmd awk
require_cmd find

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
    $1 ~ /^#/ { next }
    { print $0 }
  ' "${file}"
}

detect_rule_type() {
  local url="$1"

  if [[ "$url" == *"/geosite/"* ]]; then
    echo "DOMAIN-SUFFIX"
  elif [[ "$url" == *"/geoip/"* ]]; then
    echo "IP-CIDR"
  else
    echo ""
  fi
}

extract_payload_items() {
  local yaml_file="$1"
  yq -o=json '.payload // .rules // []' "${yaml_file}" 2>/dev/null || echo "[]"
}

normalize_rule_line() {
  local rule_type="$1"
  local value="$2"

  # 去掉首尾空白
  value="$(printf '%s' "$value" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"

  # 空值直接跳过
  [[ -z "$value" ]] && return 1

  # 如果上游已经带规则类型，则直接使用，避免重复前缀
  case "$value" in
    DOMAIN,*|DOMAIN-SUFFIX,*|DOMAIN-KEYWORD,*|IP-CIDR,*|IP-CIDR6,*|URL-REGEX,*|USER-AGENT,*)
      printf '%s\n' "$value"
      return 0
      ;;
  esac

  # 根据来源 URL 补规则类型
  if [[ "$rule_type" == "DOMAIN-SUFFIX" ]]; then
    printf 'DOMAIN-SUFFIX,%s\n' "$value"
    return 0
  elif [[ "$rule_type" == "IP-CIDR" ]]; then
    printf 'IP-CIDR,%s\n' "$value"
    return 0
  fi

  return 1
}

process_one_txt() {
  local txt_file="$1"
  local base_name out_file tmp_dir merged_file final_file
  local count url dl_file rule_type

  base_name="$(basename "${txt_file}" .txt)"
  out_file="${OUT_DIR}/${base_name}.list"

  echo "==> Processing: ${txt_file}"
  echo "    Output    : ${out_file}"

  tmp_dir="$(mktemp -d)"
  merged_file="${tmp_dir}/merged.txt"
  final_file="${tmp_dir}/final.txt"
  : > "${merged_file}"
  : > "${final_file}"

  count=0
  while IFS= read -r url || [[ -n "${url}" ]]; do
    count=$((count + 1))
    dl_file="${tmp_dir}/${base_name}_${count}.yaml"
    rule_type="$(detect_rule_type "${url}")"

    if [[ -z "${rule_type}" ]]; then
      echo "WARN: skip unsupported url type: ${url}"
      continue
    fi

    echo "  - Download[${count}]: ${url} (${rule_type})"
    curl "${CURL_COMMON_ARGS[@]}" "${url}" -o "${dl_file}"

    while IFS= read -r item; do
      normalize_rule_line "${rule_type}" "${item}" >> "${merged_file}" || true
    done < <(extract_payload_items "${dl_file}" | jq -r '.[]')
  done < <(read_urls "${txt_file}")

  if [[ "${count}" -eq 0 ]]; then
    echo "WARN: no valid URLs found in ${txt_file}"
    : > "${out_file}"
    rm -rf "${tmp_dir}"
    return 0
  fi

  echo "==> Merge & stable dedup"

  awk '
    NF == 0 { next }
    !seen[$0]++
  ' "${merged_file}" > "${final_file}"

  mv "${final_file}" "${out_file}"

  echo "==> Done: ${out_file}"
  wc -l "${out_file}" || true

  rm -rf "${tmp_dir}"
}

main() {
  local found=0
  local txt_file

  if [[ ! -d "${TXT_DIR}" ]]; then
    echo "ERROR: input directory not found: ${TXT_DIR}" >&2
    exit 1
  fi

  while IFS= read -r txt_file; do
    found=1
    process_one_txt "${txt_file}"
  done < <(find "${TXT_DIR}" -maxdepth 1 -type f -name '*.txt' | sort)

  if [[ "${found}" -eq 0 ]]; then
    echo "WARN: no txt files found under ${TXT_DIR}"
  fi

  echo "All done."
}

main "$@"