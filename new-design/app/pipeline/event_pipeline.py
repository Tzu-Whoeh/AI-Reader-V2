#!/usr/bin/env python3
"""
两层事件抽取管道
  父事件(章节级): 看全章抽骨架事件, participants 准, 带 scene_ref + anchor_text + story_order
  子事件(场景级): 逐场景补细节动作, 挂父, 从候选清单选 participants/items
两道确定性校验:
  (a) 施事者从父继承: 子事件 participants 空 -> 继承父事件 agent/participants
  (b) 物品锚点校验: 子事件 items 必须出现在其 anchor_text 句内, 否则剔除

call_model() 默认直连 Ollama; 经平台调用时替换该函数。
依赖: 同目录提示词文件 06_event_pass1_parent.txt / 06_event_pass2_sub.txt
"""
import json, urllib.request

MODEL = "huihui_ai/Qwen3.6-abliterated:35b"

def call_model(prompt, temperature=0.12, num_ctx=8192, timeout=300):
    body={"model":MODEL,"prompt":prompt,"stream":False,"think":False,"format":"json",
          "options":{"temperature":temperature,"num_ctx":num_ctx}}
    req=urllib.request.Request("http://127.0.0.1:11434/api/generate",
        data=json.dumps(body,ensure_ascii=False).encode(),
        headers={"Content-Type":"application/json"},method="POST")
    with urllib.request.urlopen(req,timeout=timeout) as r:
        return json.loads(json.loads(r.read())["response"])

import os as _os
PROMPTS_DIR=_os.path.dirname(_os.path.abspath(__file__))  # 默认提示词在本模块同目录
def set_prompts_dir(d): 
    global PROMPTS_DIR; PROMPTS_DIR=d
def _load(fn):
    # fn 可为裸文件名(在 PROMPTS_DIR 找)或绝对/相对路径(直接用)
    path=fn if _os.path.isabs(fn) or _os.path.exists(fn) else _os.path.join(PROMPTS_DIR,fn)
    return open(path,encoding="utf-8").read()

def _scene_segment(fulltext, scene):
    """用场景起止锚点切出该场景原文片段。
    锚点可能缺失(退化单场景/模型漏给)——缺失时退回整段,绝不让单场景崩掉整章。"""
    start_anchor=(scene.get("start_text") or "")[:20]
    end_anchor=(scene.get("end_text") or "")[:20]
    st=fulltext.find(start_anchor) if start_anchor else -1
    en=fulltext.find(end_anchor) if end_anchor else -1
    if st<0: st=0
    en=len(fulltext) if en<0 else en+len(end_anchor)
    return fulltext[st:en]

def extract_parent_events(fulltext, scenes, characters,
                          prompt_file="06_event_pass1_parent.txt"):
    """章节级父事件: 看全章, participants 从人物候选选。"""
    scene_list="\n".join(f'  {s["index"]}: {s.get("title","")}' for s in scenes)
    char_cand="\n".join(f'  {c["id"]}: {c["name"]}' for c in characters)
    p=(_load(prompt_file).replace("{SCENE_LIST}",scene_list)
        .replace("{CHAR_CAND}",char_cand).replace("{TEXT}",fulltext))
    return call_model(p).get("events",[])

def extract_sub_events(fulltext, scenes, parents, characters, items,
                       prompt_file="06_event_pass2_sub.txt"):
    """逐场景子事件 + 两道校验。返回 {scene_index: [sub_event,...]}。"""
    char_cand="\n".join(f'  {c["id"]}: {c["name"]}' for c in characters)
    item_cand="\n".join(f'  {it["id"]}: {it["name"]}' for it in items)
    cids={c["id"] for c in characters}
    item_by_id={it["id"]:it for it in items}
    tpl=_load(prompt_file)
    parents_by_pid={i:e for i,e in enumerate(parents)}

    subs={}
    for s in scenes:
        seg=_scene_segment(fulltext, s)
        p_here=[(i,e) for i,e in enumerate(parents) if e.get("scene_ref")==s["index"]]
        plist="\n".join(f'  pid={i}: {e["desc"]}' for i,e in p_here) or "  (无父事件,parent填null)"
        prompt=(tpl.replace("{PARENT_LIST}",plist).replace("{CHAR_CAND}",char_cand)
                   .replace("{ITEM_CAND}",item_cand).replace("{SCENE_TEXT}",seg))
        try:
            evs=call_model(prompt).get("sub_events",[])
        except Exception:
            evs=[]
        # 两道校验
        for se in evs:
            # (a) 施事者从父继承
            if not se.get("participants"):
                par=se.get("parent")
                if isinstance(par,int) and par in parents_by_pid:
                    pe=parents_by_pid[par]
                    ag=pe.get("agent")
                    inherit=[ag] if ag in cids else (pe.get("participants",[])[:1])
                    if inherit:
                        se["participants"]=inherit; se["_agent_inherited"]=True
            # 过滤越界 participants
            se["participants"]=[p for p in se.get("participants",[]) if p in cids]
            # (b) 物品锚点校验: items 必须出现在 anchor_text 句内
            # (c) 场景一致性: 物品所属 scene 与子事件 scene 不符 → 疑似 id 复用(同名不同个体)
            #     标记到 se["_item_warnings"],并从 items 剔除明显错配的(物品scene与本场景完全无交集)
            anc=se.get("anchor_text","")
            cur_scene=s["index"]
            kept=[]; warnings=[]
            cand=se.get("items",[]) if anc else [i for i in se.get("items",[]) if i in item_by_id]
            for iid in cand:
                if iid not in item_by_id: continue
                it=item_by_id[iid]
                names=[it["name"]]+it.get("mentions",[])
                # 锚点:物品名须在 anchor_text 里(无anchor则跳过此项)
                if anc and not any(n and n in anc for n in names):
                    continue
                # 场景一致性:物品 scene 与当前子事件场景比对
                isc=it.get("scene")
                isc_set=set(isc) if isinstance(isc,list) else ({isc} if isc is not None else set())
                if isc_set and cur_scene not in isc_set:
                    # 物品属于别的场景却被本场景子事件引用 → 大概率 id 复用(同名不同个体)
                    warnings.append({"item_id":iid,"name":it["name"],
                                     "item_scene":isc,"event_scene":cur_scene,
                                     "reason":"物品所属场景与事件场景不符,疑似同名不同个体的id复用"})
                    continue  # 剔除错配引用
                kept.append(iid)
            se["items"]=kept
            if warnings: se["_item_warnings"]=warnings
        subs[s["index"]]=evs
    return subs

def resolve_event_locations(parents, scenes):
    """事件 scene_ref -> 场景 location_ref -> 事件 location_ref(确定性)。"""
    scene_loc={}
    for s in scenes:
        ref=s.get("location_ref")
        if s.get("index") is not None and ref:
            scene_loc[s["index"]]=ref["location_id"]
    for e in parents:
        lid=scene_loc.get(e.get("scene_ref"))
        e["location_ref"]={"location_id":lid} if lid is not None else None
    return parents

def extract_time_refs(fulltext, scenes, parents, prompt_file="08_time_ref.txt"):
    """跨章同时性(两段式):
    pass1(06)已标出 is_concurrency_marker=true 的事件(疑似平行同时引入句);
    本函数对每个 marker 调 08 复核——确认是真"双方此刻并行"才抽 names/places/local_scene_ref,
    否则(得知/回忆过去)返回空,由 pass2 纠正 pass1 的宽触发。无 marker 则完全不跑。"""
    markers=[e for e in parents if e.get("is_concurrency_marker")]
    if not markers: return []
    scene_list="\n".join(f'  {s["index"]}: {s.get("title","")}' for s in scenes)
    tpl=_load(prompt_file)
    out=[]
    for mk in markers:
        anchor=mk.get("anchor_text","")
        p=(tpl.replace("{SCENE_LIST}",scene_list)
              .replace("{MARKER}",anchor).replace("{TEXT}",fulltext))
        try:
            trs=call_model(p).get("time_refs",[])
        except Exception:
            trs=[]
        for tr in trs:
            tr.setdefault("local_scene_ref", mk.get("scene_ref"))
            out.append(tr)
    return out

def analyze_events(fulltext, scenes, characters, items):
    """完整两层事件抽取 + 校验 + 位置推导 + 跨章同时性(marker 触发的 time_ref)。"""
    parents=extract_parent_events(fulltext, scenes, characters)
    subs=extract_sub_events(fulltext, scenes, parents, characters, items)
    resolve_event_locations(parents, scenes)
    time_refs=extract_time_refs(fulltext, scenes, parents)
    return {"parent_events":parents, "sub_events":subs, "time_refs":time_refs}