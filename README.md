# Personal Proxy Rules

A GitHub Actions pipeline that collects curated Mihomo-compatible rule sources and publishes merged rules for Mihomo, Shadowrocket, and custom V2Ray-compatible GeoSite/GeoIP databases.

## Repository layout

```text
config/
  personal/                 Private/custom rules maintained in this repository
  sources/
    mihomo/                  URL lists and GeoSite/GeoIP category configuration
    shadowrocket/            Shadowrocket-specific source lists
scripts/                     Build and validation scripts
compilation/                 Generated files and source audit, committed for static hosting
.github/
  actions/                   Reusable setup, staging, and publish actions
  workflows/                 One daily build-and-publish pipeline
tests/                       Offline parser/encoder/output regression tests
```

## Build flow

The `build-and-publish` workflow runs daily at 02:00 China Standard Time, on relevant pushes, or manually. It runs offline tests, builds all three output families, validates build outputs, and commits only changed generated files. Build failures stop publication. The workflow combines formerly separate jobs to avoid competing commits and publishes all outputs from one consistent source snapshot.

Tool versions are pinned in the workflow (`mihomo v1.19.32`, `yq v4.54.1`, Python 3.12, PyYAML 6.0.2). Update these versions deliberately and validate the workflow before merging.

## Inputs

- `config/sources/mihomo/*.txt`: one URL per line; blank lines and lines starting with `#` are ignored.
- `config/sources/mihomo/extra.yaml`: additional named GeoSite/GeoIP groups. Repeated group names are merged.
- `config/sources/shadowrocket/*.txt`: Shadowrocket-specific source URL lists.
- `config/personal/*.yaml`: personal rules, also referenced by URL lists where appropriate.

Remote inputs must expose a YAML `payload` or `rules` sequence. Failed downloads, malformed YAML, missing sources, and empty generated categories fail the build rather than silently replacing a good artifact.

## Outputs

- `compilation/mihomo/*.yaml` and `*.mrs`
- `compilation/shadowrocket/*.list`
- `compilation/GeoSite.dat` and `GeoIP.dat`

Artifacts remain available in the repository for static hosting. The existing repository URL layout stays unchanged for generated artifacts. Personal source entries use repository-local `local://personal/<file>` references, so scheduled Actions builds do not depend on the repository already being published remotely.

## Local checks

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

Mihomo generation additionally requires Bash, curl, jq, mikefarah/yq v4, and the pinned Mihomo binary on `PATH`. Shadowrocket lists are built with Python/PyYAML; source and output SHA-256/count audit metadata is written to `compilation/source-audit.json`. Large source-count changes (over 50% versus the last successful build) fail closed for review. Personal rules are read from this repository using `local://personal/<file>` references:

```bash
bash scripts/build_mihomo.sh
python scripts/build_dat.py
python scripts/build_shadowrocket.py
python scripts/validate_outputs.py
```

This repository contains personal rules. Do not publish or redistribute it without authorization.
