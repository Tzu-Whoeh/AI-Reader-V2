#!/usr/bin/env python3
"""
AI Reader (new-design) · 合并后端(单服务单端口)· 多小说库

统一提供:
  - 只读 API   /api/summary|graph|events|chapters|reader/<ch>|dimension/<name>|node/<type>/<id>
               读类支持 ?novel=<slug> 选择小说;省略则用最近上传的小说。
  - 库 API     /api/novels(列出所有小说)
  - 任务 API   /api/upload(txt/zip) | /api/analyze/<slug> | /api/progress/<slug>
  - 静态托管   / 与 /assets/*
全部挂在可配前缀 BASE_PATH 下。

数据布局(LIB 根下):
  raw/<slug>.txt 或 raw/<slug>/(zip 解压)
  input/<slug>/chNN.txt          拆章+清洗后的各章原文
  output/<slug>/meta.json        {novel_name, author, source_type, uploaded_at, stage, chapter_count}
  output/<slug>/chNN/            每章中间结果
  output/<slug>/global/          global 结果

运行:
  OLLAMA_URL=http://127.0.0.1:18434 python -m app.server.main \
      --lib <app目录> --base-path "" --port 8080
"""
import os, sys, json, re, time, zipfile, threading, argparse, unicodedata, shutil
from flask import Flask, request, jsonify, Response, send_from_directory

_HERE = os.path.dirname(os.path.abspath(__file__))
_APP = os.path.dirname(_HERE)
_ROOT = os.path.dirname(_APP)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from app.server import readonly as RO
from app.pipeline import rules as RULES

BASE_PATH = ""
STATIC_DIR = os.path.join(_HERE, "static")
LIB = _APP                       # 库根:其下 raw/ input/ output/
_RUNNING = set()                 # 正在分析的 slug

flask_app = Flask(__name__)

def _bp(rule): return (BASE_PATH + rule) if BASE_PATH else rule
def raw_dir():    return os.path.join(LIB, "raw")
def input_dir():  return os.path.join(LIB, "input")
def output_dir(): return os.path.join(LIB, "output")
def novel_out(slug):   return os.path.join(output_dir(), slug)
def novel_input(slug): return os.path.join(input_dir(), slug)

# ---------------- 工具 ----------------
def slugify(name):
    """安全化小说名做目录名:去扩展名,替换文件系统非法字符与空白。"""
    base = re.sub(r'\.(txt|zip)$', '', name, flags=re.I)
    base = unicodedata.normalize("NFKC", base).strip()
    base = re.sub(r'[\/\\:\*\?"<>\|]+', '_', base)   # 非法字符
    base = re.sub(r'\s+', '_', base)                  # 空白
    base = base.strip('_.') or "novel"
    return base[:80]

def read_meta(slug):
    p = os.path.join(novel_out(slug), "meta.json")
    if not os.path.isfile(p): return None
    try: return json.load(open(p, encoding="utf-8"))
    except Exception: return {}

def write_meta(slug, meta):
    os.makedirs(novel_out(slug), exist_ok=True)
    p = os.path.join(novel_out(slug), "meta.json"); tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f: json.dump(meta, f, ensure_ascii=False)
    os.replace(tmp, p)

def latest_novel_slug():
    """最近上传(uploaded_at 最大)的小说 slug;无则 None。"""
    novels = RO.list_novels()
    if not novels: return None
    novels.sort(key=lambda n: n.get("uploaded_at") or "", reverse=True)
    return novels[0]["slug"]

def _resolve_novel():
    """读类端点解析 ?novel=,缺省取最近上传。"""
    return request.args.get("novel") or latest_novel_slug()

# ---------------- 只读 API(支持 ?novel=) ----------------
def register_readonly():
    app = flask_app
    @app.get(_bp("/api/summary"))
    def summary():
        with RO.use_novel(_resolve_novel()):
            c = {"characters": len(RO.GLOBALS.get("characters", {}).get("global_characters", [])),
                 "items": len(RO.GLOBALS.get("items", {}).get("global_items", [])),
                 "locations": len(RO.GLOBALS.get("locations", {}).get("global_locations", [])),
                 "organizations": len(RO.GLOBALS.get("organizations", {}).get("global_organizations", [])),
                 "events": len(RO.GLOBALS.get("timeline", {}).get("global_events", []))}
            return jsonify({"chapters": [m["_chapter"] for m in RO.CHAPTERS], "counts": c})

    @app.get(_bp("/api/graph"))
    def graph():
        with RO.use_novel(_resolve_novel()):
            return jsonify(RO.build_graph())

    @app.get(_bp("/api/events"))
    def events():
        with RO.use_novel(_resolve_novel()):
            return jsonify(RO.build_events())

    @app.get(_bp("/api/chapters"))
    def chapters():
        with RO.use_novel(_resolve_novel()):
            return jsonify({"chapters": sorted(RO.RAW.keys())})

    @app.get(_bp("/api/reader/<int:ch>"))
    def reader(ch):
        with RO.use_novel(_resolve_novel()):
            return jsonify(RO.build_reader(ch))

    @app.get(_bp("/api/dimension/<name>"))
    def dimension(name):
        with RO.use_novel(_resolve_novel()):
            d = RO.GLOBALS.get(name)
            if d is None: return jsonify({"error": "无此维度"}), 404
            return jsonify(d)

    @app.get(_bp("/api/node/<ntype>/<nid>"))
    def node(ntype, nid):
        try: nid_v = int(nid)
        except (TypeError, ValueError): nid_v = nid
        with RO.use_novel(_resolve_novel()):
            anchors = RO.node_anchors(ntype, nid_v)
            return jsonify({"type": ntype, "id": nid_v, "anchors": anchors,
                            "occurrences": RO.find_occurrences([a for a in anchors if a])})

    @app.get(_bp("/api/novels"))
    def novels():
        nv = RO.list_novels()
        for n in nv:
            m = read_meta(n.get("slug"))
            n["dirty"] = _is_dirty(n.get("slug"), m)
            if m:
                for k in ("tags", "cover", "rules_selected", "partial_reason", "error_count", "first_error"):
                    if k in m: n[k] = m[k]
        return jsonify({"novels": nv, "current": latest_novel_slug()})

# ---------------- 任务 API ----------------
def _set_stage(slug, **kw):
    meta = read_meta(slug) or {}
    meta.update(kw)
    write_meta(slug, meta)

def _split_to_input(slug, selected_ids=None):
    """把 raw/<slug>(.txt 或目录) 的所有文本逐个清洗+拆章,汇总重排成 input/<slug>/chNN.txt。
    返回章数。"""
    _pp = os.path.join(_APP, "pipeline")
    if _pp not in sys.path: sys.path.append(_pp)
    import clean_split as CS
    noise_pats, chap_pats = RULES.resolve_enabled(selected_ids)
    # 收集原文文件
    texts = []
    raw_txt = os.path.join(raw_dir(), slug + ".txt")
    raw_sub = os.path.join(raw_dir(), slug)
    if os.path.isfile(raw_txt):
        texts.append(open(raw_txt, encoding="utf-8", errors="replace").read())
    elif os.path.isdir(raw_sub):
        files = []
        for root, _, fns in os.walk(raw_sub):
            for fn in fns:
                if fn.lower().endswith(".txt"):
                    files.append(os.path.join(root, fn))
        files.sort()  # 文件名自然排序
        for fp in files:
            texts.append(open(fp, encoding="utf-8", errors="replace").read())
    # 逐个清洗 + 拆章,汇总
    chapters = []
    for t in texts:
        cleaned, _ = CS.clean(t, noise_patterns=(noise_pats or None))
        for ch in CS.split_chapters(cleaned, patterns=(chap_pats or None)):
            chapters.append(ch)
    # 写 input/<slug>/chNN.txt(全局重排)
    idir = novel_input(slug)
    os.makedirs(idir, exist_ok=True)
    for i, ch in enumerate(chapters, 1):
        open(os.path.join(idir, f"ch{i:02d}.txt"), "w", encoding="utf-8").write(ch["text"])
    return len(chapters)

def _run_analysis(slug):
    _pp = os.path.join(_APP, "pipeline")
    if _pp not in sys.path: sys.path.append(_pp)
    from app.pipeline import app as pipeline
    out = novel_out(slug)
    try:
        _set_stage(slug, stage="splitting", control="go")
        meta0 = read_meta(slug) or {}
        sel = meta0.get("rules_selected")  # None → 全局默认
        n = _split_to_input(slug, sel)
        _set_stage(slug, stage="analyzing", chapter_count=n, done=0, total=n, chapters=[])
        meta = read_meta(slug)
        def control():
            # 读盘取最新 control(允许外部端点改写),返回 go|pause|stop
            cur = read_meta(slug) or {}
            return cur.get("control", "go")
        def cb(ev):
            st = ev.get("stage")
            if st == "paused":
                meta["stage"] = "paused"; meta["done"] = ev.get("done", meta.get("done", 0)); write_meta(slug, meta); return
            if st == "stopping":
                meta["stage"] = "stopping"; write_meta(slug, meta); return
            if st == "split": meta["total"] = ev.get("total", 0); meta["stage"] = "analyzing"
            elif st == "step":
                meta["stage"] = "analyzing"; meta["cur_chapter"] = ev.get("chapter")
                meta["step"] = ev.get("step"); meta["step_name"] = ev.get("step_name")
                meta["step_idx"] = ev.get("step_idx"); meta["step_total"] = ev.get("step_total")
            elif st == "chapter":
                meta["done"] = ev.get("done", meta.get("done", 0))
                meta["step"] = None; meta["step_name"] = None
                meta.setdefault("chapters", []).append({k: ev.get(k) for k in
                    ("chapter", "title", "scenes", "characters", "events", "skipped") if k in ev})
            elif st == "chapter_error":
                meta.setdefault("chapters", []).append({"chapter": ev.get("chapter"), "error": ev.get("error")})
            elif st == "aggregate": meta["stage"] = "aggregating"
            elif st == "done":
                meta["stage"] = "done"; meta["counts"] = ev.get("counts", {})
                meta["clean_fingerprint"] = RULES.fingerprint(meta.get("rules_selected"))
            write_meta(slug, meta)
        # presplit:input/<slug>/ 下已是 chNN.txt
        pipeline.run(novel_input(slug), out_dir=out, presplit=True, progress_cb=cb, should_continue=control)
        # 完结判定:逐章错误隔离会让 pipeline 即使大量失败也"跑完"并发 done。
        # 这里据实复核 —— 有章节失败或未跑满则标 partial,不再一律 done。
        m = read_meta(slug)
        chs = m.get("chapters", []) or []
        errored = [c for c in chs if c.get("error")]
        succeeded = [c for c in chs if not c.get("error")]
        total = m.get("total", 0) or 0
        accounted = len(chs)
        if errored or (total and accounted < total):
            m["stage"] = "partial"
            m["error_count"] = len(errored)
            m["succeeded_count"] = len(succeeded)
            # 给个可读摘要:多少章成功/失败/未跑
            not_run = max(0, total - accounted)
            m["partial_reason"] = (
                f"成功 {len(succeeded)} 章、失败 {len(errored)} 章" +
                (f"、未跑 {not_run} 章" if not_run else "") +
                (f";首个错误:{errored[0].get('error')}" if errored else ""))
            # 记录代表性错误(便于排查隧道/超时等)
            if errored:
                m["first_error"] = errored[0].get("error")
            write_meta(slug, m)
        elif m.get("stage") != "done":
            m["stage"] = "done"; write_meta(slug, m)
    except Exception as e:
        _set_stage(slug, stage="error", error=str(e))
    finally:
        _RUNNING.discard(slug)

def register_tasks():
    app = flask_app
    @app.post(_bp("/api/upload"))
    def upload():
        if "file" not in request.files:
            return jsonify({"error": "需要上传文件(txt 或 zip)"}), 400
        f = request.files["file"]
        fname = f.filename or "novel.txt"
        low = fname.lower()
        if not (low.endswith(".txt") or low.endswith(".zip")):
            return jsonify({"error": "仅支持 .txt 或 .zip"}), 400
        slug = slugify(fname)
        # 重传同名报错
        if os.path.isdir(novel_out(slug)):
            return jsonify({"error": f"小说「{slug}」已存在", "slug": slug}), 409
        os.makedirs(raw_dir(), exist_ok=True)
        novel_name = re.sub(r'\.(txt|zip)$', '', fname, flags=re.I)
        src = "txt"
        if low.endswith(".txt"):
            data = f.read()
            open(os.path.join(raw_dir(), slug + ".txt"), "wb").write(data)
        else:
            src = "zip"
            zpath = os.path.join(raw_dir(), slug + ".zip")
            f.save(zpath)
            dest = os.path.join(raw_dir(), slug)
            os.makedirs(dest, exist_ok=True)
            try:
                with zipfile.ZipFile(zpath) as z:
                    for nm in z.namelist():
                        # 防 zip-slip:跳过绝对路径/上跳
                        if nm.startswith("/") or ".." in nm.split("/"): continue
                        if nm.endswith("/"): continue
                        if not nm.lower().endswith(".txt"): continue
                        target = os.path.join(dest, os.path.basename(nm))
                        with z.open(nm) as srcf, open(target, "wb") as outf:
                            outf.write(srcf.read())
            except zipfile.BadZipFile:
                return jsonify({"error": "无效 zip"}), 400
            finally:
                if os.path.exists(zpath): os.remove(zpath)
        write_meta(slug, {"novel_name": novel_name, "author": None, "source_type": src,
                          "uploaded_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                          "stage": "uploaded", "chapter_count": 0})
        return jsonify({"slug": slug, "novel_name": novel_name, "source_type": src})

    @app.post(_bp("/api/analyze/<slug>"))
    def analyze(slug):
        if read_meta(slug) is None:
            return jsonify({"error": "小说不存在"}), 404
        if slug in _RUNNING:
            return jsonify({"started": False, "reason": "已在运行"}), 409
        _RUNNING.add(slug)
        threading.Thread(target=_run_analysis, args=(slug,), daemon=True).start()
        return jsonify({"started": True, "slug": slug})

    @app.get(_bp("/api/progress/<slug>"))
    def progress(slug):
        meta = read_meta(slug)
        if meta is None: return jsonify({"error": "小说不存在"}), 404
        meta["running"] = slug in _RUNNING
        return jsonify(meta)

    def _set_control(slug, value):
        meta = read_meta(slug)
        if meta is None: return None
        if slug not in _RUNNING:
            return jsonify({"error": "该小说当前未在分析", "stage": meta.get("stage")}), 409
        meta["control"] = value
        write_meta(slug, meta)
        return jsonify({"ok": True, "slug": slug, "control": value})

    @app.post(_bp("/api/pause/<slug>"))
    def pause(slug):
        # 章间软停:置 control=pause,run 在下一章前阻塞
        r = _set_control(slug, "pause")
        return r if r is not None else (jsonify({"error": "小说不存在"}), 404)

    @app.post(_bp("/api/resume/<slug>"))
    def resume(slug):
        r = _set_control(slug, "go")
        return r if r is not None else (jsonify({"error": "小说不存在"}), 404)

    @app.post(_bp("/api/stop/<slug>"))
    def stop(slug):
        # 停止后续章,run 会对已完成部分聚合后结束(结果通常为 partial)
        r = _set_control(slug, "stop")
        return r if r is not None else (jsonify({"error": "小说不存在"}), 404)


# ---------------- 书库管理 API(规则 / meta / 删除 / 重新清洗) ----------------
def _is_dirty(slug, meta):
    """书已分析,但当前勾选规则指纹 != 分析时记录的指纹 → 脏(建议重新分析)。"""
    if not meta or meta.get("stage") != "done":
        return False
    recorded = meta.get("clean_fingerprint")
    if not recorded:
        return False
    return RULES.fingerprint(meta.get("rules_selected")) != recorded

def register_library_admin():
    app = flask_app

    @app.get(_bp("/api/rules"))
    def rules_get():
        return jsonify({
            "presets": [r for r in RULES.load_presets()],
            "custom": RULES.load_custom().get("rules", []),
            "user_presets": RULES.load_custom().get("presets", []),
            "default_enabled": RULES.load_default_enabled(),
        })

    @app.post(_bp("/api/rules/custom"))
    def rules_custom():
        """body: {op:'add'|'update'|'delete', rule:{id,kind,name,pattern,desc}}"""
        body = request.get_json(force=True, silent=True) or {}
        op = body.get("op"); rule = body.get("rule") or {}
        c = RULES.load_custom()
        rid = rule.get("id")
        builtin_ids = {r["id"] for r in RULES.load_presets()}
        if op in ("add", "update"):
            if not rid or rule.get("kind") not in ("noise", "chapter") or not rule.get("pattern"):
                return jsonify({"error": "需要 id/kind/pattern"}), 400
            if rid in builtin_ids:
                return jsonify({"error": "不可覆盖预制规则 id"}), 400
            try:
                re.compile(rule["pattern"])
            except re.error as e:
                return jsonify({"error": f"正则无效: {e}"}), 400
            c["rules"] = [r for r in c["rules"] if r.get("id") != rid]
            c["rules"].append({"id": rid, "kind": rule["kind"], "name": rule.get("name", rid),
                               "pattern": rule["pattern"], "desc": rule.get("desc", ""), "builtin": False})
        elif op == "delete":
            c["rules"] = [r for r in c["rules"] if r.get("id") != rid]
        else:
            return jsonify({"error": "op 必须是 add/update/delete"}), 400
        RULES.save_custom(c)
        return jsonify({"ok": True, "custom": c["rules"]})

    @app.put(_bp("/api/rules/default"))
    def rules_default():
        body = request.get_json(force=True, silent=True) or {}
        ids = body.get("enabled")
        if not isinstance(ids, list):
            return jsonify({"error": "需要 enabled:[id...]"}), 400
        RULES.save_default_enabled(ids)
        return jsonify({"ok": True, "default_enabled": ids})

    @app.post(_bp("/api/rules/presets"))
    def rules_user_presets():
        """存/删用户预设。body: {op:'save'|'delete', name, enabled:[id...]}"""
        body = request.get_json(force=True, silent=True) or {}
        op = body.get("op"); name = (body.get("name") or "").strip()
        c = RULES.load_custom()
        if op == "save":
            if not name:
                return jsonify({"error": "需要 name"}), 400
            c["presets"] = [p for p in c["presets"] if p.get("name") != name]
            c["presets"].append({"name": name, "enabled": body.get("enabled", [])})
        elif op == "delete":
            c["presets"] = [p for p in c["presets"] if p.get("name") != name]
        else:
            return jsonify({"error": "op 必须是 save/delete"}), 400
        RULES.save_custom(c)
        return jsonify({"ok": True, "user_presets": c["presets"]})

    @app.put(_bp("/api/novels/<slug>/meta"))
    def novel_meta_update(slug):
        meta = read_meta(slug)
        if meta is None:
            return jsonify({"error": "小说不存在"}), 404
        body = request.get_json(force=True, silent=True) or {}
        for k in ("novel_name", "author", "cover"):
            if k in body:
                meta[k] = body[k]
        if "tags" in body and isinstance(body["tags"], list):
            meta["tags"] = body["tags"]
        if "rules_selected" in body:
            v = body["rules_selected"]
            meta["rules_selected"] = list(v) if isinstance(v, list) else None
        write_meta(slug, meta)
        meta["dirty"] = _is_dirty(slug, meta)
        return jsonify({"ok": True, "meta": meta})

    @app.delete(_bp("/api/novels/<slug>"))
    def novel_delete(slug):
        if read_meta(slug) is None:
            return jsonify({"error": "小说不存在"}), 404
        if slug in _RUNNING:
            return jsonify({"error": "分析进行中,无法删除"}), 409
        for p in (novel_out(slug), novel_input(slug),
                  os.path.join(raw_dir(), slug), os.path.join(raw_dir(), slug + ".txt")):
            try:
                if os.path.isdir(p): shutil.rmtree(p)
                elif os.path.isfile(p): os.remove(p)
            except Exception:
                pass
        return jsonify({"ok": True, "deleted": slug})

    @app.post(_bp("/api/reclean/<slug>"))
    def reclean(slug):
        """用该书当前勾选规则重跑 清洗+拆章 → 重排 input(不分析)。"""
        meta = read_meta(slug)
        if meta is None:
            return jsonify({"error": "小说不存在"}), 404
        if slug in _RUNNING:
            return jsonify({"error": "分析进行中"}), 409
        try:
            idir = novel_input(slug)
            if os.path.isdir(idir):
                shutil.rmtree(idir)
            n = _split_to_input(slug, meta.get("rules_selected"))
            meta["chapter_count"] = n
            meta["recleaned_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            write_meta(slug, meta)
            return jsonify({"ok": True, "chapter_count": n, "dirty": _is_dirty(slug, meta)})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

# ---------------- 静态托管 ----------------
def register_static():
    app = flask_app
    @app.get(_bp("/") if BASE_PATH else "/")
    def index():
        idx = os.path.join(STATIC_DIR, "index.html")
        if os.path.isfile(idx): return send_from_directory(STATIC_DIR, "index.html")
        return Response(RO.FRONTEND, mimetype="text/html")
    @app.get(_bp("/assets/<path:fn>"))
    def assets(fn): return send_from_directory(os.path.join(STATIC_DIR, "assets"), fn)

def create_app(lib=None, base_path="", static=None):
    global BASE_PATH, STATIC_DIR, LIB
    BASE_PATH = base_path.rstrip("/")
    if static: STATIC_DIR = static
    if lib: LIB = lib
    os.makedirs(raw_dir(), exist_ok=True)
    os.makedirs(input_dir(), exist_ok=True)
    os.makedirs(output_dir(), exist_ok=True)
    RO.set_library(LIB)
    RULES.set_library(LIB)
    register_readonly(); register_tasks(); register_library_admin(); register_static()
    return flask_app

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--lib", default=None, help="库根目录(其下 raw/ input/ output/)")
    ap.add_argument("--base-path", default="")
    ap.add_argument("--static", default=None)
    ap.add_argument("--port", type=int, default=8080)
    args = ap.parse_args()
    app = create_app(args.lib, args.base_path, args.static)
    print(f"库根: {LIB}")
    print(f"小说数: {len(RO.list_novels())}")
    print(f"前端: {'Vite产物 '+STATIC_DIR if os.path.isfile(os.path.join(STATIC_DIR,'index.html')) else '内嵌回退'}")
    print(f"OLLAMA_URL={os.environ.get('OLLAMA_URL','(默认 18434)')}")
    print(f"服务: http://127.0.0.1:{args.port}{BASE_PATH or '/'}")
    app.run(host="127.0.0.1", port=args.port, threaded=True)