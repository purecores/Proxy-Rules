import json
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml


MIHOMO_YAML_PATH = Path(r"D:\APP\mihomo\proxies\shanhai.yaml")
SINGBOX_JSON_PATH = Path(r"D:\APP\Sing-box\config.json")
GROUPS_YAML_PATH = Path(r"D:\APP\mihomo\config.yaml")


# -----------------------------
# IO helpers
# -----------------------------
def load_yaml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"YAML not found: {path}")
    text = path.read_text(encoding="utf-8")
    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise ValueError(f"YAML root must be dict: {path}")
    return data


def load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"JSON not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json_atomic(path: Path, obj: Dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def backup_file(path: Path) -> Path:
    bak = path.with_suffix(path.suffix + ".bak")
    shutil.copy2(path, bak)
    return bak


def ensure_list(x: Any) -> List[Any]:
    if x is None:
        return []
    if isinstance(x, list):
        return x
    return [x]


def seconds_to_duration_str(v: Any) -> Optional[str]:
    """
    mihomo 常见 interval: 300 (秒)
    sing-box 需要 duration string，如 "300s" / "5m"
    这里统一转 "Ns"
    """
    if v is None:
        return None
    try:
        iv = int(v)
        if iv <= 0:
            return None
        return f"{iv}s"
    except Exception:
        # 若用户写的是 "5m" 这种字符串，直接透传
        if isinstance(v, str) and v.strip():
            return v.strip()
        return None


# -----------------------------
# Convert: mihomo anytls -> sing-box outbound
# -----------------------------
def convert_anytls_proxy_to_singbox(proxy: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    ptype = str(proxy.get("type", "")).strip().lower()
    if ptype != "anytls":
        return None

    name = proxy.get("name") or proxy.get("tag") or ""
    if not name:
        return None

    server = proxy.get("server") or proxy.get("host")
    port = proxy.get("port")
    if server is None or port is None:
        return None

    outbound: Dict[str, Any] = {
        "type": "anytls",  # 若你的 sing-box 不支持 anytls，需要按实际类型改这里及字段映射
        "tag": str(name),
        "server": server,
        "server_port": int(port),
    }

    # 严格：避免 unknown field
    for k in ("password", "uuid", "username"):
        if k in proxy and proxy[k] not in (None, ""):
            outbound[k] = proxy[k]

    # TLS
    tls_enabled = proxy.get("tls", None)
    sni = proxy.get("sni") or proxy.get("servername")
    alpn = proxy.get("alpn")
    insecure = proxy.get("skip-cert-verify")
    fingerprint = proxy.get("fingerprint")

    tls_obj: Dict[str, Any] = {}
    if tls_enabled is True:
        tls_obj["enabled"] = True
    elif tls_enabled is False:
        tls_obj["enabled"] = False
    elif any(v is not None for v in (sni, alpn, insecure, fingerprint)):
        tls_obj["enabled"] = True

    if sni:
        tls_obj["server_name"] = sni
    if alpn:
        tls_obj["alpn"] = ensure_list(alpn)
    if insecure is not None:
        tls_obj["insecure"] = bool(insecure)
    if fingerprint:
        tls_obj["utls"] = {"enabled": True, "fingerprint": fingerprint}

    if tls_obj:
        outbound["tls"] = tls_obj

    return outbound


def extract_anytls_outbounds_from_mihomo(
    mihomo_data: Dict[str, Any],
) -> List[Dict[str, Any]]:
    proxies = mihomo_data.get("proxies") or []
    if not isinstance(proxies, list):
        return []
    outbounds: List[Dict[str, Any]] = []
    for p in proxies:
        if isinstance(p, dict):
            ob = convert_anytls_proxy_to_singbox(p)
            if ob:
                outbounds.append(ob)
    return outbounds


# -----------------------------
# Convert: proxy-groups -> sing-box group outbounds
# -----------------------------
def compile_filter_regex(pattern: str) -> Optional[re.Pattern]:
    if not pattern:
        return None
    try:
        return re.compile(pattern)
    except re.error:
        return None


def extract_proxy_groups(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    groups = data.get("proxy-groups") or []
    if not isinstance(groups, list):
        return []
    return [g for g in groups if isinstance(g, dict)]


def dedup_preserve_order(items: List[str]) -> List[str]:
    seen = set()
    out = []
    for x in items:
        if not x or x in seen:
            continue
        seen.add(x)
        out.append(x)
    return out


def build_group_outbound(
    group: Dict[str, Any], all_node_tags: List[str]
) -> Optional[Dict[str, Any]]:
    """
    按 mihomo group.type 映射：
      - select    -> sing-box selector
      - url-test  -> sing-box urltest

    节点选择规则：
      - 若有 filter：matched_nodes = regex 匹配 all_node_tags
      - 若无 filter：
          * 且 proxies 不存在/为空：matched_nodes = all_node_tags（默认包含所有节点）
          * 且 proxies 存在且非空：matched_nodes = []（只用显式 proxies）
      - outbounds = proxies(显式) + matched_nodes（去重，保序）
    """
    name = group.get("name")
    if not name:
        return None

    gtype = str(group.get("type", "select")).strip().lower()

    explicit_proxies = group.get("proxies", None)
    if explicit_proxies is None:
        explicit_proxies_list: List[str] = []
        proxies_present = False
    else:
        proxies_present = True
        explicit_proxies_list = (
            explicit_proxies if isinstance(explicit_proxies, list) else []
        )

    filter_pattern = str(group.get("filter") or "").strip()
    rx = compile_filter_regex(filter_pattern) if filter_pattern else None

    # 关键修改：无 filter 时，只有在 proxies 不存在/为空 才默认包含所有节点
    if rx is not None:
        matched_nodes = [t for t in all_node_tags if rx.search(t)]
    else:
        if (not proxies_present) or (len(explicit_proxies_list) == 0):
            matched_nodes = list(all_node_tags)
        else:
            matched_nodes = []

    outbounds_list = dedup_preserve_order(
        [p for p in explicit_proxies_list if isinstance(p, str)] + matched_nodes
    )

    if gtype in ("select", "selector"):
        return {
            "type": "selector",
            "tag": str(name),
            "outbounds": outbounds_list,
        }

    if gtype in ("url-test", "urltest"):
        ob2: Dict[str, Any] = {
            "type": "urltest",
            "tag": str(name),
            "outbounds": outbounds_list,
        }
        if group.get("url"):
            ob2["url"] = str(group["url"]).strip()
        interval = seconds_to_duration_str(group.get("interval"))
        if interval:
            ob2["interval"] = interval
        if group.get("tolerance") is not None:
            try:
                ob2["tolerance"] = int(group["tolerance"])
            except Exception:
                pass
        return ob2

    # 其他类型：保守降级为 selector
    return {
        "type": "selector",
        "tag": str(name),
        "outbounds": outbounds_list,
    }


# -----------------------------
# Rebuild outbounds (CLEAN)
# -----------------------------
def rebuild_outbounds_clean(
    config: Dict[str, Any],
    anytls_outbounds: List[Dict[str, Any]],
    group_outbounds: List[Dict[str, Any]],
) -> None:
    """
    清空原 outbounds，并重建：
      1) DIRECT / REJECT（不生成 BLOCK）
      2) anytls 节点
      3) group outbounds（selector/urltest）
    """
    config["outbounds"] = []

    # 内置
    config["outbounds"].append({"type": "direct", "tag": "DIRECT"})
    config["outbounds"].append({"type": "block", "tag": "REJECT"})

    seen = {"DIRECT", "REJECT"}

    def add_outbound(ob: Dict[str, Any]) -> None:
        tag = ob.get("tag")
        if not tag:
            return
        tag = str(tag)
        if tag in seen:
            return
        seen.add(tag)
        config["outbounds"].append(ob)

    for ob in anytls_outbounds:
        if isinstance(ob, dict):
            add_outbound(ob)

    for ob in group_outbounds:
        if isinstance(ob, dict):
            add_outbound(ob)


def main():
    mihomo_data = load_yaml(MIHOMO_YAML_PATH)
    anytls_outbounds = extract_anytls_outbounds_from_mihomo(mihomo_data)
    anytls_tags = [
        str(o["tag"]) for o in anytls_outbounds if isinstance(o, dict) and o.get("tag")
    ]

    groups_data = load_yaml(GROUPS_YAML_PATH)
    groups = extract_proxy_groups(groups_data)

    group_outbounds: List[Dict[str, Any]] = []
    for g in groups:
        ob = build_group_outbound(g, all_node_tags=anytls_tags)
        if ob:
            group_outbounds.append(ob)

    config = load_json(SINGBOX_JSON_PATH)
    backup = backup_file(SINGBOX_JSON_PATH)

    rebuild_outbounds_clean(config, anytls_outbounds, group_outbounds)
    save_json_atomic(SINGBOX_JSON_PATH, config)

    print("Done.")
    print(f"Backup saved: {backup}")
    print(f"anytls extracted: {len(anytls_outbounds)}")
    print(f"groups converted: {len(group_outbounds)}")
    print(f"final outbounds: {len(config.get('outbounds', []))}")


if __name__ == "__main__":
    main()
