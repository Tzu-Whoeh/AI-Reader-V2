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
    """用场景起止锚点切出该场景原文片段。"""
    st=fulltext.find(scene["start_text"][:20]); en=fulltext.find(scene["end_text"][:20])
    if st<0: st=0
    en=len(fulltext) if en<0 else en+len(scene["end_text"][:20])
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
            anc=se.get("anchor_text","")
            if anc:
                kept=[]
                for iid in se.get("items",[]):
                    if iid not in item_by_id: continue
                    names=[item_by_id[iid]["name"]]+item_by_id[iid].get("mentions",[])
                    if any(n and n in anc for n in names):
                        kept.append(iid)
                se["items"]=kept
            else:
                se["items"]=[i for i in se.get("items",[]) if i in item_by_id]
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

def analyze_events(fulltext, scenes, characters, items):
    """完整两层事件抽取 + 校验 + 位置推导。"""
    parents=extract_parent_events(fulltext, scenes, characters)
    subs=extract_sub_events(fulltext, scenes, parents, characters, items)
    resolve_event_locations(parents, scenes)
    return {"parent_events":parents, "sub_events":subs}
