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
            # 参与者 = participants ∪ {agent}(C 兜底:模型偶尔只填 agent 漏填 participants)
            raw_parts=list(e.get("participants",[]))
            ag=e.get("agent")
            if ag is not None and ag not in raw_parts: raw_parts.append(ag)
            gparts=[loc2glob.get((ch_idx+1,p)) for p in raw_parts]
            # 去重保序 + 去空
            seen=set(); gp_clean=[]
            for p in gparts:
                if p and p not in seen: seen.add(p); gp_clean.append(p)
            global_events.append({
                "event_id":eid,"chapter":ch_idx+1,"desc":e["desc"],
                "narrative_order":e.get("narrative_order"),"story_order":e.get("story_order"),
                "is_flashback":e.get("is_flashback",False),
                "global_participants":gp_clean,"abs_interval":e.get("abs_interval"),
                "storyline":e.get("storyline","")})

    # ---- 全局事件总序(人物线 = 总序的子集投影,共享事件 seq 一致自动满足)----
    # 设计(见 research/timeline_sync/DESIGN.md):
    #   基准键 (chapter, story_order):无共享参与者且跨章不可比时,按章节兜底,同章保留 story_order。
    #   闪回归位:闪回事件若有"锚"(与某更早主线事件共享参与者)→ 紧跟锚事件;
    #            无锚的孤立闪回 → 退回基准键(不硬猜,符合纪律)。
    #   冲突时锚优先于 story_order(本轮决策:同步点为准)。

    by_id={ev["event_id"]:ev for ev in global_events}
    def base_key(ev):  # 基准:章节先后兜底,同章按 story_order
        return (ev["chapter"], ev["story_order"] if ev["story_order"] is not None else 0)

    # 主线 = 非闪回事件,按基准键定序;闪回事件先单独拎出
    mainline=sorted([ev for ev in global_events if not ev["is_flashback"]], key=base_key)
    flashbacks=[ev for ev in global_events if ev["is_flashback"]]

    # 给主线事件分配整数序位(留间隙,供闪回插入)
    pos={}  # event_id -> float 序位
    for i,ev in enumerate(mainline): pos[ev["event_id"]]=float(i)*1000.0

    # 闪回归位:找"锚" = 与该闪回共享参与者、且 base_key 更早的主线事件中最晚的一个
    #   紧跟其后插入(锚位 + 小增量);story_order 决定多个挂同一锚的闪回之间的相对序。
    for fb in sorted(flashbacks, key=base_key):
        fb_parts=set(fb["global_participants"])
        anchor=None
        for ev in mainline:
            if ev["event_id"] not in pos: continue
            if fb_parts & set(ev["global_participants"]) and base_key(ev)<=base_key(fb):
                anchor=ev  # 取满足条件里最晚的(mainline 已升序,持续覆盖)
        if anchor is not None:
            # 锚后插入,以 story_order 排同锚多闪回
            so=fb["story_order"] if fb["story_order"] is not None else 0
            pos[fb["event_id"]]=pos[anchor["event_id"]]+1.0+so*0.001
        else:
            # 无锚孤立闪回:退回基准键(转成可比序位,排在对应章节主线附近)
            ck,so=base_key(fb)
            # 找基准键 <= fb 的最后一个主线事件,排其后;都没有则排最前
            prev=[ev for ev in mainline if base_key(ev)<=base_key(fb) and ev["event_id"] in pos]
            pos[fb["event_id"]]=(pos[prev[-1]["event_id"]]+0.5) if prev else -1.0

    # 全局总序:按序位排序(并列时 event_id 稳定兜底)
    total_order=sorted(global_events, key=lambda ev:(pos[ev["event_id"]], ev["event_id"]))
    for rank,ev in enumerate(total_order,1): ev["global_seq"]=rank

    # 人物线 = 总序的子集投影(seq 取全局秩在该人物事件内的相对名次)
    per_char=defaultdict(list)
    for ev in total_order:  # 已按总序
        for gp in ev["global_participants"]:
            per_char[gp].append(ev)
    timelines={}
    glob_seq={}  # (global_id, event_id) -> 个人线内 seq,供 sync positions 回填
    for gp,evs in per_char.items():
        timelines[gp]=[]
        for i,e in enumerate(evs,1):  # evs 已是总序子集,天然有序
            timelines[gp].append({"seq":i,"event_id":e["event_id"],"chapter":e["chapter"],
                                  "global_seq":e["global_seq"],
                                  "desc":e["desc"],"is_flashback":e["is_flashback"]})
            glob_seq[(gp,e["event_id"])]=i

    # 同步点: 被>=2个全局人物共享的事件 + 回填 positions(各参与者个人线内 seq)
    sync=[]
    for ev in total_order:
        if len(ev["global_participants"])>=2:
            sync.append({"event_id":ev["event_id"],"desc":ev["desc"],
                         "global_participants":ev["global_participants"],
                         "chapter":ev["chapter"],"global_seq":ev["global_seq"],
                         "positions":{gp:glob_seq.get((gp,ev["event_id"]))
                                      for gp in ev["global_participants"]}})

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
