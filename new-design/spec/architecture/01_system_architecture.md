# 架构规格 · AI-Reader-V2(new-design)

> 逆向自 `app/` 代码。描述系统分层、数据流、存储契约、模型适配、部署拓扑。

## 1. 总体分层

```
┌─────────────────────────────────────────────────────────────┐
│ 前端 web/(Vite + React,豁免零依赖纪律)                       │
│   App.jsx 全局当前小说状态 · 图谱/阅读/时间线/场景视图          │
│   产物 → app/server/static/                                   │
└───────────────▲─────────────────────────────────────────────┘
                │ HTTP(/api/*,可配 BASE_PATH 前缀)
┌───────────────┴─────────────────────────────────────────────┐
│ 合并后端 app/server/main.py(Flask 单服务单端口)              │
│   只读 API(readonly.py) · 任务 API · 库管理 API · 静态托管     │
│   多小说库:use_novel(slug) 上下文加锁装载模块全局              │
└───────────────▲─────────────────────────────────────────────┘
                │ 后台线程调用
┌───────────────┴─────────────────────────────────────────────┐
│ 分析管线 app/pipeline/(app.py 全流程主入口)                   │
│   清洗拆章 → 逐章七维度+事件 → 逐章后处理 → 后台增量聚合         │
│            → 跨章缝合 → 全局分维度聚合 → 校验                   │
└───────────────▲─────────────────────────────────────────────┘
                │ OLLAMA_URL /api/generate
┌───────────────┴─────────────────────────────────────────────┐
│ 本地 LLM 推理(ollama,wangcai 隧道 127.0.0.1:18434)          │
│   huihui_ai/Qwen3.6-abliterated:35b(抽取)/:27b(场景判断)    │
└─────────────────────────────────────────────────────────────┘
```

## 2. 分析数据流(单章 → 全局)

`app.py::run` 编排,`analyze_chapter` 跑单章十步(`CHAPTER_STEPS`):

```
原文 ─CS.clean→ 去噪 ─CS.split_chapters→ 章列表
  每章:
   1 scene        01_scene_splitting     (27b, temp0.15)
   2 character_p1  02_character_pass1     (35b)
   3 character_p2  02_character_pass2     (35b, 注入人物清单)
   4 item_p1       03_item_pass1          (35b, 注入场景清单)
   5 item_p2       03_item_pass2          (35b, 注入物品清单)
   6 location_p1   04_location_pass1      (35b)
   7 location_p2   04_location_pass2      (35b, 注入地点清单)
   ─ merge_core.merge  跨维度 id 解析 + 锚点校验 + sanitize_items(纯确定性)
   ─ _redo_scene_summaries  场景摘要兜底(检出问题→模型重做→再校验→确定性截断兜底)
   8 events        event_pipeline.analyze_events  父事件+子事件+两道校验
   ─ derive_scene_tags        场景基础标签(确定性,零模型)
   ─ 01c function_tags        功能标签(模型 + sanitize 词形校验)
   9 organization  09_org_extraction → org_extract.postprocess + resolve_member_ids
  10 merge/后处理  graph_index.build_graph(_graph) + gap_scan.scan(_gap_suspects)
  → store.save_chapter_merged(ch) → output/<slug>/chNN/_merged.json
  → worker.mark_dirty()  触发后台增量聚合
全局:
  worker.stop(final=True)  → 跨章缝合 + 聚合 原子提交 global/
  aggregate.aggregate(store, call_model, novel_root)  再跑一次取完整 idx
```

关键:逐章错误隔离(单章 try/except,失败记 `chapter_error` 继续);后处理两步各自 try/except
隔离(失败记 `_postproc_errors`,不影响主产物落盘)。

## 3. 跨章缝合架构(cross_chapter.run)

```
各章局部实体 ─→ resolve_global_entities(并查集)
                  归并键过 _is_merge_key(剔代词/泛称/绰号/单字/姓+职务)
                  mentions → aux(不作键不展示)
                  完全同名=高置信合并;仅别名重叠=ambiguities
  启用 LLM 复核(use_llm + call_model)时铁律顺序:
    entity_clean 封闭式清洗  →  精确同名合并  →  entity_review 模型复核  →  stitch_timelines
    复核/清洗均带磁盘缓存(novel_root/.review_cache/{review,clean}.json),3 票多数自洽投票
  产出:global_characters/items/locations/organizations
        + character_timelines + sync_points + ambiguities
```

模型判断与确定性兜底的边界:`merge_core` / `graph_index` / `gap_scan` / `sanitize_*` 纯确定性;
`entity_review` / `entity_clean` 是显式 LLM 复核层(独立模块 + 缓存),不污染确定性归并主路径。

## 4. 三层存储契约(storage.py)

库根 `LIB = app/`,按小说 slug 隔离:

```
raw/<slug>.txt 或 raw/<slug>/        原始(zip 解压进目录)
input/<slug>/chNN.txt                清洗+拆章后各章原文(全局重排)
output/<slug>/meta.json              {novel_name, author, source_type, uploaded_at,
                                      stage, chapter_count, done, total, control,
                                      rules_selected, clean_fingerprint, counts, ...}
output/<slug>/chNN/_merged.json      第二层:每章七维度跨维度归并
output/<slug>/chNN/<dim>_<pass>.json 第一层:原始 pass 输出(可选落盘)
output/<slug>/global/<dim>.json      第三层:跨章归一,每维度一个全局文件
output/<slug>/global/_index.json     顶层索引(章节清单+各全局文件+统计+校验摘要)
```

原子提交(`commit_global`):增量聚合写临时 `global_subdir` → `os.replace` 切换为正式 `global/`,
防前端读到半成品。`stage` 状态机:`uploaded → splitting → analyzing → aggregating → done|partial`,
异常 `error`,软停 `paused`/`stopping`,僵尸 `interrupted`。

## 5. 模型适配(app.py PASS_MODELS)

| 任务类 | pass | 模型 | 理由 |
|---|---|---|---|
| 抽取类 | character/item/location/event/org | `:35b`(DEFAULT_MODEL) | 容量优势,远程地名等稳 |
| 判断类 | scene(场景边界) | `:27b` | 实测场景拆分更稳,35b 过度细切+段数漂移 |

调用参数固定:`format:"json"`、`think:false`、`stream:false`、`num_predict:4096`。
`call_model` 容忍截断 JSON(`_safe_json` 补齐括号再解析)。Ollama 端点经 `OLLAMA_URL`
环境变量可配(默认 18434 隧道;非生产 app.py 历史写死 11434)。

## 6. 部署拓扑(wangcai · 8543,详见部署规格)

```
浏览器 ──https://f.xbot.cool:8543/──▶ nginx(8543 ssl, letsencrypt f.xbot.cool 证书)
                                       login-gated 复用 :8765
                                       location / → proxy_pass 127.0.0.1:8081 (read_timeout 3600s)
                                          │
                          systemd ai-reader-new.service
                          .venv/bin/python -m app.server.main --lib .../app
                            --static .../app/server/static --base-path "" --port 8081
                          Environment OLLAMA_URL=http://127.0.0.1:18434
                                          │
                                  ollama 隧道 127.0.0.1:18434
```

与平台 f.xbot.cool 配置、ubuntu 老版本(8011/8443)完全隔离;独立 nginx 站点文件
`/etc/nginx/sites-available/ai-reader-new`。

## 7. 关键架构决策与权衡

- **后端合并**:原 server.py(只读纯标准库)+ tasks.py(Flask)→ 单 Flask 服务单端口,
  同前缀提供只读+任务+静态。合并后只读核心 `readonly.py` 仍纯标准库(可独立起在任意机器)。
- **前端单 base**:`/api` 同含只读与任务端点;`VITE_BASE` + `--base-path` 两处配置控制前缀,
  迁顶层不改代码。
- **静态回退**:`static/index.html` 存在则托管 Vite 产物,否则回退 `readonly.py` 内嵌 `FRONTEND`
  字符串(旧机/无构建环境仍可起)。
- **后台增量聚合 worker**:每章完成即增量聚合,图谱/高亮随进度显现,不阻塞主分析循环;
  用 `functools.partial` 绑定 `call_model` + `novel_root` 进 worker,使其也走带缓存的复核归并。
