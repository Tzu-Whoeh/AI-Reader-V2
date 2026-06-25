#!/usr/bin/env python3
"""
漏标规则扫描器(确定性,只找疑点,不改数据)
三类检测:
  A. 锚点扫描: 实体名/别名在某场景原文出现,但该实体未被任何事件/清单挂到该场景
  B. 结构空洞: 场景里有人物名出现却无事件含该人物; 物品 mention 落在某场景却未挂该场景
  C. 引用悬空: owner 有值但未匹配到人物 id; 关系 from/to 指向不存在的 id

输出疑点清单,每条带 {type, scene, target, evidence, hint},供定向补抽。
不调用模型。
"""
import json, re

def _scene_segments(fulltext, scenes):
    segs={}
    for s in scenes:
        start_anchor=(s.get("start_text") or "")[:20]
        end_anchor=(s.get("end_text") or "")[:20]
        st=fulltext.find(start_anchor) if start_anchor else -1
        en=fulltext.find(end_anchor) if end_anchor else -1
        if st<0: st=0
        en=len(fulltext) if en<0 else en+len(end_anchor)
        segs[s.get("index")]=(st,en,fulltext[st:en])
    return segs

def scan(fulltext, merged, events):
    scenes=merged.get("scenes",[])
    chars={c["id"]:c for c in merged.get("characters",[])}
    items={it["id"]:it for it in merged.get("items",[])}
    segs=_scene_segments(fulltext, scenes)
    suspects=[]

    # 事件覆盖表: 每个场景挂了哪些人物 / 哪些物品
    scene_event_chars={s["index"]:set() for s in scenes}
    scene_event_items={s["index"]:set() for s in scenes}
    for e in events.get("parent_events",[]):
        sr=e.get("scene_ref")
        if sr in scene_event_chars:
            for p in e.get("participants",[]): scene_event_chars[sr].add(p)
    for si,subs in events.get("sub_events",{}).items():
        si=int(si) if str(si).isdigit() else si
        for se in subs:
            for p in se.get("participants",[]): scene_event_chars.get(si,set()).add(p)
            for it in se.get("items",[]): scene_event_items.get(si,set()).add(it)

    # ---- A + B(人物): 人物名出现在某场景,但该场景事件未含该人物 ----
    for s in scenes:
        si=s["index"]; _,_,seg=segs[si]
        for cid,c in chars.items():
            names=[c["name"]]+c.get("aliases",[])
            appears=any(n and n in seg for n in names)
            if appears and cid not in scene_event_chars.get(si,set()):
                # 该人物在这一幕出现,却没有事件挂他 → 疑似漏事件/漏participant
                hit=next((n for n in names if n and n in seg),"")
                suspects.append({"type":"人物出现未挂事件","scene":si,
                    "target":c["name"],"target_id":cid,"evidence":hit,
                    "hint":f"场景{si}原文出现「{hit}」,但无事件含该人物,可能漏了他参与的事件或漏标 participant"})

    # ---- B(物品): 物品 mention 落在某场景区间,但物品 scene 未指向该场景 ----
    for it_id,it in items.items():
        cur=it.get("scene")
        cur_set=set(cur) if isinstance(cur,list) else ({cur} if cur is not None else set())
        for m in it.get("mentions",[]):
            pos=fulltext.find(m)
            if pos<0: continue
            for s in scenes:
                st,en,_=segs[s["index"]]
                if st<=pos<=en and s["index"] not in cur_set:
                    suspects.append({"type":"物品漏挂场景","scene":s["index"],
                        "target":it["name"],"target_id":it_id,"evidence":m,
                        "hint":f"物品「{it['name']}」的提及「{m}」落在场景{s['index']},但其 scene={cur} 未含该场景"})
                    break

    # ---- C: 引用悬空 ----
    # owner 有值但无 owner_ref
    for it in merged.get("items",[]):
        if it.get("owner") and not it.get("owner_ref"):
            suspects.append({"type":"owner未匹配人物","scene":it.get("scene"),
                "target":it["name"],"evidence":it["owner"],
                "hint":f"物品「{it['name']}」owner=「{it['owner']}」未匹配到人物 id,可能该人物漏识别"})
    # 关系 id 悬空
    cid_set=set(chars); 
    for r in merged.get("character_relations",[]):
        for end in ("from_id","to_id"):
            if r.get(end) not in cid_set:
                suspects.append({"type":"关系id悬空","scene":None,
                    "target":f"{r.get('relation_type')} {r.get('label','')}","evidence":f"{end}={r.get(end)}",
                    "hint":f"人物关系的 {end}={r.get(end)} 不在人物清单,上游可能漏识别该人物"})

    return suspects

def group_by_scene(suspects):
    g={}
    for s in suspects: g.setdefault(s.get("scene"),[]).append(s)
    return g

if __name__=="__main__":
    import sys
    fulltext=open(sys.argv[1],encoding="utf-8").read()
    merged=json.load(open(sys.argv[2],encoding="utf-8"))
    events=json.load(open(sys.argv[3],encoding="utf-8"))
    sus=scan(fulltext, merged, events)
    print(json.dumps(sus, ensure_ascii=False, indent=2))