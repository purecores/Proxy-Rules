#!/usr/bin/env bash
set -euo pipefail

# Resolve repo root
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

# Read URLs from txt (ignore empty lines and comment lines starting with #)
read_urls() {
  local file="$1"
  awk '
    NF == 0 { next }
    $1 ~ /^#/ { next }
    { print $0 }
  ' "${file}"
}

# Extract payload/rules to JSON array
# Supports common Mihomo rule-set structures:
# 1) payload:
#      - DOMAIN-SUFFIX,example.com
# 2) rules:
#      - DOMAIN-SUFFIX,example.com
extract_rules_json_array() {
  local yaml_file="$1"
  yq -o=json '.payload // .rules // []' "${yaml_file}" 2>/dev/null || echo "[]"
}

process_one_txt() {
  local txt_file="$1"
  local base_name
  base_name="$(basename "${txt_file}" .txt)"
  local out_file="${OUT_DIR}/${base_name}.list"

  echo "==> Processing: ${txt_file}"
  echo "    Output    : ${out_file}"

  local tmp_dir
  tmp_dir="$(mktemp -d)"
  cleanup() { rm -rf "${tmp_dir}" || true; }
  trap cleanup RETURN

  local jsonl_file="${tmp_dir}/rules.jsonl"
  : > "${jsonl_file}"

  local count=0
  while IFS= read -r url || [[ -n "${url}" ]]; do
    count=$((count + 1))
    local dl_file="${tmp_dir}/${base_name}_${count}.yaml"

    echo "  - Download[${count}]: ${url}"
    curl "${CURL_COMMON_ARGS[@]}" "${url}" -o "${dl_file}"

    extract_rules_json_array "${dl_file}" >> "${jsonl_file}"
  done < <(read_urls "${txt_file}")

  if [[ "${count}" -eq 0 ]]; then
    echo "WARN: no valid URLs found in ${txt_file}"
    : > "${out_file}"
    return 0
  fi

  echo "==> Merge & stable dedup"

  # 1) flatten all arrays to one rule per line
  # 2) remove null / empty
  # 3) stable dedup with awk, preserving first appearance order
  jq -r '.[]' "${jsonl_file}" \
    | awk '
        NF == 0 { next }
        $0 == "null" { next }
        !seen[$0]++
      ' > "${out_file}"

  echo "==> Done: ${out_file}"
  wc -l "${out_file}" || true
}

main() {
  if [[ ! -d "${TXT_DIR}" ]]; then
    echo "ERROR: input directory not found: ${TXT_DIR}" >&2
    exit 1
  fi

  local found=0
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