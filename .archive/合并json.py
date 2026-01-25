#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
功能：
- 读取多个指定的 .txt 文件（每行一个 JSON 规则集 URL，忽略空行与 # 注释行）
- 下载这些 URL 的 JSON
- 合并到 singbox/ 子文件夹里与 txt 同名的 .json（去重并保序追加 rules）
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Tuple


# ===================== 可修改配置区 =====================

# 1) 在这里手动指定需要处理的多个 txt 文件（不遍历目录）
TXT_FILES: List[str] = [
    Path("./txt/singbox/AIGC.txt"),
    Path("./txt/singbox/Dev.txt"),
    Path("./txt/singbox/Direct.txt"),
    Path("./txt/singbox/Proxy.txt"),
]

# 2) 输出目录：会写入到该目录下的 <txt同名>.json
SINGBOX_DIR = Path("singbox")

# 3) 网络参数
HTTP_TIMEOUT_SECONDS = 30
USER_AGENT = "singbox-ruleset-merger/1.0"

# ===================== 实现代码区（一般无需改） =====================


def iter_urls_from_txt(txt_path: Path) -> List[str]:
    urls: List[str] = []
    with txt_path.open("r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            if line.startswith("#"):
                continue
            urls.append(line)
    return urls


def http_get_json(url: str) -> Dict[str, Any]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/plain, */*",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
        data = resp.read()
    try:
        return json.loads(data.decode("utf-8"))
    except UnicodeDecodeError:
        # 极少数情况下不是 utf-8，可退回用 latin1 再解析（尽量不报错）
        return json.loads(data.decode("latin1"))


def load_local_ruleset(path: Path) -> Dict[str, Any]:
    if not path.exists():
        # 新建一个空的 sing-box 规则集骨架
        return {"version": 1, "rules": []}

    with path.open("r", encoding="utf-8") as f:
        obj = json.load(f)

    # 基本兜底，确保符合常见 ruleset 结构
    if not isinstance(obj, dict):
        raise ValueError(f"本地规则文件不是 JSON object: {path}")
    if "version" not in obj:
        obj["version"] = 1
    if "rules" not in obj or not isinstance(obj["rules"], list):
        obj["rules"] = []
    return obj


def canonical_rule_key(rule: Any) -> str:
    """
    用于 rules 去重：对每个 rule 项做稳定序列化作为 key。
    规则项一般是 dict（对象），也可能是其他 JSON 类型，这里统一处理。
    """
    return json.dumps(rule, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def merge_rules_keep_order(
    local_rules: List[Any], incoming_rules: List[Any]
) -> Tuple[List[Any], int]:
    """
    去重并保序追加：保留 local_rules 原顺序，然后按 incoming_rules 顺序追加未出现过的项。
    返回：(合并后的rules, 新增条数)
    """
    seen = set()
    merged: List[Any] = []

    for r in local_rules:
        k = canonical_rule_key(r)
        if k in seen:
            continue
        seen.add(k)
        merged.append(r)

    added = 0
    for r in incoming_rules:
        k = canonical_rule_key(r)
        if k in seen:
            continue
        seen.add(k)
        merged.append(r)
        added += 1

    return merged, added


def normalize_ruleset(obj: Dict[str, Any]) -> Dict[str, Any]:
    """
    归一化：确保有 version(int) 与 rules(list)。
    不强行改写其它字段，尽量保持原样。
    """
    if "version" not in obj or not isinstance(obj["version"], int):
        obj["version"] = 1
    if "rules" not in obj or not isinstance(obj["rules"], list):
        obj["rules"] = []
    return obj


def merge_one_txt(txt_path: Path, out_dir: Path) -> None:
    urls = iter_urls_from_txt(txt_path)
    if not urls:
        print(f"[SKIP] {txt_path} 中没有可用 URL")
        return

    out_dir.mkdir(parents=True, exist_ok=True)
    out_json = out_dir / f"{txt_path.stem}.json"

    local = load_local_ruleset(out_json)
    local = normalize_ruleset(local)

    total_added = 0
    total_incoming = 0

    for url in urls:
        try:
            incoming = http_get_json(url)
        except Exception as e:
            print(f"[WARN] 下载失败：{url}  ({e})")
            continue

        if not isinstance(incoming, dict):
            print(f"[WARN] 远端内容不是 JSON object，跳过：{url}")
            continue

        incoming = normalize_ruleset(incoming)
        incoming_rules = incoming.get("rules", [])
        if not isinstance(incoming_rules, list):
            print(f"[WARN] 远端 rules 不是数组，跳过：{url}")
            continue

        local_rules = local.get("rules", [])
        merged_rules, added = merge_rules_keep_order(local_rules, incoming_rules)
        local["rules"] = merged_rules

        total_incoming += len(incoming_rules)
        total_added += added

    # version 处理策略：优先保留本地 version；若本地不存在则使用 1（上面已兜底）
    # 如你需要强制跟随远端 version，可自行改这里。

    with out_json.open("w", encoding="utf-8") as f:
        json.dump(local, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(
        f"[OK] {txt_path.name} -> {out_json.as_posix()} | "
        f"远端rules合计={total_incoming}, 新增={total_added}, 合并后总数={len(local['rules'])}"
    )


def main() -> int:
    if not TXT_FILES:
        print("请先在脚本中填写 TXT_FILES 列表（指定一个或多个 .txt 文件路径）。")
        return 2

    for p in TXT_FILES:
        txt_path = Path(p).expanduser().resolve()
        if not txt_path.exists() or txt_path.suffix.lower() != ".txt":
            print(f"[SKIP] 不存在或不是 .txt：{txt_path}")
            continue

        try:
            merge_one_txt(txt_path, SINGBOX_DIR)
        except Exception as e:
            print(f"[ERROR] 处理失败：{txt_path} ({e})")
            # 不中断其它文件
            continue

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
