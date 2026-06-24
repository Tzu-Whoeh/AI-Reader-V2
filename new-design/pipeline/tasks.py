#!/usr/bin/env python3
"""
分析任务层(M2)· Flask
独立应用的"上传 → 启动分析 → 进度"后端。包装 app.py 的 run(),不改其分析逻辑。

依赖:flask(M2 经批准可加依赖;后端只读可视化 server.py 仍纯标准库,二者分离)。

端点:
  POST /api/upload                 上传文本(form-data file 或 raw body) → {job_id}
  POST /api/analyze/<job_id>       后台异步触发分析(presplit 可选) → {started}
  GET  /api/progress/<job_id>      进度 {stage, done, total, chapters[], error?}
  GET  /api/jobs                   任务列表
产物落 JOBS_DIR/<job_id>/output/(global/ 可被只读 server.py 消费)。

运行:
  OLLAMA_URL=http://127.0.0.1:18434 python tasks.py --port 8090 --jobs /path/to/jobs
"""
import os, sys, json, uuid, threading, time, argparse
from flask import Flask, request, jsonify

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

app = Flask(__name__)
JOBS_DIR = os.environ.get("JOBS_DIR", os.path.join(_HERE, "jobs"))
_LOCKS = {}            # job_id -> threading.Lock(防重复触发)
_RUNNING = set()

def job_path(job_id, *parts):
    return os.path.join(JOBS_DIR, job_id, *parts)

def _write_progress(job_id, prog):
    p = job_path(job_id, "progress.json")
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(prog, f, ensure_ascii=False)
    os.replace(tmp, p)   # 原子写,避免轮询读到半截

def _read_progress(job_id):
    p = job_path(job_id, "progress.json")
    if not os.path.isfile(p):
        return None
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return {"stage": "unknown"}

@app.post("/api/upload")
def upload():
    job_id = uuid.uuid4().hex[:12]
    os.makedirs(job_path(job_id, "input"), exist_ok=True)
    # 支持 multipart file 或 raw body
    if "file" in request.files:
        f = request.files["file"]
        text = f.read().decode("utf-8", errors="replace")
        name = f.filename or "input.txt"
    else:
        text = request.get_data(as_text=True) or ""
        name = "input.txt"
    if not text.strip():
        return jsonify({"error": "空文本"}), 400
    with open(job_path(job_id, "input", "input.txt"), "w", encoding="utf-8") as fp:
        fp.write(text)
    _write_progress(job_id, {"stage": "uploaded", "name": name, "chars": len(text),
                             "done": 0, "total": 0, "chapters": []})
    return jsonify({"job_id": job_id, "chars": len(text)})

def _run_analysis(job_id, presplit):
    import app as pipeline   # 复用 app.py 的 run()
    out_dir = job_path(job_id, "output")
    os.makedirs(out_dir, exist_ok=True)
    state = {"stage": "starting", "done": 0, "total": 0, "chapters": [], "error": None}
    _write_progress(job_id, state)

    def cb(ev):
        st = ev.get("stage")
        if st == "split":
            state["total"] = ev.get("total", 0); state["stage"] = "analyzing"
        elif st == "chapter":
            state["done"] = ev.get("done", state["done"])
            state["chapters"].append({k: ev.get(k) for k in
                ("chapter", "title", "scenes", "characters", "events", "skipped") if k in ev})
        elif st == "chapter_error":
            state["chapters"].append({"chapter": ev.get("chapter"), "error": ev.get("error")})
        elif st == "aggregate":
            state["stage"] = "aggregating"
        elif st == "done":
            state["stage"] = "done"; state["counts"] = ev.get("counts", {})
        state["stage"] = state.get("stage", "analyzing")
        _write_progress(job_id, state)

    try:
        inp = job_path(job_id, "input")  # 目录:app.py 会读其中 txt
        pipeline.run(inp, out_dir=out_dir, presplit=presplit, progress_cb=cb)
        if state["stage"] != "done":
            state["stage"] = "done"; _write_progress(job_id, state)
    except Exception as e:
        state["stage"] = "error"; state["error"] = str(e)
        _write_progress(job_id, state)
    finally:
        _RUNNING.discard(job_id)

@app.post("/api/analyze/<job_id>")
def analyze(job_id):
    if not os.path.isdir(job_path(job_id, "input")):
        return jsonify({"error": "job 不存在"}), 404
    if job_id in _RUNNING:
        return jsonify({"started": False, "reason": "已在运行"}), 409
    presplit = request.args.get("presplit") == "1"
    _RUNNING.add(job_id)
    t = threading.Thread(target=_run_analysis, args=(job_id, presplit), daemon=True)
    t.start()
    return jsonify({"started": True, "job_id": job_id})

@app.get("/api/progress/<job_id>")
def progress(job_id):
    prog = _read_progress(job_id)
    if prog is None:
        return jsonify({"error": "job 不存在"}), 404
    prog["running"] = job_id in _RUNNING
    return jsonify(prog)

@app.get("/api/jobs")
def jobs():
    if not os.path.isdir(JOBS_DIR):
        return jsonify({"jobs": []})
    out = []
    for j in sorted(os.listdir(JOBS_DIR)):
        prog = _read_progress(j) or {}
        out.append({"job_id": j, "stage": prog.get("stage"),
                    "done": prog.get("done"), "total": prog.get("total")})
    return jsonify({"jobs": out})

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8090)
    ap.add_argument("--jobs", default=None)
    args = ap.parse_args()
    if args.jobs:
        JOBS_DIR = args.jobs
    os.makedirs(JOBS_DIR, exist_ok=True)
    print(f"任务层: http://127.0.0.1:{args.port}  jobs={JOBS_DIR}")
    print(f"OLLAMA_URL={os.environ.get('OLLAMA_URL','(默认 18434)')}")
    app.run(host="127.0.0.1", port=args.port, threaded=True)
