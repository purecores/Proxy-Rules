#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

import requests
import yaml


# ========== 你只需要改这里：指定要处理的多个 txt 文件 ==========
TXT_FILES = [
    Path("./txt/mihomo/AIGC.txt"),
    Path("./txt/mihomo/Dev.txt"),
    Path("./txt/mihomo/Direct.txt"),
    Path("./txt/mihomo/Proxy.txt"),
]

MIHOMO_DIR = Path("mihomo")  # 输出目录
TIMEOUT = 30  # 下载超时（秒）
# =========================================================


def read_urls_from_txt(txt_path: Path) -> List[str]:
    urls: List[str] = []
    text = txt_path.read_text(encoding="utf-8", errors="ignore")
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # 支持行末注释：URL # comment
        if "#" in line:
            line = line.split("#", 1)[0].strip()
        if line:
            urls.append(line)
    return urls


def download_text(url: str, timeout: int = 30) -> str:
    headers = {"User-Agent": "mihomo-rule-merger/1.0"}
    r = requests.get(url, headers=headers, timeout=timeout)
    r.raise_for_status()
    r.encoding = r.encoding or "utf-8"
    return r.text


def load_yaml_mapping(text: str, source: str) -> Dict[str, Any]:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise ValueError(f"YAML 解析失败: {source}: {e}") from e

    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"YAML 顶层不是 mapping(dict): {source}")
    return data


def extract_payload(yaml_obj: Dict[str, Any], source: str) -> List[Any]:
    payload = yaml_obj.get("payload", [])
    if payload is None:
        return []
    if not isinstance(payload, list):
        raise ValueError(f"payload 不是 list: {source}")
    return payload


def load_local_yaml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {"payload": []}
    text = path.read_text(encoding="utf-8", errors="ignore")
    obj = load_yaml_mapping(text, str(path))
    if "payload" not in obj or obj["payload"] is None:
        obj["payload"] = []
    if not isinstance(obj["payload"], list):
        raise ValueError(f"本地文件 payload 不是 list: {path}")
    return obj


def _keyify(item: Any) -> str:
    """
    payload 通常是字符串；若出现 dict/list，则用稳定序列化做 key，以便去重。
    """
    if isinstance(item, str):
        return item
    return yaml.safe_dump(item, allow_unicode=True, sort_keys=True).strip()


def dedup_and_append_preserve_order(
    existing: List[Any], incoming: List[Any]
) -> Tuple[List[Any], int]:
    seen = set()
    result: List[Any] = []

    for it in existing:
        k = _keyify(it)
        if k not in seen:
            seen.add(k)
            result.append(it)

    added = 0
    for it in incoming:
        k = _keyify(it)
        if k not in seen:
            seen.add(k)
            result.append(it)
            added += 1

    return result, added


class MihomoDumper(yaml.SafeDumper):
    """
    控制 YAML 输出风格与缩进：
    - 列表按块样式输出（- item）
    - 缩进更符合常见配置文件阅读习惯
    """

    pass


def _increase_indent(self, flow=False, indentless=False):
    # 避免列表项“缩进丢失”，让嵌套结构更标准
    return yaml.SafeDumper.increase_indent(self, flow=flow, indentless=False)


MihomoDumper.increase_indent = _increase_indent  # type: ignore


def dump_yaml_pretty(path: Path, data: Dict[str, Any]) -> None:
    """
    输出为常见“标准缩进”的 YAML：
    - indent=2（需要可改）
    - default_flow_style=False 强制块样式
    - sort_keys=False 保持键顺序（例如 payload 在前/后由原对象决定）
    """
    content = yaml.dump(
        data,
        Dumper=MihomoDumper,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
        indent=2,
        width=120,
    )
    # 习惯上文件以换行结束
    if not content.endswith("\n"):
        content += "\n"
    path.write_text(content, encoding="utf-8")


def process_txt(txt_path: Path) -> None:
    if not txt_path.exists():
        print(f"[SKIP] 不存在: {txt_path}")
        return

    urls = read_urls_from_txt(txt_path)
    if not urls:
        print(f"[SKIP] 未发现 URL: {txt_path}")
        return

    target_yaml = MIHOMO_DIR / f"{txt_path.stem}.yaml"
    local_obj = load_local_yaml(target_yaml)
    merged_payload: List[Any] = list(local_obj["payload"])  # type: ignore

    total_added = 0
    for url in urls:
        try:
            remote_text = download_text(url, timeout=TIMEOUT)
            remote_obj = load_yaml_mapping(remote_text, url)
            remote_payload = extract_payload(remote_obj, url)

            merged_payload, added = dedup_and_append_preserve_order(
                merged_payload, remote_payload
            )
            total_added += added
            print(f"[OK]  {txt_path.name} <= {url} (+{added})")
        except Exception as e:
            print(f"[ERR] {txt_path.name} <= {url}: {e}")

    local_obj["payload"] = merged_payload

    MIHOMO_DIR.mkdir(parents=True, exist_ok=True)
    dump_yaml_pretty(target_yaml, local_obj)
    print(f"[WRITE] {target_yaml} 新增 {total_added} 条，合计 {len(merged_payload)} 条")


def main() -> None:
    for p in TXT_FILES:
        process_txt(p)


if __name__ == "__main__":
    main()
