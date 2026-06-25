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

    # 倒排索引替代 O(n^2) 两两比较:name -> 拥有该 name 的节点下标。
    # 只有"共享至少一个名字"的节点对才可能 union,这些对恰好由倒排桶精确枚举,
    # 不多不少 —— 输出与两两比较完全等价(union 结果只取决于"哪些对共享名字")。
    # 复杂度从 O(n^2) 降到 O(n + Σ 桶内对数);现实语料里绝大多数名字桶很小。
    name2nodes=defaultdict(list)
    for idx,nd in enumerate(nodes):
        for nm in nd["names"]:
            name2nodes[nm].append(idx)

    # 收集所有"共享名字"的无序节点对(去重),并记录它们共享的名字集合。
    # 用 dict 累积同一对在多个名字桶里出现的交集,行为对齐原始 inter=names&names。
    pair_overlap={}
    for nm, idxs in name2nodes.items():
        if len(idxs)<2: continue
        for a in range(len(idxs)):
            for b in range(a+1,len(idxs)):
                i,j=idxs[a],idxs[b]
                if i>j: i,j=j,i
                pair_overlap.setdefault((i,j),set()).add(nm)

    ambiguities=[]
    # 按 (i,j) 升序遍历,精确复现原 for i: for j>i 的处理与 ambiguity 记录顺序。
    # overlap 直接用两节点 name 集合的交集(与原实现逐字一致,而非累加器),
    # 保证 overlap 列表内部顺序也与原输出 byte 级相同。
    for (i,j) in sorted(pair_overlap.keys()):
        inter=nodes[i]["names"] & nodes[j]["names"]
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

# ============================================================================
# 场景级时间轴(重构):时间轴主干 = 场景;事件作为场景下挂的一组。
#   理由(见 research/timeline_sync):场景拆分是成熟稳定的骨架;同时性/闪回天然是
#   场景级的;事件 story_order 屡屡标错,不宜承担跨章主干排序。
#   事件仍保留,挂在所属场景下,其 story_order 只在场景内有意义。
# ============================================================================

def _scene_flashback(scene, evs):
    """场景是否闪回:优先看场景 type(往事/回忆/闪回);否则看挂的事件多数 is_flashback。"""
    t=(scene.get("type") or "")+(scene.get("title") or "")
    if any(k in t for k in ("往事","回忆","闪回","倒叙","回放")): return True
    if evs:
        fb=sum(1 for e in evs if e.get("is_flashback"))
        return fb*2>len(evs)  # 多数事件闪回 → 场景闪回
    return False

def stitch_timelines(chapters, char_global, loc_global=None):
    """场景级缝合:跨章场景排成全局时间轴,事件挂在场景下,人物线=人物出现的场景序投影。
    loc_global: 全局地点(供 time_ref.places 跨章匹配 + 场景地点归一)。"""
    loc_global=loc_global or []
    cloc2glob={}  # (章,章内人物id)->全局人物id
    for g in char_global:
        for m in g["members"]: cloc2glob[(m["chapter"],m["local_id"])]=g["global_id"]
    lloc2glob={}  # (章,章内地点id)->全局地点id
    for g in loc_global:
        for m in g["members"]: lloc2glob[(m["chapter"],m["local_id"])]=g["global_id"]
    gid_names={g["global_id"]:set(g["all_names"]) for g in char_global}
    locname_by_global={g["global_id"]:g["canonical"] for g in loc_global}

    # ---- 1. 收集全局场景 + 把事件挂到场景下 ----
    global_scenes=[]; sid=0
    for ch_idx,ch in enumerate(chapters):
        ch_no=ch_idx+1
        scenes=ch.get("scenes",[])
        # 该章事件按 scene_ref 分组
        ev_by_scene=defaultdict(list)
        for e in ch.get("events",[]):
            ev_by_scene[e.get("scene_ref")].append(e)
        for s in scenes:
            sid+=1
            s_idx=s.get("index")
            evs=ev_by_scene.get(s_idx,[])
            # 场景参与人物 = 场景内所有事件 participants∪agent 的全局并集
            gp=set()
            for e in evs:
                rp=list(e.get("participants",[])); ag=e.get("agent")
                if ag is not None and ag not in rp: rp.append(ag)
                for p in rp:
                    g=cloc2glob.get((ch_no,p))
                    if g: gp.add(g)
            # 场景地点(全局):优先场景 location_ref,否则由事件 location_ref 推
            gloc=None
            lr=s.get("location_ref")
            if lr and lr.get("location_id") is not None:
                gloc=lloc2glob.get((ch_no,lr["location_id"]))
            if gloc is None:
                for e in evs:
                    elr=e.get("location_ref")
                    if elr and elr.get("location_id") is not None:
                        gloc=lloc2glob.get((ch_no,elr["location_id"])); 
                        if gloc: break
            # 事件挂场景下(保留 story_order 供场景内排序)
            hung=[]
            for e in evs:
                rp=list(e.get("participants",[])); ag=e.get("agent")
                if ag is not None and ag not in rp: rp.append(ag)
                ep=[]
                seen=set()
                for p in rp:
                    g=cloc2glob.get((ch_no,p))
                    if g and g not in seen: seen.add(g); ep.append(g)
                hung.append({"desc":e.get("desc"),"story_order":e.get("story_order"),
                             "is_flashback":e.get("is_flashback",False),
                             "abs_interval":e.get("abs_interval"),
                             "global_participants":ep,"anchor_text":e.get("anchor_text","")})
            # 场景内事件按 story_order 排
            hung.sort(key=lambda x:(x["story_order"] if x["story_order"] is not None else 0))
            global_scenes.append({
                "scene_uid":sid,"chapter":ch_no,"scene_index":s_idx,
                "title":s.get("title",""),"type":s.get("type",""),
                "location_global":gloc,"location_name":locname_by_global.get(gloc),
                "global_participants":sorted(gp),
                "is_flashback":_scene_flashback(s,evs),
                "events":hung})

    # ---- 2. 场景级全局总序 ----
    # 基准键(章,场景index):章内按场景顺序,跨章按章顺序。闪回场景靠锚归位。
    def base_key(sc): return (sc["chapter"], sc["scene_index"] if sc["scene_index"] is not None else 0)
    mainline=sorted([s for s in global_scenes if not s["is_flashback"]], key=base_key)
    flash=[s for s in global_scenes if s["is_flashback"]]
    pos={}
    for i,s in enumerate(mainline): pos[s["scene_uid"]]=float(i)*1000.0
    # 闪回场景:与更早主线场景共享人物→锚其后;否则退基准键
    for fb in sorted(flash if False else flash, key=base_key):
        fbp=set(fb["global_participants"]); anchor=None
        for s in mainline:
            if s["scene_uid"] not in pos: continue
            if fbp & set(s["global_participants"]) and base_key(s)<=base_key(fb): anchor=s
        if anchor is not None:
            pos[fb["scene_uid"]]=pos[anchor["scene_uid"]]+1.0
        else:
            prev=[s for s in mainline if base_key(s)<=base_key(fb) and s["scene_uid"] in pos]
            pos[fb["scene_uid"]]=(pos[prev[-1]["scene_uid"]]+0.5) if prev else -1.0

    # ---- 3. 跨章同时性锚(time_ref):场景级 ----
    # B 章 time_ref 复述另一时刻 → 用 names(为主)+places(加分) 匹配【其他章场景】;
    #   命中唯一最高分场景 → 把本章对应场景(local_anchor 所属场景)锚到该场景旁。
    #   并列且构成"同地点同人物簇"→ 锚簇内最后(scene_index 最大);否则报歧义。
    def scene_names(sc):
        s=set()
        for g in sc["global_participants"]: s|=gid_names.get(g,set())
        return s
    def find_local_scene(ch_no, tr):
        # 优先用 time_ref.local_scene_ref(模型在源头标的本章同时场景编号)
        ref=tr.get("local_scene_ref")
        if ref is not None:
            for s in global_scenes:
                if s["chapter"]==ch_no and s["scene_index"]==ref: return s
        # 回退:local_anchor 文本匹配场景内事件/标题
        la=tr.get("local_anchor")
        if la:
            for s in [s for s in global_scenes if s["chapter"]==ch_no]:
                for e in s["events"]:
                    at=e.get("anchor_text") or ""; d=e.get("desc") or ""
                    if la in at or at in la or la in d or d in la: return s
                if la in (s.get("title") or ""): return s
        return None
    conc_amb=[]; conc_links=[]
    for ch_idx,ch in enumerate(chapters):
        ch_no=ch_idx+1
        for tr in ch.get("time_refs",[]):
            names=set(n for n in tr.get("names",[]) if n)
            places=set(p for p in tr.get("places",[]) if p)
            if not names and not places: continue
            local_sc=find_local_scene(ch_no, tr)
            scored=[]
            for s in global_scenes:
                if s["chapter"]==ch_no: continue
                nh=len(names & scene_names(s))
                ph=1 if (places and s.get("location_name") and
                         any(p in s["location_name"] or s["location_name"] in p for p in places)) else 0
                if nh>0: scored.append((nh+ph,nh,ph,s))
            if not scored:
                conc_amb.append({"type":"time_ref_no_match","chapter":ch_no,
                    "anchor":tr.get("anchor"),"names":sorted(names),"places":sorted(places),
                    "note":"其他章未找到名字交集的场景,无法跨章锚定"}); continue
            scored.sort(key=lambda x:(-x[0],-x[1],x[3]["scene_uid"]))
            top=scored[0][0]; tied=[s[3] for s in scored if s[0]==top]
            if len(tied)>1:
                same_chap=len(set(t["chapter"] for t in tied))==1
                locs=set(t.get("location_name") for t in tied)
                place_shared=len(locs)==1 and None not in locs
                name_sets=[scene_names(t) for t in tied]
                char_shared=bool(set.intersection(*name_sets)) if all(name_sets) else False
                if same_chap and place_shared and char_shared:
                    matched=sorted(tied,key=lambda t:(t["scene_index"] or -1,t["scene_uid"]))[-1]
                else:
                    conc_amb.append({"type":"time_ref_ambiguous","chapter":ch_no,
                        "anchor":tr.get("anchor"),"names":sorted(names),
                        "candidates":[t["title"] for t in tied],
                        "note":"多个跨章场景并列且不构成同地点同人物簇,无法确定指向"}); continue
            else:
                matched=tied[0]
            conc_links.append({"local_anchor":tr.get("local_anchor"),
                "local_scene":(local_sc["title"] if local_sc else None),
                "matched_scene":matched["title"],"matched_chapter":matched["chapter"],
                "names":sorted(names),"places":sorted(places),"cluster_size":len(tied)})
            if local_sc is not None and not (set(local_sc["global_participants"]) & set(matched["global_participants"])):
                pos[local_sc["scene_uid"]]=pos[matched["scene_uid"]]+0.0001

    # ---- 4. 场景全局序 + 人物线(场景序子集投影) ----
    total=sorted(global_scenes, key=lambda s:(pos[s["scene_uid"]], s["scene_uid"]))
    for rank,s in enumerate(total,1): s["global_seq"]=rank
    per_char=defaultdict(list)
    for s in total:
        for g in s["global_participants"]: per_char[g].append(s)
    timelines={}; gseq_in_line={}
    for g,scs in per_char.items():
        timelines[g]=[]
        for i,s in enumerate(scs,1):
            timelines[g].append({"seq":i,"scene_uid":s["scene_uid"],"chapter":s["chapter"],
                                 "global_seq":s["global_seq"],"title":s["title"],
                                 "is_flashback":s["is_flashback"]})
            gseq_in_line[(g,s["scene_uid"])]=i
    # 同步点:被>=2全局人物共享的场景
    sync=[]
    for s in total:
        if len(s["global_participants"])>=2:
            sync.append({"scene_uid":s["scene_uid"],"title":s["title"],
                         "global_participants":s["global_participants"],
                         "chapter":s["chapter"],"global_seq":s["global_seq"],
                         "positions":{g:gseq_in_line.get((g,s["scene_uid"])) for g in s["global_participants"]}})
    return total, timelines, sync, conc_amb, conc_links

# abs_interval 方向词表(场景级:看场景首事件 abs 与场景顺序)
_ABS_PAST=("昨晚","昨日","昨天","前天","之前","以前","早前","早年","当年","过去",
           "月前","年前","天前","周前","星期前","小时前","分钟前","前夕")
_ABS_FUTURE=("之后","此后","后来","次日","翌日","隔日","将要","即将","稍后","随后")
def _abs_direction(s):
    s=s or ""
    if any(w in s for w in _ABS_PAST): return "past"
    if any(w in s for w in _ABS_FUTURE): return "future"
    return None

def check_abs_consistency(global_scenes, timelines):
    """场景级 abs 校验:同一人物线上,若某场景首事件 abs 方向与场景顺序矛盾,报歧义。"""
    by_uid={s["scene_uid"]:s for s in global_scenes}
    def scene_abs(s):  # 取场景第一个事件的 abs_interval 作场景级时间锚
        return s["events"][0]["abs_interval"] if s.get("events") else None
    amb=[]; seen=set()
    for g,tl in timelines.items():
        for i in range(1,len(tl)):
            cur=by_uid.get(tl[i]["scene_uid"]); prev=by_uid.get(tl[i-1]["scene_uid"])
            if not cur or not prev: continue
            if _abs_direction(scene_abs(cur))=="past":
                key=(cur["scene_uid"],prev["scene_uid"])
                if key in seen: continue
                seen.add(key)
                amb.append({"type":"abs_vs_scene_order",
                    "scene_uid":cur["scene_uid"],"scene_title":cur["title"],
                    "abs_interval":scene_abs(cur),
                    "prev_scene_uid":prev["scene_uid"],"prev_title":prev["title"],
                    "note":"场景 abs_interval 指向更早,但场景顺序将其排在 prev 之后,请人工确认"})
    return amb

def project_global_events(global_scenes):
    """把挂在场景下的事件投影成全局事件线(确定性,不新增语义)。
    全局序 = 场景在 global_scenes 的既有时间轴顺序;场景内按 events 既有顺序(已按 story_order 排)。
    供 /api/summary 计数、/api/events、build_graph 的事件节点使用。"""
    out=[]; seq=0
    for sc in global_scenes:
        for e in sc.get("events",[]):
            seq+=1
            out.append({
                "global_seq":seq,
                "scene_uid":sc["scene_uid"],
                "chapter":sc["chapter"],
                "location_global":sc.get("location_global"),
                "location_name":sc.get("location_name"),
                "is_flashback":e.get("is_flashback", sc.get("is_flashback",False)),
                "desc":e.get("desc"),
                "story_order":e.get("story_order"),
                "abs_interval":e.get("abs_interval"),
                "global_participants":e.get("global_participants",[]),
                "anchor_text":e.get("anchor_text",""),
            })
    return out

def run(chapters):
    char_global, char_amb = resolve_global_entities(chapters,"characters","name","aliases")
    item_global, item_amb = resolve_global_entities(chapters,"items","name","mentions")
    loc_global,  loc_amb  = resolve_global_entities(chapters,"locations","name","mentions")
    org_global,  org_amb  = resolve_global_entities(chapters,"organizations","name","aliases")
    global_scenes, timelines, sync, conc_amb, conc_links = stitch_timelines(chapters, char_global, loc_global)
    timeline_amb = check_abs_consistency(global_scenes, timelines) + conc_amb
    return {
        "global_characters":char_global,"global_items":item_global,"global_locations":loc_global,
        "global_organizations":org_global,
        "global_scenes":global_scenes,"global_events":project_global_events(global_scenes),
        "character_timelines":timelines,"sync_points":sync,
        "concurrency_links":conc_links,
        "ambiguities":{"characters":char_amb,"items":item_amb,"locations":loc_amb,
                       "organizations":org_amb,"timeline":timeline_amb}}