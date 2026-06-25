#!/usr/bin/env python3
"""组织抽取后处理(确定性,不调模型)。挂在 09_org 抽取之后,根治验证发现的两类问题:
1. 全/半角失配 → NFKC 归一后再锚点校验。
2. 过抽泛指/人物 → 停用清单 + 低频边缘(单 mention)在多块/多次里需复现才保留。
设计原则(AGENT.md §8):用确定性后处理兜底,不把规则堆进 prompt。"""
import unicodedata, re

def _nfkc(s): return unicodedata.normalize("NFKC", s or "")

# 泛指/方位/阵营泛称——不是具体可定位的组织实体,过抽常客。
# 注:保守清单,只排明确泛指;真组织名(军统/76号/地下党…)不在内。
STOPWORDS = {
    "重庆方面", "南京方面", "延安方面", "日本人", "日本方面", "中国人",
    "敌方", "我方", "对方", "各方", "某方", "共方", "国方",
    "上面", "上头", "组织上",
    # 注:"总部/政府/当局"等去掉硬停用——它们常是具名组织的一部分(如"特工总部"),
    # 误杀风险高;过抽这类改由"低频边缘需复现"与人工 ambiguities 兜底。
}

def normalize_anchor_ok(needle, text):
    """NFKC 归一后判断 needle 是否逐字(归一意义上)出现在 text。"""
    if not needle: return False
    return _nfkc(needle) in _nfkc(text)

def clean_organizations(obj, text, min_mentions_for_singleton=1):
    """对单章抽取结果做后处理。返回 (cleaned_obj, dropped_log)。
    - text: 本章原文(用于 NFKC 锚点校验)。
    - min_mentions_for_singleton: 单 mention 的边缘组织保留门槛(单章内通常=1;
      跨块/多次复核场景可调高,见 FINDINGS「低频边缘需≥2」)。
    """
    dropped = []
    orgs_in = obj.get("organizations", [])
    kept_orgs = []
    id_remap_valid = set()

    for o in orgs_in:
        name = o.get("name", "")
        # 1) 停用泛指
        if _nfkc(name) in {_nfkc(w) for w in STOPWORDS}:
            dropped.append(("stopword", name)); continue
        # 2) mentions:NFKC 归一锚点校验,丢掉命不中的;name 本身也要能命中
        good_mentions = [m for m in o.get("mentions", []) if normalize_anchor_ok(m, text)]
        if not normalize_anchor_ok(name, text):
            # name 在原文都找不到(归一后仍不中)→ 整条删(防自造)
            dropped.append(("name_no_anchor", name)); continue
        # 3) 低频边缘:有效 mention 数低于门槛 → 视为不稳,删
        #    (name 命中算 1;good_mentions 去重)
        uniq = set(_nfkc(m) for m in good_mentions) | {_nfkc(name)}
        if len(uniq) < min_mentions_for_singleton:
            dropped.append(("low_freq", name)); continue
        o2 = dict(o); o2["mentions"] = good_mentions
        kept_orgs.append(o2); id_remap_valid.add(o.get("id"))

    # 成员:org_id 必须指向保留下来的组织;explicit 必须有 NFKC 命中的 anchor_text
    kept_mem = []
    for m in obj.get("memberships", []):
        if m.get("org_id") not in id_remap_valid:
            dropped.append(("mem_dangling_org", m.get("character_name"))); continue
        if m.get("source") == "explicit":
            if not normalize_anchor_ok(m.get("anchor_text", ""), text):
                # 明说但锚点不中 → 降级 inferred(交人工),不直接采纳
                m = dict(m); m["source"] = "inferred"; m["anchor_text"] = ""
        kept_mem.append(m)

    # 组织关系:from/to 都要在保留集
    kept_rel = [r for r in obj.get("org_relations", [])
                if r.get("from_id") in id_remap_valid and r.get("to_id") in id_remap_valid]

    out = dict(obj)
    out["organizations"] = kept_orgs
    out["organization_count"] = len(kept_orgs)
    out["memberships"] = kept_mem
    out["org_relations"] = kept_rel
    return out, dropped