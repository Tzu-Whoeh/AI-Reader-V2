#!/usr/bin/env python3
"""
AI Reader (new-design) · 合并后端(单服务单端口)

3B 收口:把原 server.py(只读 API,纯标准库)与 tasks.py(分析任务层,Flask)合并为
一个 Flask 应用,统一提供:
  - 只读 API   /api/summary|graph|events|chapters|reader/<ch>|dimension/<name>|node/<type>/<id>
  - 任务 API   /api/upload | /api/analyze/<job> | /api/progress/<job> | /api/jobs
  - 静态托管   /  与  /assets/*(Vite 产物 server/static/)
全部挂在可配前缀 BASE_PATH 下(开发 /new,迁顶层留空)。

运行:
  OLLAMA_URL=http://127.0.0.1:18434 python -m app.server.main \
      --output output --raw raw --jobs jobs --base-path /new --port 8080
"""
import os, sys, json, uuid, threading, argparse
from flask import Flask, request, jsonify, Response, send_from_directory

_HERE = os.path.dirname(os.path.abspath(__file__))
_APP = os.path.dirname(_HERE)            # app/
_ROOT = os.path.dirname(_APP)            # new-design/ (so 'app' package importable)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from app.server import readonly as RO     # 只读逻辑(同包)
# pipeline analysis 模块之间用相对/裸名互相 import(如 app.py 内 import storage),
# 故运行时需保证 app/pipeline 在 path 上;但不能污染顶层造成与 app 包重名,
# 仅在真正跑分析时(_run_analysis 内)临时加入。

BASE_PATH = ""
STATIC_DIR = os.path.join(_HERE, "static")
JOBS_DIR = os.path.join(_APP, "jobs")
_RUNNING = set()

flask_app = Flask(__name__)

# ---------------- 只读 API ----------------
def _bp(rule): return (BASE_PATH + rule) if BASE_PATH else rule

def register_readonly():
    app = flask_app
    @app.get(_bp("/api/summary"))
    def summary():
        c = {"characters": len(RO.GLOBALS.get("characters", {}).get("global_characters", [])),
             "items": len(RO.GLOBALS.get("items", {}).get("global_items", [])),
             "locations": len(RO.GLOBALS.get("locations", {}).get("global_locations", [])),
             "events": len(RO.GLOBALS.get("timeline", {}).get("global_events", []))}
        return jsonify({"chapters": [m["_chapter"] for m in RO.CHAPTERS], "counts": c})

    @app.get(_bp("/api/graph"))
    def graph(): return jsonify(RO.build_graph())

    @app.get(_bp("/api/events"))
    def events(): return jsonify(RO.build_events())

    @app.get(_bp("/api/chapters"))
    def chapters(): return jsonify({"chapters": sorted(RO.RAW.keys())})

    @app.get(_bp("/api/reader/<int:ch>"))
    def reader(ch): return jsonify(RO.build_reader(ch))

    @app.get(_bp("/api/dimension/<name>"))
    def dimension(name):
        d = RO.GLOBALS.get(name)
        if d is None: return jsonify({"error": "无此维度"}), 404
        return jsonify(d)

    @app.get(_bp("/api/node/<ntype>/<nid>"))
    def node(ntype, nid):
        try: nid_v = int(nid)
        except (TypeError, ValueError): nid_v = nid
        anchors = RO.node_anchors(ntype, nid_v)
        return jsonify({"type": ntype, "id": nid_v, "anchors": anchors,
                        "occurrences": RO.find_occurrences([a for a in anchors if a])})

# ---------------- 任务 API ----------------
def job_path(job_id, *p): return os.path.join(JOBS_DIR, job_id, *p)

def _write_progress(job_id, prog):
    p = job_path(job_id, "progress.json"); tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f: json.dump(prog, f, ensure_ascii=False)
    os.replace(tmp, p)

def _read_progress(job_id):
    p = job_path(job_id, "progress.json")
    if not os.path.isfile(p): return None
    try: return json.load(open(p, encoding="utf-8"))
    except Exception: return {"stage": "unknown"}

def _run_analysis(job_id, presplit):
    # pipeline 模块间用裸名 import(import storage 等),运行时临时把 app/pipeline 加入 path
    _pp = os.path.join(_APP, "pipeline")
    if _pp not in sys.path:
        sys.path.append(_pp)
    from app.pipeline import app as pipeline
    out_dir = job_path(job_id, "output"); os.makedirs(out_dir, exist_ok=True)
    state = {"stage": "starting", "done": 0, "total": 0, "chapters": [], "error": None}
    _write_progress(job_id, state)
    def cb(ev):
        st = ev.get("stage")
        if st == "split": state["total"] = ev.get("total", 0); state["stage"] = "analyzing"
        elif st == "chapter":
            state["done"] = ev.get("done", state["done"])
            state["chapters"].append({k: ev.get(k) for k in
                ("chapter", "title", "scenes", "characters", "events", "skipped") if k in ev})
        elif st == "chapter_error":
            state["chapters"].append({"chapter": ev.get("chapter"), "error": ev.get("error")})
        elif st == "aggregate": state["stage"] = "aggregating"
        elif st == "done": state["stage"] = "done"; state["counts"] = ev.get("counts", {})
        _write_progress(job_id, state)
    try:
        pipeline.run(job_path(job_id, "input"), out_dir=out_dir, presplit=presplit, progress_cb=cb)
        if state["stage"] != "done": state["stage"] = "done"; _write_progress(job_id, state)
    except Exception as e:
        state["stage"] = "error"; state["error"] = str(e); _write_progress(job_id, state)
    finally:
        _RUNNING.discard(job_id)

def register_tasks():
    app = flask_app
    @app.post(_bp("/api/upload"))
    def upload():
        job_id = uuid.uuid4().hex[:12]
        os.makedirs(job_path(job_id, "input"), exist_ok=True)
        if "file" in request.files:
            f = request.files["file"]; text = f.read().decode("utf-8", errors="replace"); name = f.filename or "input.txt"
        else:
            text = request.get_data(as_text=True) or ""; name = "input.txt"
        if not text.strip(): return jsonify({"error": "空文本"}), 400
        with open(job_path(job_id, "input", "input.txt"), "w", encoding="utf-8") as fp: fp.write(text)
        _write_progress(job_id, {"stage": "uploaded", "name": name, "chars": len(text),
                                 "done": 0, "total": 0, "chapters": []})
        return jsonify({"job_id": job_id, "chars": len(text)})

    @app.post(_bp("/api/analyze/<job_id>"))
    def analyze(job_id):
        if not os.path.isdir(job_path(job_id, "input")): return jsonify({"error": "job 不存在"}), 404
        if job_id in _RUNNING: return jsonify({"started": False, "reason": "已在运行"}), 409
        presplit = request.args.get("presplit") == "1"
        _RUNNING.add(job_id)
        threading.Thread(target=_run_analysis, args=(job_id, presplit), daemon=True).start()
        return jsonify({"started": True, "job_id": job_id})

    @app.get(_bp("/api/progress/<job_id>"))
    def progress(job_id):
        prog = _read_progress(job_id)
        if prog is None: return jsonify({"error": "job 不存在"}), 404
        prog["running"] = job_id in _RUNNING
        return jsonify(prog)

    @app.get(_bp("/api/jobs"))
    def jobs():
        if not os.path.isdir(JOBS_DIR): return jsonify({"jobs": []})
        out = []
        for j in sorted(os.listdir(JOBS_DIR)):
            pr = _read_progress(j) or {}
            out.append({"job_id": j, "stage": pr.get("stage"), "done": pr.get("done"), "total": pr.get("total")})
        return jsonify({"jobs": out})

# ---------------- 静态托管 ----------------
def register_static():
    app = flask_app
    @app.get(_bp("/") if BASE_PATH else "/")
    def index():
        idx = os.path.join(STATIC_DIR, "index.html")
        if os.path.isfile(idx): return send_from_directory(STATIC_DIR, "index.html")
        return Response(RO.FRONTEND, mimetype="text/html")  # 回退内嵌前端
    @app.get(_bp("/assets/<path:fn>"))
    def assets(fn): return send_from_directory(os.path.join(STATIC_DIR, "assets"), fn)

def create_app(output="output", raw=None, jobs=None, base_path="", static=None):
    global BASE_PATH, STATIC_DIR, JOBS_DIR
    BASE_PATH = base_path.rstrip("/")
    if static: STATIC_DIR = static
    if jobs: JOBS_DIR = jobs
    os.makedirs(JOBS_DIR, exist_ok=True)
    RO.load_data(output, raw)
    register_readonly(); register_tasks(); register_static()
    return flask_app

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", default="output")
    ap.add_argument("--raw", default=None)
    ap.add_argument("--jobs", default=None)
    ap.add_argument("--base-path", default="")
    ap.add_argument("--static", default=None)
    ap.add_argument("--port", type=int, default=8080)
    args = ap.parse_args()
    app = create_app(args.output, args.raw, args.jobs, args.base_path, args.static)
    print(f"加载: {len(RO.CHAPTERS)}章, 原文{len(RO.RAW)}章")
    print(f"前端: {'Vite产物 '+STATIC_DIR if os.path.isfile(os.path.join(STATIC_DIR,'index.html')) else '内嵌回退'}")
    print(f"OLLAMA_URL={os.environ.get('OLLAMA_URL','(默认 18434)')}")
    print(f"服务: http://127.0.0.1:{args.port}{BASE_PATH or '/'}")
    app.run(host="127.0.0.1", port=args.port, threaded=True)
