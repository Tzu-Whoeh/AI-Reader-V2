#!/usr/bin/env python3
"""组织抽取的确定性后处理 + 成员名归一(挂在 app.analyze_chapter 内,不调模型)。
来源:research/org_extraction 验证稳定后收编。
- NFKC 归一锚点(根治全/半角失配,如 76号/７６号)
- 泛指停用清单(排阵营泛称)
- 自造名删除(name 在原文 NFKC 找不到则删)
- explicit 锚点不中 → 降级 inferred(交人工)
- 成员 character_name → 章内局部 character_id 解析(供 aggregate 跨章映射)
"""
import unicodedata

def _nfkc(s): return unicodedata.normalize("NFKC", s or "")

STOPWORDS = {
    "重庆方面", "南京方面", "延安方面", "日本人", "日本方面", "中国人",
    "敌方", "我方", "对方", "各方", "某方", "共方", "国方",
    "上面", "上头", "组织上",
}

def _anchor_ok(needle, text):
    if not needle: return False
    return _nfkc(needle) in _nfkc(text)

def postprocess(obj, text):
    """对单章 09_org 抽取结果做确定性清洗。返回 cleaned dict(organizations/memberships/org_relations)。"""
    if not isinstance(obj, dict): return {"organizations": [], "memberships": [], "org_relations": []}
    stop = {_nfkc(w) for w in STOPWORDS}
    kept_orgs = []; valid_ids = set()
    for o in obj.get("organizations", []) or []:
        name = o.get("name", "")
        if _nfkc(name) in stop:            continue
        if not _anchor_ok(name, text):     continue   # 自造/改写名删
        good_m = [m for m in o.get("mentions", []) if _anchor_ok(m, text)]
        o2 = dict(o); o2["mentions"] = good_m
        kept_orgs.append(o2); valid_ids.add(o.get("id"))
    kept_mem = []
    for m in obj.get("memberships", []) or []:
        if m.get("org_id") not in valid_ids: continue
        m = dict(m)
        if m.get("source") == "explicit" and not _anchor_ok(m.get("anchor_text", ""), text):
            m["source"] = "inferred"; m["anchor_text"] = ""
        kept_mem.append(m)
    kept_rel = [r for r in (obj.get("org_relations", []) or [])
                if r.get("from_id") in valid_ids and r.get("to_id") in valid_ids]
    return {"organizations": kept_orgs, "memberships": kept_mem, "org_relations": kept_rel}

def resolve_member_ids(memberships, characters):
    """把 membership 的 character_name 解析到章内局部 character_id。
    匹配:name 或 aliases 含该称呼(NFKC)。匹配不到的丢弃(下游需要 local id 做跨章映射)。"""
    idx = []
    for c in characters or []:
        names = {_nfkc(c.get("name", ""))} | {_nfkc(a) for a in c.get("aliases", [])}
        idx.append((c.get("id"), {n for n in names if n}))
    out = []
    for m in memberships:
        cn = _nfkc(m.get("character_name", ""))
        if not cn: continue
        cid = None
        for c_id, names in idx:
            if cn in names: cid = c_id; break
        if cid is None: continue
        mm = {"character_id": cid, "org_id": m.get("org_id"), "role": m.get("role", ""),
              "source": m.get("source", "explicit"), "anchor_text": m.get("anchor_text", "")}
        out.append(mm)
    return out