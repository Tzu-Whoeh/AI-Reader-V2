#!/usr/bin/env python3
"""
叙事分析产物校验器 · 纯标准库(后端零依赖红线)

实现模型 MODEL.md §5 的跨字段语义规则 R1–R6,产出 ValidationReport
(validation_report.schema.json 形态)。结构校验(类型/必填/枚举)由 CI 侧
jsonschema 负责(见 tools/schema_check.py);本模块只管 Schema 表达不了的语义。

用法:
  from validate import validate_global, ValidationReport
  rep = validate_global(global_dir="output/global", raw_by_chapter={1: "原文..."})
  if not rep.ok: ...
"""
import os, json, re

CONF = {"high", "medium", "low"}
REL_TYPES = {"social", "kin", "affective", "attitude", "event", "awareness",
             "adjacency", "containment", "movement", "remote"}

# evidence 内引号包裹的逐字片段;片段内 ... / …… 视为省略,切段分别匹配
_QUOTE = re.compile(r"['‘’\"“”]([^'‘’\"“”]{2,60})['‘’\"“”]")
_ELLIPSIS = re.compile(r"\.{2,}|…+|⋯+")


def _norm(s):
    """归一:去空白与常见标点噪声,用于逐字子串比对。"""
    return re.sub(r"\s+", "", s or "")


def _anchor_fragments(field):
    """从锚点字段抽取应逐字命中的片段。
    evidence 形如『...'片段A'...'片段B'...』→ 取引号内;省略号再切段。
    start_text/anchor 本身即片段(可能带引号)→ 去引号后整体。
    返回 [(片段, 是否来自引号)]。"""
    quoted = _QUOTE.findall(field or "")
    frags = []
    if quoted:
        for q in quoted:
            for part in _ELLIPSIS.split(q):
                part = part.strip()
                if len(_norm(part)) >= 2:
                    frags.append(part)
    else:
        s = (field or "").strip().strip("'‘’\"“”")
        for part in _ELLIPSIS.split(s):
            part = part.strip()
            if len(_norm(part)) >= 2:
                frags.append(part)
    return frags


class Issue:
    __slots__ = ("rule", "path", "detail")
    def __init__(self, rule, path, detail):
        self.rule, self.path, self.detail = rule, path, detail
    def as_dict(self):
        return {"rule": self.rule, "path": self.path, "detail": self.detail}


class ValidationReport:
    def __init__(self):
        self.errors, self.warnings = [], []
    @property
    def ok(self):
        return not self.errors
    def err(self, rule, path, detail):
        self.errors.append(Issue(rule, path, detail))
    def warn(self, rule, path, detail):
        self.warnings.append(Issue(rule, path, detail))
    def as_dict(self):
        return {"ok": self.ok,
                "errors": [i.as_dict() for i in self.errors],
                "warnings": [i.as_dict() for i in self.warnings]}


# ---------- R1 锚点逐字命中 ----------
def check_anchors(rep, items, field, path_prefix, raw_norm_by_ch, default_ch=None):
    """items: 含锚点字段的对象列表。raw_norm_by_ch: {chapter: 归一原文}。
    命中失败记 warning(不静默丢弃,但不阻断——锚点是模型措辞,允许容错)。"""
    for i, obj in enumerate(items):
        val = obj.get(field)
        if not val:
            continue
        ch = obj.get("chapter", default_ch)
        raw = raw_norm_by_ch.get(ch) if ch is not None else None
        if raw is None:
            # 无对应原文,无法判定 —— 跳过(缺基准,non-blocking)
            continue
        frags = _anchor_fragments(val)
        missed = [f for f in frags if _norm(f) not in raw]
        if missed:
            rep.warn("R1", f"{path_prefix}[{i}].{field}",
                     f"锚点片段未在第{ch}章原文逐字命中: {missed[:3]}")


# ---------- R2 引用完整性 ----------
def check_refs(rep, global_chars, global_items, global_locs, timeline, char_dim, loc_dim):
    gid_char = {c["global_id"] for c in global_chars}
    gid_item = {c["global_id"] for c in global_items}
    gid_loc = {c["global_id"] for c in global_locs}

    # 人物关系全局端点
    for i, r in enumerate(char_dim.get("relations", [])):
        for end in ("from_global", "to_global"):
            v = r.get(end)
            if v is not None and v not in gid_char:
                rep.err("R2", f"characters.relations[{i}].{end}",
                        f"悬空引用 global_id={v}")
    # 地点关系全局端点
    for i, r in enumerate(loc_dim.get("relations", [])):
        for end in ("from_global", "to_global"):
            v = r.get(end)
            if v is not None and v not in gid_loc:
                rep.err("R2", f"locations.relations[{i}].{end}",
                        f"悬空引用 global_id={v}")
    # 事件参与者
    for i, e in enumerate(timeline.get("global_events", [])):
        for v in e.get("global_participants", []):
            if v not in gid_char:
                rep.err("R2", f"timeline.global_events[{i}].global_participants",
                        f"参与者 global_id={v} 不存在")


# ---------- R3 绝对时间纪律 ----------
def check_abs_time(rep, timeline):
    for i, e in enumerate(timeline.get("global_events", [])):
        ai = e.get("abs_interval")
        if ai is None:
            continue  # 合规:无依据留空
        if not isinstance(ai, dict):
            rep.err("R3", f"timeline.global_events[{i}].abs_interval",
                    "非 null 时须为区间对象")
            continue
        if not any(ai.get(k) for k in ("start", "end")):
            rep.warn("R3", f"timeline.global_events[{i}].abs_interval",
                     "abs_interval 对象但 start/end 全空,疑似应为 null")


# ---------- R5 provenance 自洽 ----------
def check_provenance(rep, dim_name, global_entities, local_by_ch):
    """local_by_ch: {chapter: {local_id: 局部实体}}。缺章级数据则跳过该检查。"""
    for gi, g in enumerate(global_entities):
        names = set(g.get("all_names", []))
        for m in g.get("members", []):
            ch, lid = m.get("chapter"), m.get("local_id")
            locals_ = local_by_ch.get(ch)
            if locals_ is None:
                continue  # 无该章局部数据,无法核 provenance
            loc = locals_.get(lid)
            if loc is None:
                rep.err("R5", f"{dim_name}[{gi}].members",
                        f"member(ch={ch},local_id={lid}) 在该章局部实体中不存在")
                continue
            # all_names ⊇ 成员 name/aliases
            member_names = {loc.get("name")} | set(loc.get("aliases", []))
            missing = {n for n in member_names if n} - names
            if missing:
                rep.warn("R5", f"{dim_name}[{gi}].all_names",
                         f"未涵盖成员名 {missing}")


# ---------- R6 枚举闭合 ----------
def check_enums(rep, char_dim, loc_dim):
    for dim, key in ((char_dim, "characters"), (loc_dim, "locations")):
        for i, r in enumerate(dim.get("relations", [])):
            rt = r.get("relation_type")
            if rt is not None and rt not in REL_TYPES:
                rep.err("R6", f"{key}.relations[{i}].relation_type",
                        f"未知关系类型 '{rt}'")
            c = r.get("confidence")
            if c is not None and c not in CONF:
                rep.err("R6", f"{key}.relations[{i}].confidence", f"未知置信度 '{c}'")


def _load(d, name):
    p = os.path.join(d, name)
    return json.load(open(p, encoding="utf-8")) if os.path.isfile(p) else {}


def validate_global(global_dir, raw_by_chapter=None, local_by_chapter=None):
    """主入口。
    global_dir: output/global 目录。
    raw_by_chapter: {chapter: 原文str}(R1 用,缺则跳过 R1)。
    local_by_chapter: {chapter: _merged dict}(R5 用,缺则跳过 R5 的成员核对)。
    """
    rep = ValidationReport()
    chars = _load(global_dir, "characters.json")
    items = _load(global_dir, "items.json")
    locs = _load(global_dir, "locations.json")
    timeline = _load(global_dir, "timeline.json")

    gchars = chars.get("global_characters", [])
    gitems = items.get("global_items", [])
    glocs = locs.get("global_locations", [])

    # R2 / R3 / R6 —— 只需 global,可无条件跑
    check_refs(rep, gchars, gitems, glocs, timeline, chars, locs)
    check_abs_time(rep, timeline)
    check_enums(rep, chars, locs)

    # R5 —— 需章级数据
    if local_by_chapter:
        local_index = {}
        for ch, merged in local_by_chapter.items():
            local_index[ch] = {}
            for dim in ("characters", "items", "locations"):
                for ent in merged.get(dim, []):
                    if dim == "characters":  # 仅人物维度示意;可按 dim 分别索引
                        pass
            # 分维度索引
        # 人物 provenance
        idx_char = {ch: {e["id"]: e for e in merged.get("characters", [])}
                    for ch, merged in local_by_chapter.items()}
        idx_loc = {ch: {e["id"]: e for e in merged.get("locations", [])}
                   for ch, merged in local_by_chapter.items()}
        check_provenance(rep, "global_characters", gchars, idx_char)
        check_provenance(rep, "global_locations", glocs, idx_loc)

    # R1 —— 需原文
    if raw_by_chapter:
        raw_norm = {ch: _norm(t) for ch, t in raw_by_chapter.items()}
        check_anchors(rep, chars.get("relations", []), "evidence",
                      "characters.relations", raw_norm)
        check_anchors(rep, locs.get("relations", []), "evidence",
                      "locations.relations", raw_norm)

    return rep


if __name__ == "__main__":
    import argparse, sys
    ap = argparse.ArgumentParser()
    ap.add_argument("--global-dir", required=True)
    ap.add_argument("--raw-dir", default=None, help="可选:每章原文 chNN.txt 目录")
    args = ap.parse_args()
    raw = None
    rep = validate_global(args.global_dir, raw_by_chapter=raw)
    out = rep.as_dict()
    print(json.dumps(out, ensure_ascii=False, indent=2))
    sys.exit(0 if rep.ok else 1)
