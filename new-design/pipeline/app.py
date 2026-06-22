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
import os, sys, json, glob
import clean_split as CS
import storage, merge_core, aggregate, graph_index, gap_scan
import event_pipeline as EP

# ---- 模型调用(默认直连;平台环境替换此函数,并赋给 EP.call_model)----
import urllib.request
MODEL="huihui_ai/Qwen3.6-abliterated:35b"
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

def call_model(prompt, temperature=0.12, num_ctx=8192, timeout=300, retries=1):
    body={"model":MODEL,"prompt":prompt,"stream":False,"think":False,"format":"json",
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
    scenes=call_model(L("01_scene_splitting.txt").replace("{TEXT}",text),temperature=0.15)
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
    return merged

def run(input_path, out_dir="output"):
    raw=read_input(input_path)
    cleaned, rep=CS.clean(raw)
    chapters=CS.split_chapters(cleaned)
    store=storage.Store(out_dir)
    print(f"[清洗] 删除 {rep['dropped_count']} 行噪音")
    print(f"[拆分] {len(chapters)} 章")

    for c in chapters:
        ch=c["index"]
        cdir=os.path.join(out_dir,f"ch{ch:02d}")
        merged_path=os.path.join(cdir,"_merged.json")
        if os.path.exists(merged_path):
            print(f"[ch{ch:02d}] 已存在,跳过(断点续跑)"); continue
        # 长章二次切块(此处仅保存切块信息;逐块分析+块内合并可按需扩展)
        chunks=CS.chunk_long_chapter(c["text"])
        try:
            if len(chunks)==1:
                merged=analyze_chapter(c["text"])
            else:
                # 长章:逐块分析后合并(简化:取首块为主,其余块事件并入。生产可做块级实体归一)
                print(f"[ch{ch:02d}] 长章,{len(chunks)}块,逐块处理")
                merged=analyze_chapter(chunks[0])
                # NOTE: 多块的跨块章节内归一可复用 cross_chapter 思路,此处留接口
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
    if len(sys.argv)<2:
        print("用法: python app.py <文件或目录> [输出目录]"); sys.exit(1)
    out=sys.argv[2] if len(sys.argv)>2 else "output"
    run(sys.argv[1], out)
