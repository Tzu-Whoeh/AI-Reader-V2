"""
跨章节缝合器(确定性 + 歧义报告)
输入: 每章的 {characters, events, items, locations} JSON
输出:
  - 全局实体表(人物/物品/地点跨章归一)
  - 每个全局人物的个人时间线(跨章缝合,按故事顺序)
  - 跨人物同步点(共享事件)
  - 歧义报告(需人工确认的归并)
"""
import json
from collections import defaultdict

def norm(s): return (s or "").strip()

def resolve_global_entities(chapters, ent_key, name_key="name", alias_key=None):
    """
    跨章实体归一。返回:
      global_list: [{global_id, canonical, members:[(chapter,local_id)], all_names:set}]
      ambiguities: 需人工确认的项
    策略: name/alias 有交集 -> 同一全局实体。完全同名=高置信; 仅别名/部分重叠=歧义待确认。
    """
    nodes=[]  # 每个章节局部实体一个节点
    for ch_idx, ch in enumerate(chapters):
        for r in ch.get(ent_key, []):
            names=set([norm(r.get(name_key))])
            if alias_key and r.get(alias_key): names|={norm(a) for a in r[alias_key]}
            names={n for n in names if n}
            nodes.append({"chapter":ch_idx+1,"local_id":r["id"],"names":names,"raw":r})

    # 并查集: 名字有交集则合并
    parent=list(range(len(nodes)))
    def find(x):
        while parent[x]!=x: parent[x]=parent[parent[x]]; x=parent[x]
        return x
    def union(a,b): parent[find(a)]=find(b)

    ambiguities=[]
    for i in range(len(nodes)):
        for j in range(i+1,len(nodes)):
            inter=nodes[i]["names"] & nodes[j]["names"]
            if inter:
                # 判断置信: 是否有"主名"级别的交集(任一方的第一个名/最长名相同)
                exact = nodes[i]["raw"].get(name_key)==nodes[j]["raw"].get(name_key)
                union(i,j)
                if not exact:
                    ambiguities.append({
                        "reason":"仅通过别名/部分名称重叠归并,建议人工确认",
                        "chapterA":nodes[i]["chapter"],"nameA":nodes[i]["raw"].get(name_key),
                        "chapterB":nodes[j]["chapter"],"nameB":nodes[j]["raw"].get(name_key),
                        "overlap":list(inter)})

    groups=defaultdict(list)
    for i,n in enumerate(nodes): groups[find(i)].append(n)
    global_list=[]
    for gi,(root,members) in enumerate(groups.items(),1):
        allnames=set(); 
        for m in members: allnames|=m["names"]
        # canonical: 出现最多/最长的本名
        canon=sorted((m["raw"].get(name_key) for m in members), key=lambda s:-len(s or ""))[0]
        global_list.append({
            "global_id":gi,"canonical":canon,
            "all_names":sorted(allnames),
            "members":[{"chapter":m["chapter"],"local_id":m["local_id"]} for m in members]})
    return global_list, ambiguities

def stitch_timelines(chapters, char_global):
    """按全局人物分线,跨章缝合事件(故事顺序),并找同步点。"""
    # 局部人物id -> 全局id 映射
    loc2glob={}
    for g in char_global:
        for m in g["members"]:
            loc2glob[(m["chapter"],m["local_id"])]=g["global_id"]

    # 收集全局事件: (chapter, event) 展开,participants 映射到全局人物
    global_events=[]
    eid=0
    for ch_idx,ch in enumerate(chapters):
        for e in ch.get("events",[]):
            eid+=1
            gparts=[loc2glob.get((ch_idx+1,p)) for p in e.get("participants",[])]
            gparts=[p for p in gparts if p]
            global_events.append({
                "event_id":eid,"chapter":ch_idx+1,"desc":e["desc"],
                "narrative_order":e.get("narrative_order"),"story_order":e.get("story_order"),
                "is_flashback":e.get("is_flashback",False),
                "global_participants":gparts,"abs_interval":e.get("abs_interval"),
                "storyline":e.get("storyline","")})

    # 每个全局人物的时间线: 跨章, 先按章节, 章内按 story_order
    per_char=defaultdict(list)
    for ev in global_events:
        for gp in ev["global_participants"]:
            per_char[gp].append(ev)
    timelines={}
    for gp,evs in per_char.items():
        evs_sorted=sorted(evs,key=lambda x:(x["chapter"],x["story_order"] or 0))
        timelines[gp]=[{"seq":i+1,"event_id":e["event_id"],"chapter":e["chapter"],
                        "desc":e["desc"],"is_flashback":e["is_flashback"]}
                       for i,e in enumerate(evs_sorted)]

    # 同步点: 被>=2个全局人物共享的事件
    sync=[{"event_id":ev["event_id"],"desc":ev["desc"],
           "global_participants":ev["global_participants"],"chapter":ev["chapter"]}
          for ev in global_events if len(ev["global_participants"])>=2]

    return global_events, timelines, sync

def run(chapters):
    char_global, char_amb = resolve_global_entities(chapters,"characters","name","aliases")
    item_global, item_amb = resolve_global_entities(chapters,"items","name","mentions")
    loc_global,  loc_amb  = resolve_global_entities(chapters,"locations","name","mentions")
    global_events, timelines, sync = stitch_timelines(chapters, char_global)
    return {
        "global_characters":char_global,"global_items":item_global,"global_locations":loc_global,
        "global_events":global_events,"character_timelines":timelines,"sync_points":sync,
        "ambiguities":{"characters":char_amb,"items":item_amb,"locations":loc_amb}}
