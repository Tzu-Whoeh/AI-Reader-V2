"""叙事分析归并核心:四主题 JSON -> 统一结构 + 跨维度 id 引用解析。纯确定性,不过模型。"""
import json, re

# ---------- 锚点校验 ----------
def anchor_clean(records, text, name_key, mention_keys):
    """剔除 mention/alias 中原文不存在的项,记录到 dropped。"""
    report=[]
    for r in records:
        for mk in mention_keys:
            if mk not in r: continue
            kept,dropped=[],[]
            for m in r[mk]:
                (kept if m in text else dropped).append(m)
            r[mk]=kept
            if dropped: report.append({"id":r.get("id"),"name":r.get(name_key),"key":mk,"dropped":dropped})
    return report

# ---------- 跨维度名称解析 ----------
def build_name_index(records, name_key="name", alias_key=None):
    """name/alias -> id 的查找表。长名优先(避免'武田'误配到别的)。"""
    idx=[]
    for r in records:
        names=[r.get(name_key,"")]
        if alias_key and r.get(alias_key): names+=list(r[alias_key])
        for n in names:
            if n: idx.append((n, r["id"]))
    idx.sort(key=lambda x:-len(x[0]))   # 长名优先
    return idx

def resolve(value, idx):
    """把一个字符串(如 owner='武田勇夫')解析成 id。返回 (id, matched_name) 或 (None,None)。"""
    if not value: return (None,None)
    for n,i in idx:
        if n==value: return (i,n)           # 精确优先
    for n,i in idx:
        if n and (n in value or value in n): return (i,n)  # 包含次之
    return (None,None)

# ---------- 主归并 ----------

def resolve_item_locations(items, scenes):
    """物品 scene 字段 -> 场景 location_ref -> 物品 location_ref(确定性推导)。
    scene 可为 int 或 list。物品可经过多地点。"""
    scene_loc={}  # scene index -> location_id
    for sc in scenes:
        idx=sc.get("index")
        ref=sc.get("location_ref")
        if idx is not None and ref:
            scene_loc[idx]=ref["location_id"]
    for it in items:
        sv=it.get("scene")
        if sv is None: 
            it["location_refs"]=[]; continue
        scenes_of=sv if isinstance(sv,list) else [sv]
        locs=[]
        for s in scenes_of:
            lid=scene_loc.get(s)
            if lid is not None and lid not in [l["location_id"] for l in locs]:
                locs.append({"location_id":lid,"via_scene":s})
        it["location_refs"]=locs
    return items

_THINK_MARKERS=["修正","思考","让我","重新审视","重新扫描","判定为","不收录","让我们","应排除","candidate","*修正*","\n"]
def sanitize_items(items):
    """剔除模型抽风产生的脏物品:字段污染(思考写进name)、id重复、错误container关系。"""
    report=[]; seen=set(); clean=[]
    id2name={it.get("id"):it.get("name","") for it in items}  # 供container语义校验查whole名
    for it in items:
        name=it.get("name","")
        # 1) name 污染:超长或含思考标志词
        if len(name)>20 or any(m in name for m in _THINK_MARKERS):
            report.append({"reason":"name污染/超长","id":it.get("id"),"head":name[:25]}); continue
        # 2) mentions 清洗
        it["mentions"]=[m for m in it.get("mentions",[]) if isinstance(m,str) and len(m)<=20
                        and not any(k in m for k in _THINK_MARKERS)]
        # 3) 错误 container 关系:语义校验 —— container 的 whole 必须真是容器(非场所)
        po=it.get("part_of")
        if po and po.get("relation")=="container":
            whole=id2name.get(po.get("whole_id"),"")
            PLACE_WORDS=["间","房","室","厅","院","所","场","馆"]
            CONTAINER_WORDS=["包","袋","箱","盒","桶","杯","瓶","壶","柜","抽屉","口袋","篮","筐","匣","罐","缸","兜"]
            is_container = (not any(p in whole for p in PLACE_WORDS)) and any(c in whole for c in CONTAINER_WORDS)
            if not is_container:
                it["part_of"]=None  # whole 不是容器 → container 关系不成立
        # 4) id 去重(去污染后再去重,保留先出现的干净条目)
        if it.get("id") in seen:
            report.append({"reason":"id重复","id":it.get("id"),"name":name}); continue
        seen.add(it.get("id")); clean.append(it)
    return clean, report

def merge(text, scenes, characters, items, locations):
    items_clean, item_report=sanitize_items(items.get("items",[]))
    out={"scenes":scenes.get("scenes",[]),
         "characters":characters.get("characters",[]),
         "items":items_clean,
         "locations":locations.get("locations",[]),
         "_validation":{"anchors":[], "xref":[], "item_sanitize":item_report}}

    # 锚点校验各维度
    out["_validation"]["anchors"]+=anchor_clean(out["characters"], text, "name", ["aliases"])
    out["_validation"]["anchors"]+=anchor_clean(out["items"], text, "name", ["mentions"])
    out["_validation"]["anchors"]+=anchor_clean(out["locations"], text, "name", ["mentions"])

    # 索引
    char_idx=build_name_index(out["characters"],"name","aliases")
    loc_idx =build_name_index(out["locations"],"name","mentions")

    # 跨维度1: item.owner -> character id
    for it in out["items"]:
        cid,matched=resolve(it.get("owner",""), char_idx)
        if cid is not None:
            it["owner_ref"]={"character_id":cid,"matched":matched}
        elif it.get("owner"):
            out["_validation"]["xref"].append({"type":"item.owner未匹配","item":it.get("name"),"owner":it["owner"]})

    # 跨维度2: scene.location -> location id
    for sc in out["scenes"]:
        lid,matched=resolve(sc.get("location",""), loc_idx)
        if lid is not None:
            sc["location_ref"]={"location_id":lid,"matched":matched}
        elif sc.get("location") and sc.get("location")!="未明":
            out["_validation"]["xref"].append({"type":"scene.location未匹配","scene":sc.get("title"),"location":sc["location"]})

    resolve_item_locations(out["items"], out["scenes"])
    out["counts"]={k:len(out[k]) for k in("scenes","characters","items","locations")}
    return out
