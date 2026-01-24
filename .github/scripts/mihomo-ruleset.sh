#!/usr/bin/env bash
set -euo pipefail

MIHOMO_BIN="${MIHOMO_BIN:-${1:-mihomo}}"

# Resolve repo root
if [[ -n "${GITHUB_WORKSPACE:-}" && -d "${GITHUB_WORKSPACE}" ]]; then
  ROOT_DIR="${GITHUB_WORKSPACE}"
elif command -v git >/dev/null 2>&1 && git rev-parse --show-toplevel >/dev/null 2>&1; then
  ROOT_DIR="$(git rev-parse --show-toplevel)"
else
  ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
fi

TXT_DIR="${ROOT_DIR}/txt/mihomo"
OUT_DIR="${ROOT_DIR}/compilation/mihomo"
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

# Check mihomo
if ! command -v "${MIHOMO_BIN}" >/dev/null 2>&1; then
  if [[ -x "${MIHOMO_BIN}" ]]; then
    :
  else
    echo "ERROR: mihomo binary not found/executable: ${MIHOMO_BIN}" >&2
    exit 1
  fi
fi

# curl opts to avoid hangs
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
extract_payload_json_array() {
  local yaml_file="$1"
  yq -o=json '.payload // .rules // []' "${yaml_file}" 2>/dev/null || echo "[]"
}

# Detect behavior for mrs compile
detect_behavior() {
  local yaml_out="$1"
  if grep -Eq '^\s*-\s*IP-CIDR6?\s*,' "${yaml_out}"; then
    echo "ipcidr"
  else
    echo "domain"
  fi
}

merge_one_group() {
  local name="$1"
  local txt_file="${TXT_DIR}/${name}.txt"
  local out_yaml="${OUT_DIR}/${name}.yaml"
  local out_mrs="${OUT_DIR}/${name}.mrs"

  if [[ ! -f "${txt_file}" ]]; then
    echo "ERROR: missing txt: ${txt_file}" >&2
    exit 1
  fi

  echo "==> Merging ${name}"
  echo "    txt : ${txt_file}"
  echo "    yaml: ${out_yaml}"

  local tmp_dir
  tmp_dir="$(mktemp -d)"
  cleanup() { rm -rf "${tmp_dir}" || true; }
  trap cleanup RETURN

  local payload_arrays_file="${tmp_dir}/payload_arrays.jsonl"
  : > "${payload_arrays_file}"

  local idx=0
  while IFS= read -r url; do
    idx=$((idx + 1))
    local dl="${tmp_dir}/${name}_${idx}.yaml"
    echo "  - Download[${idx}]: ${url}"
    curl "${CURL_COMMON_ARGS[@]}" "${url}" -o "${dl}"
    extract_payload_json_array "${dl}" >> "${payload_arrays_file}"
  done < <(read_urls "${txt_file}")

  echo "==> Dedup & Write ${name} (awk keep-order)"
  # 1) flatten jsonl arrays to one rule per line
  # 2) awk stable dedup (keep first occurrence)
  # 3) rebuild as {payload:[...]} and output YAML (overwrite)
  jq -r '.[]' "${payload_arrays_file}" \
    | awk '!seen[$0]++' \
    | jq -Rn '{payload: [inputs]}' \
    | yq -P -o=yaml '.' - > "${out_yaml}"

  echo "==> Compile ${name}"
  local behavior
  behavior="$(detect_behavior "${out_yaml}")"
  echo "    behavior=${behavior}"
  echo "    mrs: ${out_mrs}"
  "${MIHOMO_BIN}" convert-ruleset "${behavior}" yaml "${out_yaml}" "${out_mrs}"

  echo "    outputs:"
  ls -lh "${out_yaml}" "${out_mrs}" || true
}

merge_one_group "AIGC"
merge_one_group "Direct"
merge_one_group "Proxy"

echo "All done."
