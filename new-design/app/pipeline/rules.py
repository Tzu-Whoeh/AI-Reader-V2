#!/usr/bin/env python3
"""
清洗/拆章规则层(纯标准库,确定性)。

三层存储(库根 LIB 下 rules/):
  presets.json   内置预制规则(只读,随代码发布;运行时不写)
  custom.json    用户自定义规则 + 用户预设      {rules:[...], presets:[{name, enabled:[id...]}]}
  default.json   全局默认勾选集                {enabled:[id...]}

每条规则: {id, kind:"noise"|"chapter", name, pattern, builtin:bool, desc, default_chapter?:bool}

每本书在 meta.json 里记 rules_selected:[id...](覆盖全局默认);
clean_fingerprint 记"上次分析所用规则集"的指纹,用于脏标记。
"""
import os, json, hashlib

_LIB = None  # 由 set_library 注入

def set_library(lib):
    global _LIB
    _LIB = lib
    os.makedirs(_rules_dir(), exist_ok=True)

def _rules_dir():   return os.path.join(_LIB, "rules")
def _presets_path(): return os.path.join(_rules_dir(), "presets.json")
def _custom_path():  return os.path.join(_rules_dir(), "custom.json")
def _default_path(): return os.path.join(_rules_dir(), "default.json")

# 预制随包发布;若库目录缺失,回退到模块同级的 presets 种子(部署时一并放）
_SEED_PRESETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_presets_seed.json")

def _load_json(path, fallback):
    if not os.path.isfile(path):
        return fallback
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:
        return fallback

def load_presets():
    d = _load_json(_presets_path(), None)
    if d is None:
        d = _load_json(_SEED_PRESETS, {"version": 1, "rules": []})
    return d.get("rules", [])

def load_custom():
    d = _load_json(_custom_path(), {"rules": [], "presets": []})
    d.setdefault("rules", []); d.setdefault("presets", [])
    return d

def save_custom(data):
    data.setdefault("rules", []); data.setdefault("presets", [])
    _atomic_write(_custom_path(), data)

def load_default_enabled():
    d = _load_json(_default_path(), None)
    if d and isinstance(d.get("enabled"), list):
        return d["enabled"]
    # 首次:默认启用全部内置 noise + 默认开启的 chapter 规则
    ids = []
    for r in load_presets():
        if r["kind"] == "noise":
            ids.append(r["id"])
        elif r["kind"] == "chapter" and r.get("default_chapter"):
            ids.append(r["id"])
    return ids

def save_default_enabled(ids):
    _atomic_write(_default_path(), {"enabled": list(ids)})

def _atomic_write(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)

# ---------- 规则解析 ----------
def all_rules():
    """预制 + 自定义,合并(自定义不可覆盖预制 id)。"""
    presets = load_presets()
    custom = load_custom()["rules"]
    seen = {r["id"] for r in presets}
    out = list(presets)
    for r in custom:
        if r.get("id") and r["id"] not in seen:
            out.append({**r, "builtin": False})
            seen.add(r["id"])
    return out

def _rule_map():
    return {r["id"]: r for r in all_rules()}

def resolve_enabled(selected_ids):
    """给定勾选的 id 列表,返回 (noise_patterns, chapter_patterns)。
    selected_ids 为 None → 用全局默认。"""
    ids = selected_ids if selected_ids is not None else load_default_enabled()
    rm = _rule_map()
    noise, chap = [], []
    for rid in ids:
        r = rm.get(rid)
        if not r:
            continue
        if r["kind"] == "noise":
            noise.append(r["pattern"])
        elif r["kind"] == "chapter":
            chap.append(r["pattern"])
    return noise, chap

def fingerprint(selected_ids):
    """规则集指纹:对启用规则的 (id,pattern) 排序后 hash。
    用于判断'分析时所用规则'与'当前勾选'是否一致(脏标记)。"""
    ids = selected_ids if selected_ids is not None else load_default_enabled()
    rm = _rule_map()
    items = sorted((rid, rm.get(rid, {}).get("pattern", "")) for rid in ids)
    h = hashlib.md5(json.dumps(items, ensure_ascii=False).encode("utf-8")).hexdigest()
    return h