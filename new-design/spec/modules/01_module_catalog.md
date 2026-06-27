# 模块规格 · AI-Reader-V2(new-design)

> 逆向自 `app/` 代码。逐模块列职责、输入输出、依赖、确定性属性。

## 1. pipeline/ 分析管线

| 模块 | 职责 | 输入 → 输出 | 确定性 |
|---|---|---|---|
| `app.py` | **全流程主入口** | 文件/目录 → 三层产物 + idx | 编排(调模型) |
| `clean_split.py` | 清洗 + 拆章 | 原文 → (cleaned, report)、章列表 | 纯确定性(规则 NOISE/CHAPTER_PATTERNS) |
| `rules.py` | 规则解析/指纹/库 | selected_ids → (noise_pats, chap_pats);预设/自定义/默认管理 | 纯确定性 |
| `event_pipeline.py` | 两层事件抽取 | 全文+场景+人物+物品 → parent_events/sub_events/time_refs | 调模型 + 两道确定性校验 |
| `merge_core.py` | 章节内归并 | scenes/c1/i1/l1 + 原文 → merged | **纯确定性**(锚点校验+跨维度 id 解析+sanitize_items) |
| `org_extract.py` | 组织维度后处理 | 模型 org 原始 + 原文 → organizations/memberships/relations | 确定性后处理 + 成员名归一 |
| `cross_chapter.py` | 跨章缝合 | 各章局部实体 → 全局实体+时间线+同步点+歧义 | 并查集确定性 +(可选)LLM 复核层 |
| `entity_normalize.py` | 脏人名归一 | 名字 → 归一 | 符号归一 + 相似×上下文佐证 + role_conflict 防误合 |
| `entity_review.py` | LLM 合并复核 | 候选对 + 角色/证据画像 → 合并判定 | **LLM**(3 票多数投票 + 磁盘缓存) |
| `entity_clean.py` | 封闭式名/别名清洗 | ≥4 字 token → multi?/is_person? 判定 | **LLM**(3 票投票 + 词级磁盘缓存) |
| `aggregate.py` | 全局分维度聚合 | 各章 _merged → global/*.json | 编排(转发 call_model/novel_root) |
| `agg_worker.py` | 后台增量聚合 worker | mark_dirty 触发 → 增量聚合 + 原子提交 | 线程编排 |
| `graph_index.py` | 全向图索引(逐章) | merged + ev → `_graph` 邻接表 | **纯确定性** |
| `gap_scan.py` | 漏标疑点扫描(逐章) | text + merged + ev → `_gap_suspects` | **纯确定性**(只报不改) |
| `storage.py` | 三层产物落盘契约 | — | 纯确定性(含 commit_global 原子提交) |
| `validate.py` | 语义校验 R1–R6 | global_dir + raw → ValidationReport | **纯标准库**(后端运行时校验) |

⚠️ 遗留:旧根目录有 `orchestrator.py`(四维度旧版),new-design 一律以 `app.py` 为准,勿参照。

### 1.1 merge_core.py 关键函数
- `anchor_clean(records, text, name_key, mention_keys)`:剔除原文不存在的 mention/alias,记 dropped。
- `build_name_index` / `resolve`:name/alias → id 查找(长名优先,精确优先于包含)。
- `_strip_meta` / `_truncate_at_sentence`:场景摘要确定性兜底(剥离元论证、句末截断)。
- `detect_scene_issues` / `apply_summary_fallback` / `derive_scene_tags` / `sanitize_function_tags`。
- `sanitize_items`:容器关系靠 PLACE_WORDS/CONTAINER_WORDS 黑白名单(词表外会漏,已知局限)。

### 1.2 cross_chapter.py 关键设计
- `_is_merge_key(tok)`:专名守卫。剔除单字、`_PRONOUNS`、`_GENERIC_TITLES`、`_EPITHETS`、
  `_SURNAME_TITLE`(姓+泛职)。**防超级簇坍缩的核心**。
- `resolve_global_entities(..., alias_is_mentions)`:characters/orgs 的 aliases 参与归并+展示;
  items/locations 的 mentions 仅入 `aux`(原文定位,不作键不展示)。
- 并查集:名字(过 mkeys)有交集则 union;完全同名=高置信,仅别名重叠=ambiguities。
- `run(chapters, call_model, novel_root, use_llm)`:铁律顺序 clean→exact-merge→review→stitch。

### 1.3 event_pipeline.py
- `extract_parent_events`:章级父事件(看全章,participants 从人物候选选,带 scene_ref+anchor_text+story_order)。
- 子事件:逐场景补细节,挂父,从候选清单选 participants/items。
- 两道确定性校验:(a) 施事者从父继承;(b) 物品锚点必须出现在子事件 anchor_text 句内,否则剔除。
- `set_prompts_dir` / `call_model` 由 app.py 注入(`EP.call_model=call_model`)。

## 2. server/ 合并后端

| 模块 | 职责 | 关键点 |
|---|---|---|
| `main.py` | Flask 单服务 | create_app + CLI;register_readonly/tasks/library_admin/static |
| `readonly.py` | 只读逻辑 | **纯标准库**;use_novel(slug) 上下文加锁装载模块全局;build_graph/events/reader/node_anchors/find_occurrences |

### 2.1 端点清单
只读(支持 `?novel=`):`GET /api/summary|graph|events|chapters|reader/<ch>|dimension/<name>|node/<type>/<id>`。
库:`GET /api/novels`。
任务:`POST /api/upload`(txt/zip)、`POST /api/analyze/<slug>`、`GET /api/progress/<slug>`、
`POST /api/pause|resume|stop/<slug>`。
库管理:`GET /api/rules`、`POST /api/rules/custom`、`PUT /api/rules/default`、`POST /api/rules/presets`、
`PUT /api/novels/<slug>/meta`、`DELETE /api/novels/<slug>`、`POST /api/reclean/<slug>`。
静态:`GET /`、`GET /assets/<path>`。

### 2.2 图谱边映射(API.md 契约,build_graph 落地)
| kind | 来源 | 映射 |
|---|---|---|
| `char` | characters.relations | from_global/to_global → character 节点 |
| `loc` | locations.relations | 同上 → location 节点 |
| `item` | Item.owner_ref/part_of/set_group + item_locations | owner_ref→character;part_of→item;set_group 同组互连;item_locations→location |
| `event` | timeline.global_events | 每事件一 event 节点;global_participants → character 边 |

**落地必修 bug**:判空必须用 `is not None`(`global_id` 可能为 0,旧 `if x and y` 会静默漏边)。
`/api/node` 高亮 term 前端必须正则转义(`escapeRe`)。

## 3. model/ 领域模型(SSOT)

| 文件 | 角色 |
|---|---|
| `MODEL.md` | 实体关系模型人读导读(SSOT 文字版) |
| `API.md` | API 传输契约导读 |
| `ORG_DESIGN.md` | 组织维度设计 |
| `schema/core.schema.json` | 领域核心 JSON Schema(权威) |
| `schema/global_*.schema.json` | 各全局维度 Schema(characters/items/locations/organizations/scenes/timeline) |
| `schema/api_*.schema.json` | API 响应 Schema(summary/graph/dimension/node/events/core) |
| `schema/validation_report.schema.json` | 校验报告形态 |

冲突时以 JSON Schema 为准。两层 id(局部 chapter+local_id / 全局 global_id),引用而非内联,
校验进模型(R1–R6)。

## 4. prompts/ 提示词(单一真相源)

编号英文名共 15 个:`01_scene_splitting`、`01b_summary_redo`、`01c_scene_function_tags`、
`02_character_pass1/pass2`、`03_item_pass1/pass2`、`04_location_pass1/pass2`、`05_time_analysis`、
`06_event_pass1_parent/pass2_sub`、`07_gap_fill`、`08_time_ref`、`09_org_extraction`。
`app.py`/`event_pipeline.py` 按编号名加载;**不得**用历史中文名。

## 5. web/ 前端(豁免零依赖)

Vite + React。`src/App.jsx`(全局当前小说状态)、`api.js`、`main.jsx`、`theme.css`、
`components/`、`views/`(图谱/阅读/时间线/场景)。`npm run build`(`VITE_BASE` 控前缀)→
产物进 `app/server/static/`。

## 6. tools/ 与 rules 资源

- `tools/schema_check.py`:CI/离线结构校验(jsonschema 校验 global/*.json vs schema)。**不在运行时调用**。
- `app/rules/presets.json` + `pipeline/_presets_seed.json`:清洗/拆章预设规则种子。
