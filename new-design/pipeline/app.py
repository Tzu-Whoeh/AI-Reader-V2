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
import clean_split as CS
import storage, merge_core, aggregate, graph_index, gap_scan
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

def call_model(prompt, temperature=0.12, num_ctx=49152, timeout=300, retries=1, model=None):
    body={"model":model or DEFAULT_MODEL,"prompt":prompt,"stream":False,"think":False,"format":"json",
          "options":{"temperature":temperature,"num_ctx":num_ctx,"num_predict":4096}}
    last=None
    for _ in range(retries+1):
        req=urllib.request.Request("http://127.0.0.1:11434/api/generate",
            data=json.dumps(body,ensure_ascii=False).encode(),
            headers={"Content-Type":"application/json"},method="POST")
        with urllib.request.urlopen(req,timeout=timeout) as r:
            resp=json.loads(r.read())["response"]
        try: return _safe_json(resp)
        except Exception as e: last=e
    raise last
EP.call_model=call_model

PROMPTS=os.path.dirname(os.path.abspath(__file__))  # 提示词默认在本脚本同目录
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

def analyze_chapter(text):
    """单章五维度 + 事件 + 章节归并。返回 merged dict。"""
    scenes=call_model(L("01_scene_splitting.txt").replace("{TEXT}",text),temperature=0.15,model=model_for("scene"))
    # 人物 2pass
    c1=call_model(L("02_character_pass1_recognition.txt").replace("{TEXT}",text))
    clist="\n".join(f'  id={c["id"]} name="{c["name"]}" role="{c.get("role","")}"' for c in c1["characters"])
    c2=call_model(L("02_character_pass2_relations.txt").replace("{CHARLIST}",clist).replace("{TEXT}",text))
    c1["relations"]=c2.get("relations",[])
    # 物品 2pass(注入场景清单)
    slist="\n".join(f'  index={s.get("index")} title="{s.get("title","")}" start="{(s.get("start_text") or "")[:15]}" end="{(s.get("end_text") or "")[:15]}"' for s in scenes.get("scenes",[]))
    i1=call_model(L("03_item_pass1_extraction.txt").replace("{SCENELIST}",slist).replace("{TEXT}",text))
    ilist="\n".join(f'  id={it["id"]} name="{it["name"]}" category={it["category"]}' for it in i1["items"])
    i2=call_model(L("03_item_pass2_relations.txt").replace("{ITEMLIST}",ilist).replace("{TEXT}",text))
    rmap={r["id"]:r for r in i2.get("relations",[])}
    for it in i1["items"]:
        r=rmap.get(it["id"],{}); it["part_of"]=r.get("part_of"); it["set_group"]=r.get("set_group","")
    # 地点 2pass(+交通工具过滤)
    l1=call_model(L("04_location_pass1_recognition.txt").replace("{TEXT}",text))
    l1["locations"]=[l for l in l1["locations"] if not any(w in l["name"] for w in VEH)]
    llist="\n".join(f'  id={l["id"]} name="{l["name"]}" scale={l["scale"]}' for l in l1["locations"])
    l2=call_model(L("04_location_pass2_relations.txt").replace("{LOCLIST}",llist).replace("{TEXT}",text))
    l1["relations"]=l2.get("relations",[])
    # 章节归并(跨维度 id 解析)
    merged=merge_core.merge(text, scenes, c1, i1, l1)
    merged["character_relations"]=c2.get("relations",[])
    merged["location_relations"]=l2.get("relations",[])
    # 两层事件(给场景补 location_ref 供事件→地点推导)
    for s in merged["scenes"]:
        pass  # location_ref 已在 merge 内解析到 scenes
    ev=EP.analyze_events(text, merged["scenes"], merged["characters"], merged["items"])
    merged["parent_events"]=ev["parent_events"]
    merged["sub_events"]=ev["sub_events"]
    merged["time_refs"]=ev.get("time_refs",[])
    # 确定性后处理(不调模型):逐章建全向图索引 + 漏标疑点扫描,挂进本章产物
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

def run(input_path, out_dir="output", presplit=False):
    store=storage.Store(out_dir)
    if presplit:
        if not os.path.isdir(input_path):
            print("[错误] --presplit 需要输入为目录"); return
        chapters=load_presplit(input_path)
        print(f"[预拆分模式] 每个 txt 当一章,共 {len(chapters)} 章")
    else:
        raw=read_input(input_path)
        cleaned, rep=CS.clean(raw)
        chapters=CS.split_chapters(cleaned)
        print(f"[清洗] 删除 {rep['dropped_count']} 行噪音")
        print(f"[拆分] {len(chapters)} 章")

    for c in chapters:
        ch=c["index"]
        cdir=os.path.join(out_dir,f"ch{ch:02d}")
        merged_path=os.path.join(cdir,"_merged.json")
        if os.path.exists(merged_path):
            print(f"[ch{ch:02d}] 已存在,跳过(断点续跑)"); continue
        # num_ctx=49152 可容纳整章(实测31k字≈21k token),整章处理保证指代/共指完整
        try:
            if len(c["text"])>40000:  # 超长极端章(>40k字)才警告,仍尝试整章
                print(f"[ch{ch:02d}] 超长章({len(c['text'])}字),可能逼近上下文上限")
            merged=analyze_chapter(c["text"])
            merged["_title"]=c["title"]
            store.save_chapter_merged(ch, merged)
            print(f"[ch{ch:02d}] ✓ 「{c['title']}」 场景{len(merged.get('scenes',[]))} 人物{len(merged.get('characters',[]))} 事件{len(merged.get('parent_events',[]))}")
        except Exception as e:
            print(f"[ch{ch:02d}] ✗ 失败: {e} (跳过,继续下一章)")

    # 全局合并(确定性)
    print("[全局] 跨章合并 + 聚合 + 图索引 + 漏标扫描")
    idx=aggregate.aggregate(store)
    print(f"[全局] 完成: {idx['counts']}")
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
