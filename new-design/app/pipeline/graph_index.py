#!/usr/bin/env python3
"""
图索引构建器(确定性)
扫描章节归并产物 + 两层事件,把所有【正向边】反向汇总,
为每个实体生成"谁指向我 / 我连到谁"的邻接表,使图【全向可达】:
从任意人物/物品/地点/场景/事件节点出发,都能一跳列出其全部邻居。

不改提示词、不调模型。输入是已有的 _merged.json + events_twolayer.json。
"""
import json
from collections import defaultdict

def build_graph(merged, events):
    """返回 {nodes, adjacency},节点用 '类型:id' 作全局键。"""
    adj=defaultdict(lambda: defaultdict(list))  # node -> relation -> [neighbor nodes]
    def link(a, rel, b, inv_rel):
        adj[a][rel].append(b)
        adj[b][inv_rel].append(a)

    def C(i): return f"character:{i}"
    def I(i): return f"item:{i}"
    def L(i): return f"location:{i}"
    def S(i): return f"scene:{i}"
    def E(i): return f"event:{i}"

    chars={c["id"]:c for c in merged.get("characters",[])}
    items={it["id"]:it for it in merged.get("items",[])}
    locs={l["id"]:l for l in merged.get("locations",[])}
    scenes={s["index"]:s for s in merged.get("scenes",[])}

    # 人物-人物关系(有向,带类型)
    for r in merged.get("character_relations",[]):
        f,t=r.get("from_id"),r.get("to_id")
        if f in chars and t in chars:
            adj[C(f)][f"rel:{r.get('relation_type','')}→"].append(C(t))
            adj[C(t)][f"rel:{r.get('relation_type','')}←"].append(C(f))

    # 物品→人物(owner)
    for it in merged.get("items",[]):
        ref=it.get("owner_ref")
        if ref and ref.get("character_id") in chars:
            link(I(it["id"]),"属于", C(ref["character_id"]),"拥有物品")
        # 物品→地点(location_refs)
        for lr in it.get("location_refs",[]) or []:
            if lr.get("location_id") in locs:
                link(I(it["id"]),"位于", L(lr["location_id"]),"含物品")
        # 物品→物品(part_of)
        po=it.get("part_of")
        if po and po.get("whole_id") in items:
            link(I(it["id"]),"部分属于", I(po["whole_id"]),"包含部件")

    # 场景→地点
    for s in merged.get("scenes",[]):
        ref=s.get("location_ref")
        if ref and ref.get("location_id") in locs:
            link(S(s["index"]),"发生于", L(ref["location_id"]),"承载场景")

    # 地点-地点关系
    for r in merged.get("location_relations",[]):
        f,t=r.get("from_id"),r.get("to_id")
        if f in locs and t in locs:
            adj[L(f)][f"loc:{r.get('relation_type','')}→"].append(L(t))
            adj[L(t)][f"loc:{r.get('relation_type','')}←"].append(L(f))

    # 事件→人物/场景/地点/物品
    for idx,e in enumerate(events.get("parent_events",[])):
        eid=idx
        for p in e.get("participants",[]):
            if p in chars: link(E(eid),"参与者", C(p),"参与事件")
        if e.get("scene_ref") in scenes:
            link(E(eid),"发生场景", S(e["scene_ref"]),"含事件")
        ref=e.get("location_ref")
        if ref and ref.get("location_id") in locs:
            link(E(eid),"发生地点", L(ref["location_id"]),"事件地点")
    # 子事件→物品/人物/父事件
    for si,subs in events.get("sub_events",{}).items():
        for j,se in enumerate(subs):
            sid=f"{si}.{j}"
            for it_id in se.get("items",[]):
                if it_id in items: link(E(f"sub{sid}"),"涉及物品", I(it_id),"被事件涉及")
            for p in se.get("participants",[]):
                if p in chars: link(E(f"sub{sid}"),"参与者", C(p),"参与事件")
            par=se.get("parent")
            if isinstance(par,int): link(E(f"sub{sid}"),"子事件属于", E(par),"含子事件")

    # 节点标签表
    labels={}
    for i,c in chars.items(): labels[C(i)]=c["name"]
    for i,it in items.items(): labels[I(i)]=it["name"]
    for i,l in locs.items(): labels[L(i)]=l["name"]
    for i,s in scenes.items(): labels[S(i)]=s.get("title","")
    for idx,e in enumerate(events.get("parent_events",[])): labels[E(idx)]=e.get("desc","")

    return {"adjacency":{k:dict(v) for k,v in adj.items()}, "labels":labels}

def neighbors(graph, node):
    """列出某节点的所有邻居(全向)。"""
    return graph["adjacency"].get(node,{})

def describe(graph, node):
    """人类可读地描述一个节点连到什么。"""
    lab=graph["labels"]
    out=[f"【{lab.get(node,node)}】({node})"]
    for rel,nbrs in neighbors(graph,node).items():
        names=", ".join(lab.get(n,n) for n in nbrs)
        out.append(f"  {rel}: {names}")
    return "\n".join(out)

if __name__=="__main__":
    import sys
    merged=json.load(open(sys.argv[1],encoding="utf-8"))
    events=json.load(open(sys.argv[2],encoding="utf-8"))
    g=build_graph(merged,events)
    print(json.dumps(g,ensure_ascii=False,indent=2))
