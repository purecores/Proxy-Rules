#!/usr/bin/env bash
set -euo pipefail

# Workdir is repository root (GitHub Actions default)

mkdir -p compilation/pcdn
mkdir -p .tmp/pcdn

SRC_URL="https://raw.githubusercontent.com/uselibrary/PCDN/main/pcdn.list"
SRC_FILE=".tmp/pcdn/pcdn.list"

curl -fsSL "$SRC_URL" -o "$SRC_FILE"

python3 - <<'PY'
import json
from pathlib import Path

text = Path(".tmp/pcdn/pcdn.list").read_text(encoding="utf-8", errors="ignore")
tokens = text.split()

domains = []
suffixes = []
regexes = []

def add(lst, v):
  if v not in lst:
    lst.append(v)

for t in tokens:
  if "," not in t or t.startswith("#"):
    continue
  k, v = t.split(",", 1)
  v = v.strip()
  if not v:
    continue
  if k == "DOMAIN":
    add(domains, v)
  elif k == "DOMAIN-SUFFIX":
    add(suffixes, v)
  elif k == "DOMAIN-REGEX":
    add(regexes, v)

# ---------- mihomo yaml ----------
# payload only, no comments
payload = []
for s in suffixes:
  payload.append(f"+.{s}")
for d in domains:
  payload.append(d)

mihomo_yaml = ["payload:"]
for item in payload:
  mihomo_yaml.append(f'  - "{item}"')

Path(".tmp/pcdn/mihomo-pcdn.yaml").write_text(
  "\n".join(mihomo_yaml) + "\n",
  encoding="utf-8"
)

# ---------- sing-box json ----------
singbox = {
  "version": 2,
  "rules": [
    {
      "domain": domains,
      "domain_suffix": suffixes,
      "domain_regex": regexes
    }
  ]
}

Path(".tmp/pcdn/singbox-pcdn.json").write_text(
  json.dumps(singbox, ensure_ascii=False, indent=2) + "\n",
  encoding="utf-8"
)
PY

mv -f .tmp/pcdn/mihomo-pcdn.yaml  compilation/pcdn/mihomo-pcdn.yaml
mv -f .tmp/pcdn/singbox-pcdn.json compilation/pcdn/singbox-pcdn.json

# mihomo: convert source yaml -> mrs (domain)
mihomo convert-ruleset domain yaml \
  compilation/pcdn/mihomo-pcdn.yaml \
  compilation/pcdn/mihomo-pcdn.mrs

# sing-box: compile source json -> srs
sing-box rule-set compile \
  --output compilation/pcdn/singbox-pcdn.srs \
  compilation/pcdn/singbox-pcdn.json

ls -lah compilation/pcdn
