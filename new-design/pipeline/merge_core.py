"""叙事分析归并核心:四主题 JSON -> 统一结构 + 跨维度 id 引用解析。纯确定性,不过模型。"""
import json, re

# ---------- 锚点校验 ----------
def anchor_clean(records, text, name_key, mention_keys):
    """剔除 mention/alias 中原文不存在的项,记录到 dropped。"""
    report=[]
    for r in records:
        for mk in mention_keys:
            if mk not in r: continue
            kept,dropped=[],[]
            for m in r[mk]:
                (kept if m in text else dropped).append(m)
            r[mk]=kept
            if dropped: report.append({"id":r.get("id"),"name":r.get(name_key),"key":mk,"dropped":dropped})
    return report

# ---------- 跨维度名称解析 ----------
def build_name_index(records, name_key="name", alias_key=None):
    """name/alias -> id 的查找表。长名优先(避免'武田'误配到别的)。"""
    idx=[]
    for r in records:
        names=[r.get(name_key,"")]
        if alias_key and r.get(alias_key): names+=list(r[alias_key])
        for n in names:
            if n: idx.append((n, r["id"]))
    idx.sort(key=lambda x:-len(x[0]))   # 长名优先
    return idx

def resolve(value, idx):
    """把一个字符串(如 owner='武田勇夫')解析成 id。返回 (id, matched_name) 或 (None,None)。"""
    if not value: return (None,None)
    for n,i in idx:
        if n==value: return (i,n)           # 精确优先
    for n,i in idx:
        if n and (n in value or value in n): return (i,n)  # 包含次之
    return (None,None)

# ---------- 主归并 ----------
def merge(text, scenes, characters, items, locations):
    out={"scenes":scenes.get("scenes",[]),
         "characters":characters.get("characters",[]),
         "items":items.get("items",[]),
         "locations":locations.get("locations",[]),
         "_validation":{"anchors":[], "xref":[]}}

    # 锚点校验各维度
    out["_validation"]["anchors"]+=anchor_clean(out["characters"], text, "name", ["aliases"])
    out["_validation"]["anchors"]+=anchor_clean(out["items"], text, "name", ["mentions"])
    out["_validation"]["anchors"]+=anchor_clean(out["locations"], text, "name", ["mentions"])

    # 索引
    char_idx=build_name_index(out["characters"],"name","aliases")
    loc_idx =build_name_index(out["locations"],"name","mentions")

    # 跨维度1: item.owner -> character id
    for it in out["items"]:
        cid,matched=resolve(it.get("owner",""), char_idx)
        if cid is not None:
            it["owner_ref"]={"character_id":cid,"matched":matched}
        elif it.get("owner"):
            out["_validation"]["xref"].append({"type":"item.owner未匹配","item":it.get("name"),"owner":it["owner"]})

    # 跨维度2: scene.location -> location id
    for sc in out["scenes"]:
        lid,matched=resolve(sc.get("location",""), loc_idx)
        if lid is not None:
            sc["location_ref"]={"location_id":lid,"matched":matched}
        elif sc.get("location") and sc.get("location")!="未明":
            out["_validation"]["xref"].append({"type":"scene.location未匹配","scene":sc.get("title"),"location":sc["location"]})

    out["counts"]={k:len(out[k]) for k in("scenes","characters","items","locations")}
    return out
