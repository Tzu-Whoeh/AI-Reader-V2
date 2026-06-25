#!/usr/bin/env python3
"""
叙事分析应用 · 主程序
对指定文件或目录:清洗 → 章节拆分 → 逐章五维度+事件分析 → 全局合并。

用法:
  python app.py <输入文件或目录> [输出目录]

特性:
  - 输入可为单文件或目录(目录下所有 .txt 按文件名排序合并/分别处理)
  - 断点续跑:已完成的章节(存在 _merged.json)跳过
  - 进度与错误隔离:单章失败不影响其余章

依赖同目录:
  clean_split.py  事件管道/各维度提示词/merge_core/cross_chapter/entity_normalize/
  aggregate.py / graph_index.py / gap_scan.py / event_pipeline.py / storage.py
模型调用:替换 call_model()(默认直连 Ollama)。
"""
import os, sys, json, glob, re
import time
import clean_split as CS
import storage, merge_core, aggregate, graph_index, gap_scan, org_extract
import event_pipeline as EP

# ---- 模型调用(默认直连;平台环境替换此函数,并赋给 EP.call_model)----
import urllib.request
# 按任务适配模型:抽取类(识别/共指/关系)用 35b,容量优势;
# 判断类(场景边界判断)用 27b,实测在场景拆分上比 35b 更稳(见 AGENT.md「场景拆分」节)。
DEFAULT_MODEL="huihui_ai/Qwen3.6-abliterated:35b"
PASS_MODELS={
    "scene":   "huihui_ai/Qwen3.6-abliterated:27b",  # 场景拆分:判断任务,27b 更稳
    # 其余 pass(character/item/location/event)未列出者一律走 DEFAULT_MODEL(35b)
}
def model_for(pass_name):
    return PASS_MODELS.get(pass_name, DEFAULT_MODEL)
def _safe_json(s):
    """容忍模型返回被截断的 JSON:先直接解析,失败则尝试补全收尾再解析。"""
    try: return json.loads(s)
    except Exception: pass
    # 截断修复:从末尾去掉不完整片段,补齐括号
    t=s.strip()
    # 去掉末尾未闭合的残句
    for cut in range(len(t),0,-1):
        frag=t[:cut]
        bal=frag.count("{")-frag.count("}")
        barr=frag.count("[")-frag.count("]")
        if bal>=0 and barr>=0 and (frag.rstrip().endswith(("}","]",'"')) or frag.rstrip().endswith(",")):
            fixed=frag.rstrip().rstrip(",")+("]"*barr)+("}"*bal)
            try: return json.loads(fixed)
            except Exception: continue
    raise ValueError("JSON irreparably truncated")

# Ollama 端点可配:默认走 wangcai 隧道 18434(非生产 11434);经 ops 平台/其它环境用 OLLAMA_URL 覆盖。
OLLAMA_URL=os.environ.get("OLLAMA_URL","http://127.0.0.1:18434")
def call_model(prompt, temperature=0.12, num_ctx=49152, timeout=300, retries=1, model=None):
    body={"model":model or DEFAULT_MODEL,"prompt":prompt,"stream":False,"think":False,"format":"json",
          "options":{"temperature":temperature,"num_ctx":num_ctx,"num_predict":4096}}
    last=None
    for _ in range(retries+1):
        req=urllib.request.Request(OLLAMA_URL.rstrip("/")+"/api/generate",
            data=json.dumps(body,ensure_ascii=False).encode(),
            headers={"Content-Type":"application/json"},method="POST")
        with urllib.request.urlopen(req,timeout=timeout) as r:
            resp=json.loads(r.read())["response"]
        try: return _safe_json(resp)
        except Exception as e: last=e
    raise last
EP.call_model=call_model

_HERE=os.path.dirname(os.path.abspath(__file__))
# 提示词的单一真相源是 new-design/prompts/(完整 12 个);pipeline/ 不再存放提示词副本。
# 优先用同级 prompts/;若不存在(如旧布局把提示词放本目录)则回退到本目录,保持向后兼容。
_SIBLING_PROMPTS=os.path.join(os.path.dirname(_HERE),"prompts")
PROMPTS=_SIBLING_PROMPTS if os.path.isdir(_SIBLING_PROMPTS) else _HERE
def L(fn): return open(os.path.join(PROMPTS,fn),encoding="utf-8").read()
EP.set_prompts_dir(PROMPTS)  # 让事件管道也用同一提示词目录
VEH=("车","轿车","雪佛来","汽车")

def read_input(path):
    """文件或目录 → 单一原始文本(目录下 txt 按名排序拼接)。"""
    if os.path.isdir(path):
        parts=[]
        for f in sorted(glob.glob(os.path.join(path,"*.txt"))):
            parts.append(open(f,encoding="utf-8",errors="replace").read())
        return "\n\n".join(parts)
    return open(path,encoding="utf-8",errors="replace").read()

CHAPTER_STEPS = [
    ("scene", "场景拆分"),
    ("character_p1", "人物识别"),
    ("character_p2", "人物关系"),
    ("item_p1", "物品抽取"),
    ("item_p2", "物品关系"),
    ("location_p1", "地点识别"),
    ("location_p2", "地点关系"),
    ("events", "事件分析"),
    ("organization", "组织识别"),
    ("merge", "归并与后处理"),
]
STEP_TOTAL = len(CHAPTER_STEPS)

def analyze_chapter(text, step_cb=None):
    """单章五维度 + 事件 + 章节归并。返回 merged dict。
    step_cb(step, name, idx, total) 可选:每个子步骤开始时回调,用于细粒度进度。"""
    def step(i):
        if step_cb:
            k, nm = CHAPTER_STEPS[i]
            try: step_cb(k, nm, i + 1, STEP_TOTAL)
            except Exception: pass
    step(0)
    scenes=call_model(L("01_scene_splitting.txt").replace("{TEXT}",text),temperature=0.15,model=model_for("scene"))
    # 人物 2pass
    step(1)
    c1=call_model(L("02_character_pass1_recognition.txt").replace("{TEXT}",text))
    clist="\n".join(f'  id={c["id"]} name="{c["name"]}" role="{c.get("role","")}"' for c in c1["characters"])
    step(2)
    c2=call_model(L("02_character_pass2_relations.txt").replace("{CHARLIST}",clist).replace("{TEXT}",text))
    c1["relations"]=c2.get("relations",[])
    # 物品 2pass(注入场景清单)
    slist="\n".join(f'  index={s.get("index")} title="{s.get("title","")}" start="{(s.get("start_text") or "")[:15]}" end="{(s.get("end_text") or "")[:15]}"' for s in scenes.get("scenes",[]))
    step(3)
    i1=call_model(L("03_item_pass1_extraction.txt").replace("{SCENELIST}",slist).replace("{TEXT}",text))
    ilist="\n".join(f'  id={it["id"]} name="{it["name"]}" category={it["category"]}' for it in i1["items"])
    step(4)
    i2=call_model(L("03_item_pass2_relations.txt").replace("{ITEMLIST}",ilist).replace("{TEXT}",text))
    rmap={r["id"]:r for r in i2.get("relations",[])}
    for it in i1["items"]:
        r=rmap.get(it["id"],{}); it["part_of"]=r.get("part_of"); it["set_group"]=r.get("set_group","")
    # 地点 2pass(+交通工具过滤)
    step(5)
    l1=call_model(L("04_location_pass1_recognition.txt").replace("{TEXT}",text))
    l1["locations"]=[l for l in l1["locations"] if not any(w in l["name"] for w in VEH)]
    llist="\n".join(f'  id={l["id"]} name="{l["name"]}" scale={l["scale"]}' for l in l1["locations"])
    step(6)
    l2=call_model(L("04_location_pass2_relations.txt").replace("{LOCLIST}",llist).replace("{TEXT}",text))
    l1["relations"]=l2.get("relations",[])
    # 事件
    step(7)
    # 章节归并(跨维度 id 解析)
    merged=merge_core.merge(text, scenes, c1, i1, l1)
    merged["character_relations"]=c2.get("relations",[])
    merged["location_relations"]=l2.get("relations",[])
    for s in merged["scenes"]:
        pass  # location_ref 已在 merge 内解析到 scenes
    ev=EP.analyze_events(text, merged["scenes"], merged["characters"], merged["items"])
    merged["parent_events"]=ev["parent_events"]
    merged["sub_events"]=ev["sub_events"]
    merged["time_refs"]=ev.get("time_refs",[])
    # 组织维度(明说成员归属守红线;确定性后处理 + 成员名归一)
    step(8)
    try:
        o_raw=call_model(L("09_org_extraction.txt").replace("{TEXT}",text))
        o_clean=org_extract.postprocess(o_raw, text)
        merged["organizations"]=o_clean["organizations"]
        merged["org_memberships"]=org_extract.resolve_member_ids(o_clean["memberships"], merged.get("characters",[]))
        merged["org_relations"]=o_clean["org_relations"]
    except Exception as e:
        merged["organizations"]=[]; merged["org_memberships"]=[]; merged["org_relations"]=[]
        merged.setdefault("_postproc_errors",[]).append(f"organization: {e}")
    # 确定性后处理(不调模型):逐章建全向图索引 + 漏标疑点扫描,挂进本章产物
    step(9)
    try:
        merged["_graph"]=graph_index.build_graph(merged, ev)
    except Exception as e:
        merged["_graph"]=None; merged.setdefault("_postproc_errors",[]).append(f"graph_index: {e}")
    try:
        merged["_gap_suspects"]=gap_scan.scan(text, merged, ev)
    except Exception as e:
        merged["_gap_suspects"]=[]; merged.setdefault("_postproc_errors",[]).append(f"gap_scan: {e}")
    return merged

def load_presplit(dir_path):
    """目录下每个 chNN.txt 直接当一章(各自清洗,不拼接不重新拆分)。
    章号从文件名数字提取;无数字则按排序序号。"""
    chapters=[]
    files=sorted(f for f in os.listdir(dir_path) if f.endswith(".txt"))
    for i,f in enumerate(files,1):
        raw=open(os.path.join(dir_path,f),encoding="utf-8",errors="replace").read()
        cleaned,_=CS.clean(raw)
        mobj=re.search(r'(\d+)', f)
        idx=int(mobj.group(1)) if mobj else i
        chapters.append({"index":idx,"title":os.path.splitext(f)[0],"text":cleaned.strip()})
    chapters.sort(key=lambda c:c["index"])
    return chapters

def run(input_path, out_dir="output", presplit=False, progress_cb=None, should_continue=None):
    """progress_cb(event:dict) 可选回调,用于任务层捕获进度;不传则纯命令行行为不变。
    should_continue() -> "go"|"pause"|"stop" 可选:每章开始前查询控制状态。
      pause:run 在章间阻塞轮询(2s)直到 go/stop —— 实现章间软停(不打断进行中的章)。
      stop:停止后续章,但仍对已完成章做全局聚合后返回。"""
    def _control():
        if not should_continue: return "go"
        try: return should_continue() or "go"
        except Exception: return "go" 
    def emit(**ev):
        if progress_cb:
            try: progress_cb(ev)
            except Exception: pass
    store=storage.Store(out_dir)
    if presplit:
        if not os.path.isdir(input_path):
            print("[错误] --presplit 需要输入为目录"); emit(stage="error",detail="presplit 需目录"); return
        chapters=load_presplit(input_path)
        print(f"[预拆分模式] 每个 txt 当一章,共 {len(chapters)} 章")
    else:
        raw=read_input(input_path)
        cleaned, rep=CS.clean(raw)
        chapters=CS.split_chapters(cleaned)
        print(f"[清洗] 删除 {rep['dropped_count']} 行噪音")
        print(f"[拆分] {len(chapters)} 章")
    total=len(chapters)
    emit(stage="split", total=total, done=0)

    done=0
    stopped=False
    for c in chapters:
        # 章间软停检查:pause 则阻塞轮询,stop 则跳出
        st=_control()
        while st=="pause":
            emit(stage="paused", total=total, done=done)
            time.sleep(2)
            st=_control()
        if st=="stop":
            print("[控制] 收到 stop,停止后续章,聚合已完成部分")
            emit(stage="stopping", total=total, done=done)
            stopped=True
            break
        ch=c["index"]
        cdir=os.path.join(out_dir,f"ch{ch:02d}")
        merged_path=os.path.join(cdir,"_merged.json")
        if os.path.exists(merged_path):
            print(f"[ch{ch:02d}] 已存在,跳过(断点续跑)"); done+=1
            emit(stage="chapter", chapter=ch, total=total, done=done, skipped=True); continue
        emit(stage="chapter_start", chapter=ch, total=total, done=done)
        def _step_cb(k, nm, idx, tot, _ch=ch, _done=done, _total=total):
            emit(stage="step", chapter=_ch, step=k, step_name=nm,
                 step_idx=idx, step_total=tot, total=_total, done=_done)
        try:
            if len(c["text"])>40000:
                print(f"[ch{ch:02d}] 超长章({len(c['text'])}字),可能逼近上下文上限")
            merged=analyze_chapter(c["text"], step_cb=_step_cb)
            merged["_title"]=c["title"]
            store.save_chapter_merged(ch, merged)
            done+=1
            print(f"[ch{ch:02d}] ✓ 「{c['title']}」 场景{len(merged.get('scenes',[]))} 人物{len(merged.get('characters',[]))} 事件{len(merged.get('parent_events',[]))}")
            emit(stage="chapter", chapter=ch, total=total, done=done,
                 title=c["title"], scenes=len(merged.get("scenes",[])),
                 characters=len(merged.get("characters",[])), events=len(merged.get("parent_events",[])))
        except Exception as e:
            print(f"[ch{ch:02d}] ✗ 失败: {e} (跳过,继续下一章)")
            emit(stage="chapter_error", chapter=ch, total=total, done=done, error=str(e))

    # 全局合并(确定性)
    print("[全局] 跨章合并 + 聚合 + 图索引 + 漏标扫描")
    emit(stage="aggregate", total=total, done=done)
    idx=aggregate.aggregate(store)
    print(f"[全局] 完成: {idx['counts']}")
    emit(stage="done", total=total, done=done, counts=idx.get("counts",{}))
    return idx

if __name__=="__main__":
    args=[a for a in sys.argv[1:] if not a.startswith("--")]
    presplit="--presplit" in sys.argv
    if len(args)<1:
        print("用法: python app.py <文件或目录> [输出目录] [--presplit]")
        print("  --presplit: 输入目录下每个 .txt 当作一章(用于已拆分的原文)")
        sys.exit(1)
    inp=args[0]; out=args[1] if len(args)>1 else "output"
    run(inp, out, presplit=presplit)