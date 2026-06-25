#!/usr/bin/env python3
"""
叙事分析浏览器 · 后端服务
读取 output/ 目录(分析产物) + 原文,提供 API:
  GET /                      前端页面
  GET /api/summary           概览统计 + 章节列表
  GET /api/graph             全局关系图(节点+边)
  GET /api/dimension/<name>  某维度全局数据(characters/items/locations/timeline/scenes)
  GET /api/node/<type>/<id>  节点详情 + 所有原文出处(锚点在各章原文定位)

启动:
  python server.py --output output/ --raw raw_chapters/ [--port 8080]
  --raw 指向按章拆分后的原文目录(chNN.txt),或单一原文文件目录。
仅用标准库(http.server),零三方依赖。
"""
import os, json, re, argparse, mimetypes, posixpath, threading
from urllib.parse import urlparse, unquote

OUTPUT_DIR="output"
RAW={}          # chapter_index -> raw text
GLOBALS={}      # dimension -> json
CHAPTERS=[]     # merged per chapter
BASE_PATH=""    # 部署前缀,如 "/new";nginx 透传时由 --base-path 设定
STATIC_DIR=None # Vite 产物目录(pipeline/static);存在则优先托管,否则回退内嵌 FRONTEND

# 多小说库:每次只读请求按 novel(安全化目录名)把该小说数据装入模块全局。
# build_* 函数仍读模块全局(零改动、零回归);用锁串行化按 novel 加载。
LIB_ROOT=None       # 库根:含 output/ input/ 的 app 目录;None 表示单库(老行为)
_LIB_LOCK=threading.RLock()
_CUR_NOVEL=None

def _load_globals_chapters(output_dir):
    g={}; chs_list=[]
    gdir=os.path.join(output_dir,"global")
    for name in ("characters","items","locations","organizations","timeline","scenes"):
        p=os.path.join(gdir,f"{name}.json")
        if os.path.exists(p): g[name]=json.load(open(p,encoding="utf-8"))
    chs=sorted(d for d in os.listdir(output_dir) if d.startswith("ch") and d[2:].isdigit()) if os.path.isdir(output_dir) else []
    for d in chs:
        mp=os.path.join(output_dir,d,"_merged.json")
        if os.path.exists(mp):
            m=json.load(open(mp,encoding="utf-8")); m["_chapter"]=int(d[2:])
            chs_list.append(m)
    return g, chs_list

def _load_raw(raw_dir):
    raw={}
    if raw_dir and os.path.isdir(raw_dir):
        txts=sorted(f for f in os.listdir(raw_dir) if f.endswith(".txt"))
        for i,f in enumerate(txts,1):
            mobj=re.search(r'(\d+)', f)
            idx=int(mobj.group(1)) if mobj else i
            raw[idx]=open(os.path.join(raw_dir,f),encoding="utf-8",errors="replace").read()
    return raw

def load_data(output_dir, raw_dir):
    """单库加载(老行为):把 output_dir/raw_dir 装入模块全局。"""
    global OUTPUT_DIR, RAW, GLOBALS, CHAPTERS
    OUTPUT_DIR=output_dir
    g,chs=_load_globals_chapters(output_dir)
    GLOBALS.clear(); GLOBALS.update(g)
    CHAPTERS.clear(); CHAPTERS.extend(chs)
    RAW.clear(); RAW.update(_load_raw(raw_dir))

def set_library(lib_root):
    """启用多小说库模式:lib_root 下有 output/<novel>/ 与 input/<novel>/。"""
    global LIB_ROOT
    LIB_ROOT=lib_root

def list_novels():
    """列出库中所有小说:读 output/<novel>/meta.json。"""
    out=[]
    odir=os.path.join(LIB_ROOT,"output") if LIB_ROOT else None
    if not odir or not os.path.isdir(odir): return out
    for slug in sorted(os.listdir(odir)):
        nd=os.path.join(odir,slug)
        if not os.path.isdir(nd): continue
        meta_p=os.path.join(nd,"meta.json")
        meta=json.load(open(meta_p,encoding="utf-8")) if os.path.exists(meta_p) else {}
        # 章数 + 已分析章号区间:output/<slug>/chNN
        chnums=sorted(int(d[2:]) for d in os.listdir(nd) if d.startswith("ch") and d[2:].isdigit())
        chn=len(chnums)
        item={"slug":slug,"novel_name":meta.get("novel_name",slug),
                    "author":meta.get("author"),"chapter_count":chn,
                    "stage":meta.get("stage"),"uploaded_at":meta.get("uploaded_at")}
        if chnums:
            item["analyzed_min"]=chnums[0]; item["analyzed_max"]=chnums[-1]
            item["analyzed_count"]=chn
        out.append(item)
    return out

class use_novel:
    """上下文管理器:加锁,把指定 novel 的数据装入模块全局,退出后保持(下次切换再换)。
    单库模式(LIB_ROOT=None)或 slug 为空时为 no-op,沿用当前已加载数据。"""
    def __init__(self, slug):
        self.slug=slug
    def __enter__(self):
        _LIB_LOCK.acquire()
        global _CUR_NOVEL, OUTPUT_DIR, RAW, GLOBALS, CHAPTERS
        if LIB_ROOT and self.slug and self.slug!=_CUR_NOVEL:
            odir=os.path.join(LIB_ROOT,"output",self.slug)
            idir=os.path.join(LIB_ROOT,"input",self.slug)
            g,chs=_load_globals_chapters(odir)
            GLOBALS.clear(); GLOBALS.update(g)
            CHAPTERS.clear(); CHAPTERS.extend(chs)
            RAW.clear(); RAW.update(_load_raw(idir))
            OUTPUT_DIR=odir; _CUR_NOVEL=self.slug
        return self
    def __exit__(self, *a):
        _LIB_LOCK.release()
        return False

def _sentences_with(term, text):
    """在 text 中找含 term 的句子,返回 [{sentence, pos}]。"""
    if not term: return []
    out=[]; start=0
    while True:
        pos=text.find(term, start)
        if pos<0: break
        # 句子边界
        ls=max(text.rfind("。",0,pos), text.rfind("\n",0,pos),
               text.rfind("！",0,pos), text.rfind("？",0,pos))+1
        re_end=min([x for x in [text.find("。",pos),text.find("\n",pos),
                    text.find("！",pos),text.find("？",pos)] if x>=0]+[len(text)])
        sent=text[ls:re_end+1].strip()
        out.append({"sentence":sent,"pos":pos})
        start=pos+len(term)
        if len(out)>=20: break
    return out

# 太泛、易误命中的锚点(代词/单字),反查时过滤
STOP_ANCHORS={"他","她","它","我","你","您","他们","她们","老子","自己"}
def find_occurrences(anchors):
    """给定一组锚点词,在所有章原文里找出处。过滤泛指代词,只用有区分度的词。"""
    anchors=[a for a in anchors if a and len(a)>=2 and a not in STOP_ANCHORS]
    occ=[]
    for ch_idx, text in RAW.items():
        for term in anchors:
            for hit in _sentences_with(term, text):
                occ.append({"chapter":ch_idx,"term":term,"sentence":hit["sentence"],"pos":hit["pos"]})
    # 去重(同章同句)
    seen=set(); uniq=[]
    for o in occ:
        k=(o["chapter"],o["sentence"])
        if k in seen: continue
        seen.add(k); uniq.append(o)
    uniq.sort(key=lambda x:(x["chapter"],x["pos"]))
    return uniq

def node_anchors(ntype, nid):
    """取某节点的锚点词集合(用于原文定位)。"""
    if ntype=="character":
        for g in GLOBALS.get("characters",{}).get("global_characters",[]):
            if g["global_id"]==nid: return g.get("all_names",[g.get("canonical")])
    if ntype=="item":
        # 全局物品名 + 各章 mentions
        names=[]
        for g in GLOBALS.get("items",{}).get("global_items",[]):
            if g["global_id"]==nid: names=[g.get("canonical")]+g.get("all_names",[])
        for m in CHAPTERS:
            for it in m.get("items",[]):
                if it.get("name") in names: names+=it.get("mentions",[])
        return list(dict.fromkeys(names))
    if ntype=="location":
        for g in GLOBALS.get("locations",{}).get("global_locations",[]):
            if g["global_id"]==nid: return g.get("all_names",[g.get("canonical")])
    if ntype=="event":
        # 事件用 anchor_text
        for m in CHAPTERS:
            for e in m.get("parent_events",[]):
                if e.get("event_id")==nid or e.get("desc")==nid:
                    return [e.get("anchor_text","")] if e.get("anchor_text") else []
    return []

def _entity_alias_index():
    """构建 {别名: (type, global_id, canonical)} 倒排;长别名优先(避免短词截断长词)。
    过滤 STOP_ANCHORS 与单字噪音。"""
    out={}
    def add(names, typ, gid, canon):
        for nm in names:
            if not nm or len(nm)<2 or nm in STOP_ANCHORS: continue
            # 已存在更长别名映射时不覆盖(后续按长度排序匹配,这里仅登记)
            out.setdefault(nm, (typ, gid, canon))
    for g in GLOBALS.get("characters",{}).get("global_characters",[]):
        add(g.get("all_names",[g.get("canonical")]), "character", g["global_id"], g.get("canonical"))
    for g in GLOBALS.get("locations",{}).get("global_locations",[]):
        add(g.get("all_names",[g.get("canonical")]), "location", g["global_id"], g.get("canonical"))
    # 物品:canonical + all_names + 各章 mentions
    item_names={}
    for g in GLOBALS.get("items",{}).get("global_items",[]):
        nm=[g.get("canonical")]+g.get("all_names",[])
        item_names[g["global_id"]]=set(n for n in nm if n)
    for m in CHAPTERS:
        for it in m.get("items",[]):
            for gid,names in item_names.items():
                if it.get("name") in names:
                    names.update(it.get("mentions",[]))
    for gid,names in item_names.items():
        canon=next((g.get("canonical") for g in GLOBALS.get("items",{}).get("global_items",[]) if g["global_id"]==gid), None)
        add(list(names), "item", gid, canon)
    return out

def build_reader(chapter):
    """某章原文 + 高亮区间索引。
    返回 {chapter, text, highlights:[{start,end,type,global_id,label,term}]}。
    区间不重叠:长别名优先,已占用区间不再匹配(短别名让位)。"""
    text=RAW.get(chapter)
    if text is None:
        return {"chapter":chapter,"text":None,"highlights":[],"error":"该章原文不可用(server 未加载 --raw 或无此章)"}
    alias=_entity_alias_index()
    # 别名按长度降序,长的先占位
    terms=sorted(alias.keys(), key=len, reverse=True)
    occupied=[False]*len(text)
    spans=[]
    for term in terms:
        typ,gid,canon=alias[term]
        start=0
        L=len(term)
        while True:
            pos=text.find(term, start)
            if pos<0: break
            if not any(occupied[pos:pos+L]):
                for i in range(pos,pos+L): occupied[i]=True
                spans.append({"start":pos,"end":pos+L,"type":typ,
                              "global_id":gid,"label":canon or term,"term":term})
            start=pos+L
    spans.sort(key=lambda s:s["start"])
    return {"chapter":chapter,"text":text,"highlights":spans}

def _local2global(global_entities):
    """{(chapter, local_id): global_id},用于把章级局部引用解析到全局 id。"""
    m={}
    for g in global_entities:
        for mem in g.get("members",[]):
            m[(mem.get("chapter"), mem.get("local_id"))]=g["global_id"]
    return m

def build_graph():
    """汇总全局节点 + 边(供前端总览图)。
    遵循 model/API.md 契约:实体节点(人/物/地)+ 事件节点;
    边 kind: char/loc(关系)、item(物品边)、event(事件参与)。
    注:global_id 可为 0,判空一律用 is not None(修旧版 falsy 漏边 bug)。"""
    nodes=[]; edges=[]
    gchars=GLOBALS.get("characters",{}).get("global_characters",[])
    gitems=GLOBALS.get("items",{}).get("global_items",[])
    glocs=GLOBALS.get("locations",{}).get("global_locations",[])
    gorgs=GLOBALS.get("organizations",{}).get("global_organizations",[])
    gevents=GLOBALS.get("timeline",{}).get("global_events",[])

    char_ids={g["global_id"] for g in gchars}
    item_ids={g["global_id"] for g in gitems}
    loc_ids={g["global_id"] for g in glocs}
    org_ids={g["global_id"] for g in gorgs}

    for g in gchars:
        nodes.append({"id":f"character:{g['global_id']}","label":g["canonical"],"type":"character"})
    for g in gitems:
        nodes.append({"id":f"item:{g['global_id']}","label":g["canonical"],"type":"item"})
    for g in glocs:
        nodes.append({"id":f"location:{g['global_id']}","label":g["canonical"],"type":"location"})
    for g in gorgs:
        nodes.append({"id":f"organization:{g['global_id']}","label":g["canonical"],"type":"organization"})
    for e in gevents:
        if e.get("event_id") is not None:
            lbl=(e.get("desc") or "")[:14]
            nodes.append({"id":f"event:{e['event_id']}","label":lbl,"type":"event"})

    # 人物关系边(is not None 判空)
    for r in GLOBALS.get("characters",{}).get("relations",[]):
        a,b=r.get("from_global"),r.get("to_global")
        if a is not None and b is not None and a in char_ids and b in char_ids:
            edges.append({"from":f"character:{a}","to":f"character:{b}",
                          "label":r.get("relation_type",""),"kind":"char",
                          "relation_type":r.get("relation_type","")})
    # 地点关系边
    for r in GLOBALS.get("locations",{}).get("relations",[]):
        a,b=r.get("from_global"),r.get("to_global")
        if a is not None and b is not None and a in loc_ids and b in loc_ids:
            edges.append({"from":f"location:{a}","to":f"location:{b}",
                          "label":r.get("relation_type",""),"kind":"loc",
                          "relation_type":r.get("relation_type","")})

    # 组织成员边 —— 人物→组织(明说归属,confidence=explicit)
    for m in GLOBALS.get("organizations",{}).get("memberships",[]):
        cg=m.get("character_global"); og=m.get("org_global")
        if cg is not None and og is not None and cg in char_ids and og in org_ids:
            edges.append({"from":f"character:{cg}","to":f"organization:{og}",
                          "label":m.get("role","") or "成员","kind":"membership"})
    # 组织间关系边
    for r in GLOBALS.get("organizations",{}).get("relations",[]):
        a,b=r.get("from_global"),r.get("to_global")
        if a is not None and b is not None and a in org_ids and b in org_ids:
            edges.append({"from":f"organization:{a}","to":f"organization:{b}",
                          "label":r.get("label",r.get("relation_type","")),"kind":"org",
                          "relation_type":r.get("relation_type","")})

    # 物品边 —— item→location(item_locations,局部 location_id 经 members 解析到全局)
    loc_l2g=_local2global(glocs)
    item_loc=GLOBALS.get("items",{}).get("item_locations",{})
    seen_il=set()
    for item_gid_str, recs in item_loc.items():
        try: item_gid=int(item_gid_str)
        except: continue
        if item_gid not in item_ids: continue
        for rec in recs:
            lg=loc_l2g.get((rec.get("chapter"), rec.get("location_id")))
            if lg is not None and (item_gid,lg) not in seen_il:
                seen_il.add((item_gid,lg))
                edges.append({"from":f"item:{item_gid}","to":f"location:{lg}","kind":"item"})

    # 物品边 —— owner_ref/part_of(章级,经 members 解析);set_group 同组互连
    item_l2g=_local2global(gitems)
    char_l2g=_local2global(gchars)
    seen_io=set(); set_groups={}
    for m in CHAPTERS:
        ch=m.get("_chapter")
        for it in m.get("items",[]):
            src_g=item_l2g.get((ch, it.get("id")))
            if src_g is None: continue
            # 物品归属人物(owner_ref 可为 int 或 {ref/owner_id})
            oref=it.get("owner_ref")
            oref_id=oref.get("ref") if isinstance(oref,dict) else oref
            if oref_id is not None:
                og=char_l2g.get((ch,oref_id))
                if og is not None and (src_g,og,"own") not in seen_io:
                    seen_io.add((src_g,og,"own"))
                    edges.append({"from":f"item:{src_g}","to":f"character:{og}","kind":"item","label":"owner"})
            # 部件归属物品(part_of 可为 int 或 {whole_id, relation, confidence})
            pof=it.get("part_of")
            pof_id=pof.get("whole_id") if isinstance(pof,dict) else pof
            if pof_id is not None:
                pg=item_l2g.get((ch,pof_id))
                if pg is not None and (src_g,pg,"part") not in seen_io:
                    seen_io.add((src_g,pg,"part"))
                    edges.append({"from":f"item:{src_g}","to":f"item:{pg}","kind":"item","label":"part_of"})
            # 套组聚合(同 set_group 互连;set_group 可为标量或带 id 的 dict)
            sg=it.get("set_group")
            if isinstance(sg,dict): sg=sg.get("group_id") or sg.get("id")
            if sg not in (None,"",0):
                set_groups.setdefault((ch,sg),[]).append(src_g)
    for members in set_groups.values():
        uniq=sorted(set(members))
        for i in range(len(uniq)):
            for j in range(i+1,len(uniq)):
                edges.append({"from":f"item:{uniq[i]}","to":f"item:{uniq[j]}","kind":"item","label":"set"})

    # 事件边 —— 事件→参与人物
    for e in gevents:
        eid=e.get("event_id")
        if eid is None: continue
        for p in e.get("global_participants",[]):
            if p in char_ids:
                edges.append({"from":f"event:{eid}","to":f"character:{p}","kind":"event"})

    return {"nodes":nodes,"edges":edges}

def build_events():
    """/api/events:事件时序视图(投影 timeline + 派生视图,不新增语义)。"""
    tl=GLOBALS.get("timeline",{})
    return {"events":tl.get("global_events",[]),
            "sync_points":tl.get("sync_points",[]),
            "character_timelines":tl.get("character_timelines",{})}

FRONTEND='<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">\n<meta name="viewport" content="width=device-width,initial-scale=1">\n<title>叙事档案 · 浏览器</title>\n<style>\n:root{--paper:#1a1714;--paper2:#221d18;--ink:#e8dcc8;--dim:#9a8f7d;--stamp:#a8332a;--thread:#b8884a;--line:#3a322a;--char:#a8332a;--item:#b8884a;--loc:#6f9b8e}\n*{box-sizing:border-box;margin:0;padding:0}\nbody{background:var(--paper);color:var(--ink);font-family:"Songti SC","Noto Serif SC",serif;height:100vh;overflow:hidden}\n.top{padding:14px 24px;border-bottom:2px solid var(--stamp);display:flex;align-items:baseline;gap:18px}\n.top h1{font-size:22px;letter-spacing:.1em}.top .sub{color:var(--dim);font-size:12px;font-family:sans-serif;letter-spacing:.2em}\n.top .stat{margin-left:auto;font-family:sans-serif;font-size:12px;color:var(--dim)}\n.main{display:flex;height:calc(100vh - 52px)}\n.graph-pane{flex:1;position:relative}\nsvg{width:100%;height:100%}\n.side{width:380px;border-left:1px solid var(--line);background:var(--paper2);overflow-y:auto;padding:18px}\n.filters{padding:10px 24px;display:flex;gap:14px;font-family:sans-serif;font-size:12px;border-bottom:1px solid var(--line)}\n.filters label{display:flex;align-items:center;gap:5px;cursor:pointer;color:var(--dim)}\n.filters i{width:11px;height:11px;border-radius:50%;display:inline-block}\n.node{cursor:pointer}.node circle{transition:r .15s}.node:hover circle{stroke:#fff;stroke-width:2}\n.node text{fill:var(--ink);font-size:12px;pointer-events:none}\n.side h2{font-size:18px;margin-bottom:4px}.side .meta{font-family:sans-serif;font-size:11px;color:var(--thread);letter-spacing:.1em;margin-bottom:14px}\n.occ{background:var(--paper);border-left:2px solid var(--thread);padding:8px 11px;margin-bottom:7px;font-size:13px;line-height:1.5}\n.occ .ch{font-family:sans-serif;font-size:10px;color:var(--thread);letter-spacing:.1em;display:block;margin-bottom:2px}\n.occ b{color:var(--stamp);font-weight:400;background:rgba(168,51,42,.15);padding:0 2px}\n.empty{color:var(--dim);font-style:italic;padding:20px 0}\n.hint{color:var(--dim);font-family:sans-serif;font-size:12px;text-align:center;margin-top:40%}\n</style></head><body>\n<div class="top"><h1>叙事档案</h1><span class="sub">NARRATIVE BROWSER</span><span class="stat" id="stat"></span></div>\n<div class="filters" id="filters"></div>\n<div class="main">\n  <div class="graph-pane"><svg id="g"></svg></div>\n  <div class="side" id="side"><div class="hint">点击左侧任一节点<br>查看详情与原文出处</div></div>\n</div>\n<script>\nconst TC={character:"#a8332a",item:"#b8884a",location:"#6f9b8e"};\nconst TN={character:"人物",item:"物品",location:"地点"};\nlet GRAPH={nodes:[],edges:[]}, show={character:1,item:1,location:1};\nasync function api(p){const r=await fetch(p);return r.json();}\n\nasync function init(){\n  const s=await api(\'/api/summary\');\n  document.getElementById(\'stat\').textContent=\n    `${s.counts.characters||0}人物 · ${s.counts.items||0}物品 · ${s.counts.locations||0}地点 · ${s.counts.events||0}事件 · ${(s.chapters||[]).length}章`;\n  document.getElementById(\'filters\').innerHTML=Object.keys(TN).map(t=>\n    `<label><input type="checkbox" checked data-t="${t}"><i style="background:${TC[t]}"></i>${TN[t]}</label>`).join(\'\');\n  document.querySelectorAll(\'.filters input\').forEach(c=>c.onchange=e=>{show[e.target.dataset.t]=e.target.checked?1:0;draw();});\n  GRAPH=await api(\'/api/graph\');\n  draw();\n}\nfunction draw(){\n  const svg=document.getElementById(\'g\');const W=svg.clientWidth,H=svg.clientHeight;\n  svg.setAttribute(\'viewBox\',`0 0 ${W} ${H}`);\n  const nodes=GRAPH.nodes.filter(n=>show[n.type]);\n  const idset=new Set(nodes.map(n=>n.id));\n  const edges=GRAPH.edges.filter(e=>idset.has(e.from)&&idset.has(e.to));\n  const idx={};nodes.forEach((n,i)=>{idx[n.id]=i;const a=2*Math.PI*i/nodes.length;n.x=W/2+Math.cos(a)*Math.min(W,H)*0.33;n.y=H/2+Math.sin(a)*Math.min(W,H)*0.33;n.vx=0;n.vy=0;});\n  for(let it=0;it<260;it++){\n    nodes.forEach(a=>{a.fx=0;a.fy=0;nodes.forEach(b=>{if(a===b)return;let dx=a.x-b.x,dy=a.y-b.y,d=Math.hypot(dx,dy)||1;let f=5000/(d*d);a.fx+=dx/d*f;a.fy+=dy/d*f;});});\n    edges.forEach(e=>{let a=nodes[idx[e.from]],b=nodes[idx[e.to]];let dx=b.x-a.x,dy=b.y-a.y,d=Math.hypot(dx,dy)||1,f=(d-140)*.02;a.fx+=dx/d*f;a.fy+=dy/d*f;b.fx-=dx/d*f;b.fy-=dy/d*f;});\n    nodes.forEach(n=>{n.x+=Math.max(-7,Math.min(7,n.fx));n.y+=Math.max(-7,Math.min(7,n.fy));n.x=Math.max(40,Math.min(W-40,n.x));n.y=Math.max(30,Math.min(H-30,n.y));});\n  }\n  let h=\'\';\n  edges.forEach(e=>{let a=nodes[idx[e.from]],b=nodes[idx[e.to]];h+=`<line x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}" stroke="${e.kind===\'loc\'?\'#6f9b8e\':\'#b8884a\'}" stroke-width="1" opacity=".4"/>`;});\n  nodes.forEach(n=>{const r=n.type===\'character\'?9:6;h+=`<g class="node" data-id="${n.id}" data-type="${n.type}"><circle cx="${n.x}" cy="${n.y}" r="${r}" fill="${TC[n.type]}" stroke="#2a241d" stroke-width="1.5"/><text x="${n.x}" y="${n.y-r-5}" text-anchor="middle">${n.label}</text></g>`;});\n  svg.innerHTML=h;\n  svg.querySelectorAll(\'.node\').forEach(N=>N.onclick=()=>openNode(N.dataset.type,N.dataset.id.split(\':\')[1],N.querySelector(\'text\').textContent));\n}\nasync function openNode(type,id,label){\n  const side=document.getElementById(\'side\');\n  side.innerHTML=`<h2>${label}</h2><div class="meta">${TN[type]} · 加载原文出处…</div>`;\n  const d=await api(`/api/node/${type}/${id}`);\n  let html=`<h2>${label}</h2><div class="meta">${TN[type]} · ${d.occurrences.length} 处原文出处</div>`;\n  if(!d.occurrences.length){html+=`<div class="empty">未在原文中定位到出处</div>`;}\n  else{\n    for(const o of d.occurrences){\n      const hl=o.sentence.replace(new RegExp(o.term,\'g\'),`<b>${o.term}</b>`);\n      html+=`<div class="occ"><span class="ch">第${o.chapter}章 · 「${o.term}」</span>${hl}</div>`;\n    }\n  }\n  side.innerHTML=html;\n}\ninit();\nwindow.addEventListener(\'resize\',draw);\n</script></body></html>\n'