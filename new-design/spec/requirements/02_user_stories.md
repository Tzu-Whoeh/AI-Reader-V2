# 用户故事 · AI-Reader-V2(new-design)

> 据 `01_product_requirements.md` 的 FR 与 `app/` 实际端点/管线行为编写。
> 每条故事可回溯到具体 FR 与端点;验收标准对应**代码已实现的真实行为**,不臆造功能。
> 格式:**作为** <角色>,**我想要** <能力>,**以便** <价值>。

## 0. 角色(Personas)

| 角色 | 描述 | 主要诉求 |
|---|---|---|
| **读者 Reader** | 读网文/小说,想厘清人物关系、时间线、地点 | 看得懂、查得到出处、跟着读 |
| **分析者 Analyst** | 研究叙事结构,要可靠的结构化数据 | 准确、可追溯、歧义不被硬合 |
| **运营 Operator** | 部署/维护实例,管理书库 | 上传顺畅、进度可见、可中断续跑、可清理 |
| **调校者 Tuner** | 调清洗规则/功能标签,适配不同书 | 规则可配、可重清洗、改完知道要重分析 |

---

## 1. 上传与建库(→ FR-1)

**US-1.1** 作为 Operator,我想要上传一个 `.txt` 小说文件,以便系统据它建一本可分析的小说。
- 验收:`POST /api/upload` 接受 txt;按文件名 slug 化;落 `raw/<slug>.txt`;建 `meta.json`(stage=`uploaded`);返回 `{slug, novel_name, source_type:"txt"}`。

**US-1.2** 作为 Operator,我想要上传一个 `.zip`(内含多个 txt 分卷),以便分卷小说也能整本入库。
- 验收:zip 内 txt 解压进 `raw/<slug>/`,跳过绝对路径/`..`/非 txt(防 zip-slip);源类型记 `zip`。

**US-1.3** 作为 Operator,我想要重传同名小说时被拦下,以便不会误覆盖已分析的数据。
- 验收:`output/<slug>` 已存在 → 返回 **409** + 现有 slug,不覆盖。

**US-1.4** 作为 Reader,我想要看到书库里所有小说及其状态,以便挑一本进入。
- 验收:`GET /api/novels` 列出每本 slug/书名/stage/`running`/`dirty`;`current` 为最近上传。

---

## 2. 清洗与拆章规则(→ FR-2)

**US-2.1** 作为 Tuner,我想要勾选启用哪些清洗/拆章规则,以便适配不同来源的排版噪音。
- 验收:`GET /api/rules` 返回预制/自定义/用户预设/默认勾选;每本书 `rules_selected` 可独立设(`PUT /api/novels/<slug>/meta`)。

**US-2.2** 作为 Tuner,我想要新增一条自定义正则规则,以便处理预制规则覆盖不到的噪音/章节标记。
- 验收:`POST /api/rules/custom`(add/update/delete);正则非法 → **400**;不可覆盖预制规则 id → 400。

**US-2.3** 作为 Tuner,我想要把常用规则组合存成预设,以便下次一键套用。
- 验收:`POST /api/rules/presets`(save/delete,按 name)。

**US-2.4** 作为 Tuner,我想要不重新分析就先重跑清洗+拆章,以便确认拆章结果对了再花算力分析。
- 验收:`POST /api/reclean/<slug>` 用当前 `rules_selected` 重排 `input/<slug>/chNN.txt`,更新 `chapter_count`;运行中 → 409。

---

## 3. 启动分析与进度(→ FR-3, FR-6)

**US-3.1** 作为 Operator,我想要对一本书发起分析并立即拿到响应,以便不必等整本跑完。
- 验收:`POST /api/analyze/<slug>` 起后台线程,立即返回 `{started:true}`;已在跑 → **409** `{started:false,reason:"已在运行"}`。

**US-3.2** 作为 Operator,我想要轮询看到分析进度(到章、到步),以便知道还要多久、卡在哪。
- 验收:`GET /api/progress/<slug>` 返回 stage/`done`/`total`/`cur_chapter`/`step`/`step_name`(十步 CHAPTER_STEPS 之一)。

**US-3.3** 作为 Operator,我想要在分析中途暂停/恢复/停止,以便让出 GPU 或及时止损。
- 验收:`pause`(章间软停,不打断进行中的章)/`resume`/`stop`(停后续章但聚合已完成部分);非运行中调用 → 409。

**US-3.4** 作为 Operator,我想要中断后重新发起能续跑,以便不浪费已完成章节的算力。
- 验收:已有 `_merged.json` 的章跳过(断点续跑);僵尸态(meta 活动但进程不在)对外显示 `interrupted`。

**US-3.5** 作为 Analyst,我想要个别章节失败时整本不崩,以便拿到尽可能完整的结果并知道哪章坏了。
- 验收:单章 try/except 隔离,失败记 `chapter_error` 继续;完结据实判 `done`/`partial`(`error_count`/`succeeded_count`/`partial_reason`/`first_error`)。

---

## 4. 浏览结构化结果(→ FR-5)

**US-4.1** 作为 Reader,我想要一页概览(各维度计数 + 章节清单),以便快速了解这本书的规模。
- 验收:`GET /api/summary` 返回 characters/items/locations/organizations/events 计数 + 章号列表。

**US-4.2** 作为 Reader,我想要一张全局关系图,以便直观看人物/物品/地点/事件如何相连。
- 验收:`GET /api/graph` 返回 node/edge;边含四类 `char`/`loc`/`item`/`event`;事件作为一等节点;`global_id=0` 不被漏(`is not None` 判空)。

**US-4.3** 作为 Reader,我想要点开任一节点看到它的全部原文出处,以便核对结论、回到正文。
- 验收:`GET /api/node/<type>/<id>` 返回锚点 + 各章原文反查 `occurrences`;前端高亮 term 正则转义。

**US-4.4** 作为 Reader,我想要按章逐章阅读并叠加分析标注,以便边读边看场景/人物/事件。
- 验收:`GET /api/reader/<ch>` 返回该章原文 + 标注;`GET /api/chapters` 列出有产物的章号。

**US-4.5** 作为 Analyst,我想要按维度取全局数据原样,以便做二次分析或导出。
- 验收:`GET /api/dimension/<name>`(characters/items/locations/organizations/timeline/scenes)原样返回;无此维度 → 404。

**US-4.6** 作为 Reader,我想要看人物的个人时间线与多线交汇点,以便理清谁在何时做了什么、几条线何处相遇。
- 验收:`GET /api/events` 返回 `global_events` + `character_timelines` + `sync_points`。

**US-4.7** 作为 Reader,我想要在多本书之间切换浏览,以便不必每次重启服务。
- 验收:所有读类端点支持 `?novel=<slug>`,缺省取最近上传;前端全局当前小说状态(App.jsx)。

---

## 5. 可靠性与可信(→ FR-4, NFR-1/3,四道防线)

**US-5.1** 作为 Analyst,我想要每个抽取结论都能逐字回到原文,以便信任它不是模型臆造。
- 验收:mention/alias/事件物品/场景首尾必须逐字命中原文(锚点校验 R1),否则剔除并记 `_validation`/`_anchor_miss`。

**US-5.2** 作为 Analyst,我想要跨章同名/疑似同体但拿不准的不被硬合并,以便自己判而非被代码替我决定。
- 验收:非高置信归并进 `ambiguities`(R4);代词/泛称/绰号/单字/「姓+职务」不作合并桥(`_is_merge_key`),防超级簇坍缩。

**US-5.3** 作为 Analyst,我想要没有明确依据的绝对时间一律留空,以便时间线不被推算污染。
- 验收:`abs_interval` 无明确文本依据必须 `null`(R3),绝不推算。

**US-5.4** 作为 Analyst,我想要人物跨章归一在同音异写/正式称谓同指时也能并上,以便同一个人不被拆成多个。
- 验收:人物维度走 entity_clean 清洗 + entity_review 复核(3 票多数投票,带缓存);**仅人物**,物品/地点/组织为纯 exact-only。

---

## 6. 元信息与维护(→ FR-1.4/1.5)

**US-6.1** 作为 Operator,我想要编辑书名/作者/封面/标签,以便书库整齐可检索。
- 验收:`PUT /api/novels/<slug>/meta` 改 novel_name/author/cover/tags。

**US-6.2** 作为 Tuner,我想要为单本书自定义场景功能标签候选清单,以便标签贴合该书题材。
- 验收:meta 的 `function_tag_catalog`(字符串列表,去空白/去重/2–5 字限长);为空回退内置默认。

**US-6.3** 作为 Tuner,我想要改了规则后系统提示该书需重新分析,以便不被陈旧结果误导。
- 验收:meta 记 `clean_fingerprint`;当前勾选规则指纹 ≠ 记录值 → `dirty=true`(`_is_dirty`)。

**US-6.4** 作为 Operator,我想要删除不要的小说,以便回收存储;运行中要拦下。
- 验收:`DELETE /api/novels/<slug>` 删 raw/input/output;运行中 → **409**。

---

## 7. 部署与运营(→ NFR-5,部署规格)

**US-7.1** 作为 Operator,我想要一条命令把应用起在生产端口,以便快速上线。
- 验收:`app/run.sh [端口] [base前缀]` 或 `python -m app.server.main --lib <app> --base-path ... --port ...`;经 systemd `ai-reader-new.service` 开机自启+崩溃重启。

**US-7.2** 作为 Operator,我想要前端构建产物被自动托管,缺产物时仍能起,以便部署有兜底。
- 验收:`static/index.html` 存在则托管 Vite 产物,否则回退 `readonly.py` 内嵌 `FRONTEND`。

**US-7.3** 作为 Operator,我想要长耗时推理请求不被反代掐断,以便整本分析跑得完。
- 验收:nginx `proxy_read_timeout 3600s`;管线经 `OLLAMA_URL`(默认 18434 隧道)调用。

---

## 8. 故事 ↔ FR 回溯矩阵

| FR | 覆盖故事 |
|---|---|
| FR-1 多小说库 | US-1.1~1.4, US-6.1/6.4 |
| FR-2 清洗拆章 | US-2.1~2.4 |
| FR-3 逐章分析 | US-3.1~3.2, US-3.5 |
| FR-4 跨章缝合 | US-5.2/5.4 |
| FR-5 只读浏览 | US-4.1~4.7 |
| FR-6 任务控制 | US-3.1~3.5 |
| NFR-1/3 可靠性 | US-5.1~5.4 |
| NFR-5 部署隔离 | US-7.1~7.3 |
| FR-1.4 元信息 | US-6.1~6.3 |

> 非目标(当前不做,故无故事):用户账户体系/权限分级(访问由 nginx login-gate 统一把关)、
> 在线编辑修正分析产物、多人协作标注、云端多 LLM 供应商切换(本框架专注本地 ollama)。
