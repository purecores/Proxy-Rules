# .github/scripts/singbox-ruleset.sh
#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK_DIR="$(mktemp -d)"
trap 'rm -rf "${WORK_DIR}"' EXIT

TXT_DIR="${ROOT_DIR}/txt/singbox"
OUT_DIR="${ROOT_DIR}/compilation/singbox"

mkdir -p "${OUT_DIR}"

# 过滤空行/注释行，兼容 CRLF
read_urls() {
  local file="$1"
  sed -e 's/\r$//' -e '/^[[:space:]]*$/d' -e '/^[[:space:]]*#/d' "$file"
}

build_one() {
  local name="$1"
  local url_file="${TXT_DIR}/${name}.txt"
  local out_json="${OUT_DIR}/${name}.json"
  local out_srs="${OUT_DIR}/${name}.srs"

  if [[ ! -f "${url_file}" ]]; then
    echo "ERROR: missing ${url_file}" >&2
    exit 1
  fi

  echo "==> Building ${name}"

  local rules_ndjson="${WORK_DIR}/${name}.rules.ndjson"
  local versions_nd="${WORK_DIR}/${name}.versions.txt"
  : > "${rules_ndjson}"
  : > "${versions_nd}"

  # 按 txt 中 URL 顺序逐个合并
  while IFS= read -r url; do
    echo "  -> Fetch: ${url}"

    json="$(curl -fsSL --retry 3 --retry-delay 1 "${url}")"
    echo "${json}" | jq -e . >/dev/null

    # 收集 version（默认 3）
    echo "${json}" | jq -r '(.version // 3) | tostring' >> "${versions_nd}"

    # 按源文件原始顺序输出每条 rule（缺省 rules 视为 []）
    echo "${json}" | jq -c '.rules // [] | .[]' >> "${rules_ndjson}"
  done < <(read_urls "${url_file}")

  # version 取最大值；若无来源则默认 3
  local ver
  if [[ -s "${versions_nd}" ]]; then
    ver="$(awk 'BEGIN{m=0} {v=$1+0; if(v>m)m=v} END{if(m==0)m=3; print m}' "${versions_nd}")"
  else
    ver="3"
  fi

  # 顺序稳定去重：首次出现保留，后续重复丢弃
  # 以对象 tostring 作为去重 key（不会打乱顺序）
  jq -s --argjson ver "${ver}" '
    reduce .[] as $r (
      { seen: {}, rules: [] };
      ($r | tostring) as $k
      | if .seen[$k]
        then .
        else .seen[$k] = true
             | .rules += [$r]
        end
    )
    | { version: $ver, rules: .rules }
  ' "${rules_ndjson}" > "${out_json}"

  # 基础校验
  jq -e '.version and (.rules|type=="array")' "${out_json}" >/dev/null

  echo "  -> Wrote: ${out_json}"

  # 编译为 srs（同目录同名）
  sing-box rule-set compile --output "${out_srs}" "${out_json}"
  echo "  -> Wrote: ${out_srs}"
}

build_one "AIGC"
build_one "Direct"
build_one "Proxy"

echo "All done."
