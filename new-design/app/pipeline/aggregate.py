"""全局分维度聚合:读所有章节 _merged,跨章归一,每维度输出一个全局文件。"""
import cross_chapter as cc
import entity_normalize as EN

def aggregate(store):
    chs=store.list_chapters()
    chapters=[]
    for ch in chs:
        m=store.load_chapter_merged(ch)
        chapters.append({
            "characters": m.get("characters",[]),
            "items": m.get("items",[]),
            "locations": m.get("locations",[]),
            "events": m.get("parent_events", m.get("events",[])),  # 新流程用 parent_events
            "scenes": m.get("scenes",[]),
            "_chapter": ch,
            "character_relations": m.get("character_relations",[]),
            "location_relations": m.get("location_relations",[]),
        })

    # 跨章核心(全局人物/物品/地点归一 + 事件/时间线/同步点)
    cross=cc.run(chapters)

    # ---- 全局人物文档: 归一表 + 个人时间线 + 跨章人物关系(把各章关系的局部id映射到全局id) ----
    loc2glob_char={}
    for g in cross["global_characters"]:
        for m in g["members"]: loc2glob_char[(m["chapter"],m["local_id"])]=g["global_id"]
    global_char_relations=[]
    for ci,ch in enumerate(chapters,0):
        chap_no=ch["_chapter"]
        for r in ch.get("character_relations",[]):
            f=loc2glob_char.get((chap_no,r.get("from_id"))); t=loc2glob_char.get((chap_no,r.get("to_id")))
            if f and t:
                nr=dict(r); nr["from_global"]=f; nr["to_global"]=t; nr["chapter"]=chap_no
                global_char_relations.append(nr)
    characters_doc={
        "global_characters":cross["global_characters"],
        "character_timelines":cross["character_timelines"],
        "relations":global_char_relations,
        "ambiguities":cross["ambiguities"]["characters"],
    }

    # ---- 全局物品文档(附各章实例的位置:物品→场景→地点) ----
    # 收集每章每物品的 location_refs,挂到全局物品的 members 上
    loc2glob_item={}
    for g in cross["global_items"]:
        for m in g["members"]: loc2glob_item[(m["chapter"],m["local_id"])]=g["global_id"]
    item_locations={}  # global_item_id -> [{chapter, location_id, location_name, via_scene}]
    # 需要章节地点名:用各章 _merged 的 locations
    for ci,ch in enumerate(chapters):
        chap_no=ch["_chapter"]
        locname={l["id"]:l["name"] for l in ch.get("locations",[])}
        # 重新从该章 merged 读 items(含 location_refs)
        m=store.load_chapter_merged(chap_no)
        ln={l["id"]:l["name"] for l in m.get("locations",[])}
        for it in m.get("items",[]):
            gid=loc2glob_item.get((chap_no,it["id"]))
            if gid is None: continue
            for ref in it.get("location_refs",[]):
                item_locations.setdefault(gid,[]).append({
                    "chapter":chap_no,"location_id":ref["location_id"],
                    "location_name":ln.get(ref["location_id"],""),"via_scene":ref["via_scene"]})
    items_doc={"global_items":cross["global_items"],
               "item_locations":item_locations,
               "ambiguities":cross["ambiguities"]["items"]}
    # ---- 全局地点文档 ----
    loc2glob_loc={}
    for g in cross["global_locations"]:
        for m in g["members"]: loc2glob_loc[(m["chapter"],m["local_id"])]=g["global_id"]
    global_loc_relations=[]
    for ch in chapters:
        chap_no=ch["_chapter"]
        for r in ch.get("location_relations",[]):
            f=loc2glob_loc.get((chap_no,r.get("from_id"))); t=loc2glob_loc.get((chap_no,r.get("to_id")))
            if f and t:
                nr=dict(r); nr["from_global"]=f; nr["to_global"]=t; nr["chapter"]=chap_no
                global_loc_relations.append(nr)
    locations_doc={"global_locations":cross["global_locations"],
                   "relations":global_loc_relations,
                   "ambiguities":cross["ambiguities"]["locations"]}
    # ---- 全局时间线文档 ----
    timeline_doc={"global_scenes":cross["global_scenes"],
                  "character_timelines":cross["character_timelines"],
                  "sync_points":cross["sync_points"],
                  "concurrency_links":cross.get("concurrency_links",[]),
                  "ambiguities":cross["ambiguities"].get("timeline",[])}
    # ---- 全局场景文档(各章场景顺序拼接) ----
    scenes_doc={"chapters":[{"chapter":ch["_chapter"],"scenes":ch["scenes"]} for ch in chapters]}

    # 存盘
    store.save_global("characters",characters_doc)
    store.save_global("items",items_doc)
    store.save_global("locations",locations_doc)
    store.save_global("timeline",timeline_doc)
    store.save_global("scenes",scenes_doc)

    index={
        "chapters":chs,
        "global_files":["characters.json","items.json","locations.json","timeline.json","scenes.json"],
        "counts":{
            "global_characters":len(cross["global_characters"]),
            "global_items":len(cross["global_items"]),
            "global_locations":len(cross["global_locations"]),
            "global_scenes":len(cross["global_scenes"]),
            "sync_points":len(cross["sync_points"]),
        },
        "ambiguities":{k:len(v) for k,v in cross["ambiguities"].items()},
    }
    store.save_index(index)
    return index
