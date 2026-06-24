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
import os, json, re, argparse, mimetypes, posixpath
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, unquote

OUTPUT_DIR="output"
RAW={}          # chapter_index -> raw text
GLOBALS={}      # dimension -> json
CHAPTERS=[]     # merged per chapter
BASE_PATH=""    # 部署前缀,如 "/new";nginx 透传时由 --base-path 设定
STATIC_DIR=None # Vite 产物目录(pipeline/static);存在则优先托管,否则回退内嵌 FRONTEND

def load_data(output_dir, raw_dir):
    global OUTPUT_DIR, RAW, GLOBALS, CHAPTERS
    OUTPUT_DIR=output_dir
    # 全局维度
    gdir=os.path.join(output_dir,"global")
    for name in ("characters","items","locations","timeline","scenes"):
        p=os.path.join(gdir,f"{name}.json")
        if os.path.exists(p): GLOBALS[name]=json.load(open(p,encoding="utf-8"))
    # 各章 merged
    chs=sorted(d for d in os.listdir(output_dir) if d.startswith("ch") and d[2:].isdigit())
    for d in chs:
        mp=os.path.join(output_dir,d,"_merged.json")
        if os.path.exists(mp):
            m=json.load(open(mp,encoding="utf-8")); m["_chapter"]=int(d[2:])
            CHAPTERS.append(m)
    # 原文(raw_dir 下 chNN.txt;或目录里所有 txt 按序当章)
    if raw_dir and os.path.isdir(raw_dir):
        txts=sorted(f for f in os.listdir(raw_dir) if f.endswith(".txt"))
        for i,f in enumerate(txts,1):
            mobj=re.search(r'(\d+)', f)
            idx=int(mobj.group(1)) if mobj else i
            RAW[idx]=open(os.path.join(raw_dir,f),encoding="utf-8",errors="replace").read()

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

class Handler(BaseHTTPRequestHandler):
    def _send(self, obj, ct="application/json"):
        body=(obj if isinstance(obj,bytes) else json.dumps(obj,ensure_ascii=False).encode())
        self.send_response(200); self.send_header("Content-Type",ct)
        self.send_header("Access-Control-Allow-Origin","*")
        self.end_headers(); self.wfile.write(body)

    def _serve_static(self, rel):
        """从 STATIC_DIR 安全托管一个文件;命中返回 True。"""
        if not STATIC_DIR: return False
        # 防目录穿越:规范化后必须仍在 STATIC_DIR 内
        rel=posixpath.normpath("/"+rel).lstrip("/")
        fp=os.path.join(STATIC_DIR, rel)
        if not os.path.isfile(fp): return False
        if os.path.commonpath([os.path.realpath(fp), os.path.realpath(STATIC_DIR)])!=os.path.realpath(STATIC_DIR):
            return False
        ct=mimetypes.guess_type(fp)[0] or "application/octet-stream"
        with open(fp,"rb") as f: body=f.read()
        self.send_response(200); self.send_header("Content-Type",ct)
        self.send_header("Access-Control-Allow-Origin","*")
        self.end_headers(); self.wfile.write(body)
        return True

    def do_GET(self):
        path=urlparse(self.path).path
        # 剥离部署前缀(nginx 透传 /new 时 path 形如 /new/...)
        if BASE_PATH and (path==BASE_PATH or path.startswith(BASE_PATH+"/")):
            path=path[len(BASE_PATH):] or "/"
        elif BASE_PATH and path=="/":
            pass
        if path=="/" or path=="/index.html":
            # 优先 Vite 产物的 index.html,缺失则回退内嵌 FRONTEND
            if self._serve_static("index.html"): return
            return self._send(FRONTEND.encode(), "text/html; charset=utf-8")
        # 静态资源(Vite 产物 /assets/* 等)
        if not path.startswith("/api/") and self._serve_static(path.lstrip("/")):
            return
        if path=="/api/summary":
            return self._send({
                "chapters":[m["_chapter"] for m in CHAPTERS],
                "counts":GLOBALS.get("characters",{}) and {
                    "characters":len(GLOBALS.get("characters",{}).get("global_characters",[])),
                    "items":len(GLOBALS.get("items",{}).get("global_items",[])),
                    "locations":len(GLOBALS.get("locations",{}).get("global_locations",[])),
                    "events":len(GLOBALS.get("timeline",{}).get("global_events",[])),
                }})
        if path=="/api/graph":
            return self._send(build_graph())
        if path=="/api/events":
            return self._send(build_events())
        if path=="/api/chapters":
            # 阅读器:可读章列表(有原文的章)
            return self._send({"chapters":sorted(RAW.keys())})
        if path.startswith("/api/reader/"):
            try: ch=int(unquote(path.split("/")[-1]))
            except: return self._send({"error":"章号无效"})
            return self._send(build_reader(ch))
        if path.startswith("/api/dimension/"):
            name=unquote(path.split("/")[-1])
            return self._send(GLOBALS.get(name,{}))
        if path.startswith("/api/node/"):
            parts=path.split("/")
            ntype=parts[3]; nid=unquote(parts[4])
            try: nid_v=int(nid)
            except: nid_v=nid
            anchors=node_anchors(ntype,nid_v)
            return self._send({"type":ntype,"id":nid_v,"anchors":anchors,
                               "occurrences":find_occurrences([a for a in anchors if a])})
        self.send_response(404); self.end_headers()
    def log_message(self,*a): pass

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
    gevents=GLOBALS.get("timeline",{}).get("global_events",[])

    char_ids={g["global_id"] for g in gchars}
    item_ids={g["global_id"] for g in gitems}
    loc_ids={g["global_id"] for g in glocs}

    for g in gchars:
        nodes.append({"id":f"character:{g['global_id']}","label":g["canonical"],"type":"character"})
    for g in gitems:
        nodes.append({"id":f"item:{g['global_id']}","label":g["canonical"],"type":"item"})
    for g in glocs:
        nodes.append({"id":f"location:{g['global_id']}","label":g["canonical"],"type":"location"})
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

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--output",default="output")
    ap.add_argument("--raw",default=None)
    ap.add_argument("--port",type=int,default=8080)
    ap.add_argument("--base-path",default="",
                    help="部署前缀,如 /new(nginx 透传时设);迁顶层留空")
    ap.add_argument("--static",default=None,
                    help="Vite 产物目录(默认同级 static/);存在则优先托管,否则回退内嵌前端")
    ap.add_argument("--no-validate",action="store_true",help="跳过启动自检")
    args=ap.parse_args()
    BASE_PATH=args.base_path.rstrip("/")
    sd=args.static or os.path.join(os.path.dirname(os.path.abspath(__file__)),"static")
    STATIC_DIR=sd if os.path.isdir(sd) else None
    load_data(args.output,args.raw)
    print(f"加载: {len(CHAPTERS)}章, 原文{len(RAW)}章")
    # 启动自检:跑 R1–R6,打印 ValidationReport(发现问题仅告警,不阻断启动)
    if not args.no_validate:
        try:
            import validate as _V
            gdir=os.path.join(args.output,"global")
            raw_by_ch=RAW or None
            local_by_ch={m["_chapter"]:m for m in CHAPTERS} or None
            rep=_V.validate_global(gdir, raw_by_chapter=raw_by_ch, local_by_chapter=local_by_ch)
            print(f"自检: {'✓ 通过' if rep.ok else '✗ %d 错误'%len(rep.errors)}"
                  f" · {len(rep.warnings)} 告警")
            for it in rep.errors[:5]:
                print(f"  ERR {it.rule} {it.path}: {it.detail[:60]}")
        except Exception as ex:
            print(f"自检: 跳过(validate 不可用: {ex})")
    print(f"前端: {'Vite产物 '+STATIC_DIR if STATIC_DIR else '内嵌 FRONTEND(回退)'}")
    print(f"服务: http://127.0.0.1:{args.port}{BASE_PATH or '/'}")
    HTTPServer(("127.0.0.1",args.port), Handler).serve_forever()
