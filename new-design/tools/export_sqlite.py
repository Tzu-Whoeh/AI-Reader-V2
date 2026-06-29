#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""export_sqlite.py — 把 output/<slug>/global/*.json 导出为 novel.db(SQLite)。

定位:旁路只读副本 + 可写人工层的【模型部分】。文件 JSON 仍是单一真相源;本工具只读 JSON、
单向写 DB,不回写、不作为分析输入。重复运行幂等:wipe 所有 source='model' 标签与各模型表后重灌,
绝不删 source='human' 行 / annotation / 未应用的 review(可写人工层得以保留)。

Schema 来源:spec/architecture/schema.sql(与本工具同仓库);不内嵌 DDL,保持单一真相源。

用法:
  python3 export_sqlite.py --global <output/slug/global> [--out novel.db] [--schema <schema.sql>]
                            [--raw-dir <input/slug>] [--slug NAME] [--novel-name NAME]
仅标准库(json/sqlite3/argparse/pathlib),无三方依赖。
"""
import argparse, json, sqlite3, sys, os, glob
from pathlib import Path

# 各模型表:重导出时先清空再重灌(人工层 annotation/review 及 tag.source='human' 不在此列)
MODEL_TABLES = [
    "entity", "entity_name", "entity_member", "item_location", "org_membership",
    "relation", "scene", "scene_character", "event", "event_participant",
    "character_timeline", "sync_point", "sync_point_participant", "time_expression",
    "ambiguity", "chapter",
]


def load_json(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def find_schema(explicit):
    if explicit:
        return Path(explicit)
    # 同仓库 spec 路径:tools/../spec/architecture/schema.sql
    here = Path(__file__).resolve().parent
    for cand in [here.parent / "spec" / "architecture" / "schema.sql",
                 here / "schema.sql"]:
        if cand.exists():
            return cand
    raise SystemExit("找不到 schema.sql,请用 --schema 指定")


def ensure_schema(con, schema_path):
    have = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    if "entity" not in have:
        con.executescript(Path(schema_path).read_text(encoding="utf-8"))


def wipe_model(con):
    con.execute("DELETE FROM tag WHERE source='model'")
    for t in MODEL_TABLES:
        con.execute(f"DELETE FROM {t}")
    # 重置自增,保持可重复导出 id 稳定(仅对被清空的表)
    con.execute("DELETE FROM sqlite_sequence WHERE name IN (%s)"
                % ",".join("?" * len(MODEL_TABLES + ["tag", "relation", "scene", "event"])),
                MODEL_TABLES + ["tag", "relation", "scene", "event"])


# ---------- 维度导出 ----------
def export_entities(con, gdir):
    """characters/items/locations/organizations → entity + entity_name + entity_member。
    返回 {(type,global_id): entity_pk} 备用(此处用 UNIQUE(type,global_id) 直接回查,无需缓存)。"""
    files = {
        "character": ("characters.json", "global_characters"),
        "item": ("items.json", "global_items"),
        "location": ("locations.json", "global_locations"),
        "organization": ("organizations.json", "global_organizations"),
    }
    n_ent = 0
    for etype, (fname, key) in files.items():
        fp = gdir / fname
        if not fp.exists():
            continue
        data = load_json(fp)
        for g in data.get(key, []):
            gid = g["global_id"]
            canonical = g.get("canonical") or (g.get("all_names") or [""])[0]
            extra = {k: g[k] for k in g
                     if k not in ("global_id", "canonical", "all_names", "members",
                                  "role", "category", "scale", "confidence")}
            con.execute(
                "INSERT INTO entity(type,global_id,canonical,role,category,scale,confidence,extra_json)"
                " VALUES(?,?,?,?,?,?,?,?)",
                (etype, gid, canonical, g.get("role"), g.get("category"),
                 g.get("scale"), g.get("confidence"),
                 json.dumps(extra, ensure_ascii=False) if extra else None))
            eid = con.execute("SELECT id FROM entity WHERE type=? AND global_id=?",
                              (etype, gid)).fetchone()[0]
            names = list(dict.fromkeys(g.get("all_names") or ([canonical] if canonical else [])))
            for nm in names:
                con.execute(
                    "INSERT OR IGNORE INTO entity_name(entity_id,name,is_canonical) VALUES(?,?,?)",
                    (eid, nm, 1 if nm == canonical else 0))
            seen = set()
            for m in g.get("members", []):
                key2 = (m.get("chapter"), m.get("local_id"))
                if None in key2 or key2 in seen:
                    continue
                seen.add(key2)
                con.execute(
                    "INSERT OR IGNORE INTO entity_member(entity_id,chapter,local_id) VALUES(?,?,?)",
                    (eid, key2[0], key2[1]))
            n_ent += 1
    return n_ent


def export_relations(con, gdir):
    n = 0
    for dim, fname in [("character", "characters.json"),
                       ("location", "locations.json"),
                       ("organization", "organizations.json")]:
        fp = gdir / fname
        if not fp.exists():
            continue
        for r in load_json(fp).get("relations", []):
            con.execute(
                "INSERT INTO relation(dimension,from_global,to_global,relation_type,label,evidence,confidence,chapter)"
                " VALUES(?,?,?,?,?,?,?,?)",
                (dim, r.get("from_global"), r.get("to_global"),
                 r.get("relation_type") or "social",   # 组织关系无 relation_type,缺省 social
                 r.get("label") or "", r.get("evidence"),
                 r.get("confidence"), r.get("chapter")))
            n += 1
    return n


def export_item_locations(con, gdir):
    fp = gdir / "items.json"
    if not fp.exists():
        return 0
    il = load_json(fp).get("item_locations", {})
    n = 0
    for item_gid, recs in il.items():
        eid = con.execute("SELECT id FROM entity WHERE type='item' AND global_id=?",
                          (int(item_gid),)).fetchone()
        if not eid:
            continue
        for rec in (recs if isinstance(recs, list) else [recs]):
            if not isinstance(rec, dict):
                continue
            con.execute(
                "INSERT INTO item_location(item_entity_id,chapter,location_global_id,location_name,via_scene)"
                " VALUES(?,?,?,?,?)",
                (eid[0], rec.get("chapter"), rec.get("location_global") or rec.get("location_id"),
                 rec.get("location_name") or rec.get("location"), rec.get("scene") or rec.get("via_scene")))
            n += 1
    return n


def export_memberships(con, gdir):
    fp = gdir / "organizations.json"
    if not fp.exists():
        return 0
    n = 0
    for m in load_json(fp).get("memberships", []):
        con.execute(
            "INSERT OR IGNORE INTO org_membership(org_global_id,character_global_id,role,chapter,anchor_text,source)"
            " VALUES(?,?,?,?,?,?)",
            (m.get("org_global"), m.get("character_global"), m.get("role") or "",
             m.get("chapter"), m.get("anchor_text"),
             m.get("source") if m.get("source") in ("explicit", "inferred") else None))
        n += 1
    return n


def export_scenes(con, gdir):
    """scenes.json::chapters[].scenes[] → scene + scene_character + tag(function/action)。"""
    fp = gdir / "scenes.json"
    if not fp.exists():
        return 0, 0
    n_sc = n_tag = 0
    name2gid = {}  # 人物名 → global_id(供 scene 参与人物解析)
    for nm, gid in con.execute(
            "SELECT en.name, e.global_id FROM entity e JOIN entity_name en ON en.entity_id=e.id"
            " WHERE e.type='character'"):
        name2gid.setdefault(nm, gid)
    for ch in load_json(fp).get("chapters", []):
        chapter = ch.get("chapter")
        con.execute("INSERT OR IGNORE INTO chapter(chapter) VALUES(?)", (chapter,))
        for s in ch.get("scenes", []):
            lref = s.get("location_ref") or {}
            con.execute(
                "INSERT OR IGNORE INTO scene(chapter,scene_index,title,type,location_name,location_global_id,summary,start_text,end_text)"
                " VALUES(?,?,?,?,?,?,?,?,?)",
                (chapter, s.get("index"), s.get("title"), s.get("type"),
                 s.get("location"), lref.get("location_id"),
                 s.get("summary"), s.get("start_text"), s.get("end_text")))
            sid = con.execute("SELECT id FROM scene WHERE chapter=? AND scene_index=?",
                              (chapter, s.get("index"))).fetchone()[0]
            n_sc += 1
            tags = s.get("tags") or {}
            # 参与人物(tags.characters 是名字列表)
            for nm in tags.get("characters", []) or []:
                gid = name2gid.get(nm)
                if gid is not None:
                    con.execute("INSERT OR IGNORE INTO scene_character(scene_id,character_global_id) VALUES(?,?)",
                                (sid, gid))
            # 场景标签:function/action,清单内 in_catalog=1,*_novel 为清单外 in_catalog=0
            for kind, novel_key in (("function", "function_novel"), ("action", "action_novel")):
                for rank, label in enumerate(tags.get(kind, []) or [], start=1):
                    con.execute(
                        "INSERT OR IGNORE INTO tag(target_type,target_id,kind,label,in_catalog,rank,source)"
                        " VALUES('scene',?,?,?,1,?, 'model')", (sid, kind, label, rank))
                    n_tag += 1
                for label in tags.get(novel_key, []) or []:
                    con.execute(
                        "INSERT OR IGNORE INTO tag(target_type,target_id,kind,label,in_catalog,rank,source)"
                        " VALUES('scene',?,?,?,0,NULL,'model')", (sid, kind, label))
                    n_tag += 1
    return n_sc, n_tag


def export_timeline(con, gdir):
    fp = gdir / "timeline.json"
    if not fp.exists():
        return 0
    tl = load_json(fp)
    n_ev = 0
    for ev in tl.get("global_events", []):
        eid = ev.get("global_seq")
        if eid is None:
            continue
        ai = ev.get("abs_interval") or {}
        if not isinstance(ai, dict):
            ai = {}
        con.execute(
            "INSERT OR IGNORE INTO event(event_id,chapter,description,narrative_order,story_order,is_flashback,storyline,abs_start,abs_end,abs_granularity,confidence)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (eid, ev.get("chapter"), ev.get("desc") or ev.get("description") or "",
             ev.get("narrative_order"), ev.get("story_order"),
             1 if ev.get("is_flashback") else 0, ev.get("storyline"),
             ai.get("start"), ai.get("end"), ai.get("granularity"), ev.get("confidence")))
        for gp in ev.get("global_participants", []) or []:
            con.execute("INSERT OR IGNORE INTO event_participant(event_id,character_global_id) VALUES(?,?)",
                        (eid, gp))
        n_ev += 1
    # 个人时间线(按 char global_id 字符串键)
    for cgid, entries in (tl.get("character_timelines") or {}).items():
        for e in entries:
            con.execute(
                "INSERT OR IGNORE INTO character_timeline(character_global_id,seq,event_id,chapter,description,is_flashback)"
                " VALUES(?,?,?,?,?,?)",
                (int(cgid), e.get("seq"), e.get("global_seq"), e.get("chapter"),
                 e.get("title") or e.get("description"),
                 1 if e.get("is_flashback") else (0 if "is_flashback" in e else None)))
    # 交汇点
    for sp in tl.get("sync_points", []):
        eid = sp.get("global_seq")
        if eid is None:
            continue
        con.execute("INSERT OR IGNORE INTO sync_point(event_id,chapter,description) VALUES(?,?,?)",
                    (eid, sp.get("chapter"), sp.get("title")))
        for gp in sp.get("global_participants", []) or []:
            con.execute("INSERT OR IGNORE INTO sync_point_participant(event_id,character_global_id) VALUES(?,?)",
                        (eid, gp))
    return n_ev


def export_ambiguities(con, gdir):
    n = 0
    src = [("character", "characters.json", "ambiguities"),
           ("item", "items.json", "ambiguities"),
           ("location", "locations.json", "ambiguities"),
           ("organization", "organizations.json", "ambiguities")]
    for dim, fname, key in src:
        fp = gdir / fname
        if not fp.exists():
            continue
        for a in load_json(fp).get(key, []):
            con.execute(
                "INSERT INTO ambiguity(dimension,reason,chapter_a,name_a,chapter_b,name_b,overlap_json)"
                " VALUES(?,?,?,?,?,?,?)",
                (dim, a.get("reason") or "",
                 a.get("chapterA") or a.get("chapter_a"), a.get("nameA") or a.get("name_a"),
                 a.get("chapterB") or a.get("chapter_b"), a.get("nameB") or a.get("name_b"),
                 json.dumps(a.get("overlap"), ensure_ascii=False) if a.get("overlap") is not None else None))
            n += 1
    return n


def export_meta(con, gdir, slug, novel_name):
    idx = {}
    if (gdir / "_index.json").exists():
        idx = load_json(gdir / "_index.json")
    chapters = idx.get("chapters") or []
    con.execute("INSERT OR REPLACE INTO novel(id,slug,novel_name,chapter_count) VALUES(1,?,?,?)",
                (slug, novel_name or slug, len(chapters) if isinstance(chapters, list) else None))
    for c in (chapters if isinstance(chapters, list) else []):
        if isinstance(c, int):
            con.execute("INSERT OR IGNORE INTO chapter(chapter) VALUES(?)", (c,))


def main():
    ap = argparse.ArgumentParser(description="导出 global/*.json → SQLite novel.db")
    ap.add_argument("--global", dest="gdir", required=True, help="output/<slug>/global 目录")
    ap.add_argument("--out", default="novel.db")
    ap.add_argument("--schema", default=None)
    ap.add_argument("--slug", default=None)
    ap.add_argument("--novel-name", default=None)
    args = ap.parse_args()

    gdir = Path(args.gdir)
    if not gdir.exists():
        raise SystemExit(f"global 目录不存在: {gdir}")
    slug = args.slug or gdir.parent.name

    con = sqlite3.connect(args.out)
    con.execute("PRAGMA foreign_keys=ON")
    ensure_schema(con, find_schema(args.schema))
    wipe_model(con)

    export_meta(con, gdir, slug, args.novel_name)
    counts = {}
    counts["entity"] = export_entities(con, gdir)
    counts["relation"] = export_relations(con, gdir)
    counts["item_location"] = export_item_locations(con, gdir)
    counts["membership"] = export_memberships(con, gdir)
    sc, tg = export_scenes(con, gdir)
    counts["scene"] = sc
    counts["tag"] = tg
    counts["event"] = export_timeline(con, gdir)
    counts["ambiguity"] = export_ambiguities(con, gdir)
    con.commit()

    print("导出完成 →", args.out)
    for k, v in counts.items():
        print(f"  {k}: {v}")
    # 完整性自检:relation 引用的 global_id 是否都在 entity 内(仅报告,不阻断)
    dangling = con.execute(
        "SELECT COUNT(*) FROM relation r WHERE r.from_global IS NOT NULL"
        " AND NOT EXISTS (SELECT 1 FROM entity e WHERE e.type=r.dimension AND e.global_id=r.from_global)"
    ).fetchone()[0]
    print(f"  [check] relation.from_global 悬空数: {dangling}")
    con.close()


if __name__ == "__main__":
    main()
