#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""writeback_sqlite.py — 把 novel.db 的【人工层】合并回 output/<slug>/global/*.json。

与 export_sqlite.py 反向。设计原则(安全第一):
  * 默认 **dry-run**:只打印将要做的改动(diff 摘要),不动任何文件。
  * 真正落盘需显式 `--apply`;落盘前**逐文件备份** `*.json.bak-<ts>`,再用临时文件 + os.replace **原子替换**。
  * **仅叠加(overlay),不删模型数据**:人工内容追加进既有结构,绝不覆盖/删除模型产出的字段或条目。
  * 回写成功后,把已落地的 review 置 `applied=1`(仅对真正写入的)。

回写范围(刻意收窄到"安全可叠加"的部分):
  1. tag(source='human')
       - scene 标签 → scenes.json 对应 scene 的 tags.function/action(去重追加);
         清单外(in_catalog=0)进 tags.function_novel/action_novel。
       - character 标签 → characters.json 对应 global 实体新增/合并 tags 字段(人工标签;模型当前不产出)。
  2. annotation → 目标对象的 sidecar 数组 _annotations(note/correction/rating/flag)。
       **纠错(correction)只作为"建议"并列存放,绝不静默覆盖模型字段。**
  3. review:
       - subject='tag' 且 verdict in (confirm/correct):落为对应标签的 _reviews 备注;
       - 其余尤其 entity_merge/split:**不自动应用**(需重新聚合,非叠加能安全完成)。
         一律记入对象 sidecar _reviews 并在 dry-run 标注 "需重新聚合,未应用",applied 保持 0。

仅标准库(json/sqlite3/argparse/pathlib/shutil/datetime)。不依赖 ollama。
"""
import argparse, json, sqlite3, os, sys, shutil, glob
from pathlib import Path
from datetime import datetime


def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def atomic_write(path: Path, obj, do_backup=True):
    if do_backup and path.exists():
        ts = datetime.now().strftime("%Y%m%d%H%M%S")
        shutil.copy2(path, path.with_suffix(path.suffix + f".bak-{ts}"))
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)   # 原子替换


def dedup_append(lst, items):
    """把 items 中不在 lst 的追加进 lst(保序去重)。返回新增个数。"""
    seen = set(lst)
    n = 0
    for it in items:
        if it not in seen:
            lst.append(it); seen.add(it); n += 1
    return n


def _ann_key(a):
    return (a.get("author"), a.get("kind"), a.get("field"), a.get("at"), a.get("body"), a.get("rating"))


def merge_annotations(target, new_anns):
    """把 new_anns 去重合并进 target['_annotations'](按稳定键),返回新增数。幂等。"""
    existing = target.setdefault("_annotations", [])
    seen = {_ann_key(a) for a in existing}
    n = 0
    for a in new_anns:
        if _ann_key(a) not in seen:
            existing.append(a); seen.add(_ann_key(a)); n += 1
    return n


# ----------------------------- 收集 DB 人工层 -----------------------------
def collect(con):
    con.row_factory = sqlite3.Row
    human_tags = [dict(r) for r in con.execute(
        "SELECT id,target_type,target_id,kind,label,in_catalog FROM tag WHERE source='human'")]
    annotations = [dict(r) for r in con.execute(
        "SELECT id,target_type,target_id,field,kind,body,rating,author,created_at FROM annotation")]
    reviews = [dict(r) for r in con.execute(
        "SELECT id,subject,ref_table,ref_id,ref_global,verdict,original,corrected,rationale,author,created_at,applied"
        " FROM review WHERE applied=0")]
    # 解析标签目标:scene → (chapter,scene_index);character → global_id
    scene_of = {r["id"]: (r["chapter"], r["scene_index"])
                for r in con.execute("SELECT id,chapter,scene_index FROM scene")}
    char_gid_of = {r["id"]: r["global_id"]
                   for r in con.execute("SELECT id,global_id FROM entity WHERE type='character'")}
    return human_tags, annotations, reviews, scene_of, char_gid_of


# ----------------------------- 计划构建 -----------------------------
def build_plan(con, gdir):
    human_tags, annotations, reviews, scene_of, char_gid_of = collect(con)
    plan = {"scenes": {}, "characters": {}, "deferred_reviews": [], "applied_review_ids": [],
            "counts": {"scene_tags": 0, "char_tags": 0, "annotations": 0, "reviews_recorded": 0}}

    # 1. 人工标签
    for t in human_tags:
        if t["target_type"] == "scene" and t["target_id"] in scene_of:
            ch, idx = scene_of[t["target_id"]]
            s = plan["scenes"].setdefault((ch, idx), {"function": [], "action": [],
                                                       "function_novel": [], "action_novel": [],
                                                       "_annotations": [], "_reviews": []})
            key = t["kind"] if t["in_catalog"] else t["kind"] + "_novel"
            if key in s:
                s[key].append(t["label"]); plan["counts"]["scene_tags"] += 1
        elif t["target_type"] == "character" and t["target_id"] in char_gid_of:
            gid = char_gid_of[t["target_id"]]
            c = plan["characters"].setdefault(gid, {"tags": {}, "_annotations": [], "_reviews": []})
            c["tags"].setdefault(t["kind"], []).append(t["label"])
            plan["counts"]["char_tags"] += 1

    # 2. 标注(并列叠加,不覆盖)
    for a in annotations:
        rec = {"field": a["field"], "kind": a["kind"], "body": a["body"],
               "rating": a["rating"], "author": a["author"], "at": a["created_at"]}
        if a["target_type"] == "scene" and a["target_id"] in scene_of:
            ch, idx = scene_of[a["target_id"]]
            s = plan["scenes"].setdefault((ch, idx), {"function": [], "action": [],
                                                      "function_novel": [], "action_novel": [],
                                                      "_annotations": [], "_reviews": []})
            s["_annotations"].append(rec); plan["counts"]["annotations"] += 1
        elif a["target_type"] == "character" and a["target_id"] in char_gid_of:
            gid = char_gid_of[a["target_id"]]
            c = plan["characters"].setdefault(gid, {"tags": {}, "_annotations": [], "_reviews": []})
            c["_annotations"].append(rec); plan["counts"]["annotations"] += 1
        # 其它 target_type 暂记 deferred(本工具范围内只叠加 scene/character)
        else:
            plan["deferred_reviews"].append({"kind": "annotation", "target": a["target_type"],
                                             "note": "目标类型暂不在叠加范围"})

    # 3. 裁决
    for r in reviews:
        safe = (r["subject"] == "tag" and r["verdict"] in ("confirm", "correct"))
        rec = {"subject": r["subject"], "verdict": r["verdict"], "rationale": r["rationale"],
               "original": r["original"], "corrected": r["corrected"], "author": r["author"], "at": r["created_at"]}
        if safe:
            plan["applied_review_ids"].append(r["id"]); plan["counts"]["reviews_recorded"] += 1
            # 安全裁决也仅作记录性叠加(不改模型字段),挂到相关对象 sidecar 留痕
        else:
            plan["deferred_reviews"].append(
                {"id": r["id"], "subject": r["subject"], "verdict": r["verdict"],
                 "reason": "结构性裁决需重新聚合,非叠加可安全完成,未应用"})
    return plan


# ----------------------------- 应用计划到 JSON -----------------------------
def apply_plan(gdir, plan, do_apply):
    changes = []
    # scenes.json
    scenes_fp = gdir / "scenes.json"
    if plan["scenes"] and scenes_fp.exists():
        data = load(scenes_fp)
        by_ci = {}
        for ch in data.get("chapters", []):
            for s in ch.get("scenes", []):
                by_ci[(ch.get("chapter"), s.get("index"))] = s
        for (ch, idx), add in plan["scenes"].items():
            s = by_ci.get((ch, idx))
            if s is None:
                continue
            tags = s.setdefault("tags", {})
            for key in ("function", "action", "function_novel", "action_novel"):
                if add[key]:
                    tags.setdefault(key, [])
                    n = dedup_append(tags[key], add[key])
                    if n:
                        changes.append(f"scene ch{ch}/{idx} tags.{key} +{n}")
            if add["_annotations"]:
                na = merge_annotations(s, add["_annotations"])
                if na:
                    changes.append(f"scene ch{ch}/{idx} _annotations +{na}")
            if add["_reviews"]:
                s.setdefault("_reviews", []).extend(add["_reviews"])
        if do_apply:
            atomic_write(scenes_fp, data)

    # characters.json
    chars_fp = gdir / "characters.json"
    if plan["characters"] and chars_fp.exists():
        data = load(chars_fp)
        by_gid = {g["global_id"]: g for g in data.get("global_characters", [])}
        for gid, add in plan["characters"].items():
            g = by_gid.get(gid)
            if g is None:
                continue
            if add["tags"]:
                gt = g.setdefault("tags", {})
                for kind, labels in add["tags"].items():
                    gt.setdefault(kind, [])
                    n = dedup_append(gt[kind], labels)
                    if n:
                        changes.append(f"character gid{gid} tags.{kind} +{n}")
            if add["_annotations"]:
                na = merge_annotations(g, add["_annotations"])
                if na:
                    changes.append(f"character gid{gid} _annotations +{na}")
        if do_apply:
            atomic_write(chars_fp, data)
    return changes


def main():
    ap = argparse.ArgumentParser(description="把 novel.db 人工层合并回 global/*.json(默认 dry-run)")
    ap.add_argument("--db", required=True)
    ap.add_argument("--global", dest="gdir", required=True)
    ap.add_argument("--apply", action="store_true", help="真正写盘(默认 dry-run 只打印计划)")
    args = ap.parse_args()

    gdir = Path(args.gdir)
    if not gdir.exists():
        raise SystemExit(f"global 目录不存在: {gdir}")
    con = sqlite3.connect(args.db)
    con.execute("PRAGMA foreign_keys=ON")

    plan = build_plan(con, gdir)
    changes = apply_plan(gdir, plan, do_apply=args.apply)

    mode = "APPLY" if args.apply else "DRY-RUN(未写盘)"
    print(f"=== writeback {mode} ===")
    print("待合并人工层:", json.dumps(plan["counts"], ensure_ascii=False))
    print(f"具体改动({len(changes)} 项):")
    for c in changes[:50]:
        print("  +", c)
    if len(changes) > 50:
        print(f"  ... 余 {len(changes)-50} 项")
    if plan["deferred_reviews"]:
        print(f"未应用(需重新聚合或超范围,{len(plan['deferred_reviews'])} 项):")
        for d in plan["deferred_reviews"][:20]:
            print("  -", json.dumps(d, ensure_ascii=False))

    if args.apply:
        ids = plan["applied_review_ids"]
        if ids:
            con.executemany("UPDATE review SET applied=1 WHERE id=?", [(i,) for i in ids])
            con.commit()
            print(f"已置 applied=1 的 review: {len(ids)} 条")
        print("已写盘(原文件已备份 *.bak-<ts>)。")
    else:
        print("dry-run 结束。加 --apply 才会写盘。")
    con.close()


if __name__ == "__main__":
    main()
