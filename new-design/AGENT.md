# AGENT.md · new-design 叙事分析框架 协作手册

本文件给在本仓库 `new-design/` 下工作的 AI agent。讲红线、纪律、命名约定、已知坑,
不重复使用说明 —— 怎么跑看 `APP_USAGE.md`,浏览器看 `BROWSER_USAGE.md`,架构看 `README.md`。

## 0. 一句话定位

中文叙事文本(网文/小说)结构化分析框架。原则:**模型做判断、代码兜底校验、不确定项交人工**。
任何改动不得破坏这条 —— 尤其不能把"代码确定性校验"退化成"再过一次模型"。

## 1. 真正的入口与模块地图

| 文件 | 角色 | 备注 |
|---|---|---|
| `pipeline/app.py` | **全流程主入口** | 清洗→拆章→逐章六维度+事件→逐章后处理→全局聚合;断点续跑;单章错误隔离 |
| `pipeline/event_pipeline.py` | 两层事件抽取 | 父事件(章级)+子事件(场景级)+两道校验 |
| `pipeline/merge_core.py` | 章节内归并 | 锚点校验 + 跨维度 id 解析 + sanitize_items;**纯确定性** |
| `pipeline/cross_chapter.py` | 跨章缝合 | 并查集全局实体归一 + 个人时间线 + 同步点 + 歧义报告 |
| `pipeline/entity_normalize.py` | 脏人名归一 | 符号归一 + 名字相似×上下文佐证 + role_conflict 防误合 |
| `pipeline/aggregate.py` | 全局分维度聚合 | 跨章后每维度一个全局文件 |
| `pipeline/clean_split.py` | 清洗+拆章 | 确定性,规则在 NOISE_PATTERNS / CHAPTER_PATTERNS |
| `pipeline/graph_index.py` | 全向图索引 | **逐章**建图(谁指向我/我连到谁);在 `analyze_chapter` 内调用 |
| `pipeline/gap_scan.py` | 漏标疑点扫描 | **逐章**找疑点(只报不改);在 `analyze_chapter` 内调用 |
| `pipeline/storage.py` | 三层产物落盘契约 | output/chNN/* 与 output/global/* |
| `pipeline/server.py` | 可视化后端 | 纯标准库 http.server,零三方依赖 |

⚠️ `pipeline/orchestrator.py` 是**遗留四维度旧版**(用旧中文提示词名、不跑事件/跨章/落盘)。
新工作一律以 `app.py` 为准。除非明确要清理遗留代码,否则不要改它、也不要参照它写新逻辑。

## 2. 命名约定(踩过的坑,务必遵守)

- 提示词文件用 `prompts/` 下的**编号英文名**:`01_scene_splitting.txt`、`02_character_pass1_recognition.txt` …
  `app.py`/`event_pipeline.py` 按这套名加载。**不要**用 README/docs/07 里出现的中文名
  (`人物分析_Pass1_*.txt`、`事件分析_Pass1_*.txt`)—— 那是历史残留,会 FileNotFoundError。
- 候选清单注入提示词时用**纯数字 id**(不加 C/I/L 前缀),否则模型会照抄前缀导致连线值非数字。
- 物品关系字段:一对一用 `part_of`,平级成套用 `set_group`。

## 3. 不可动摇的可靠性四道防线

改任何东西前先确认没削弱这四条 —— 它们是本框架根除幻觉的核心:

1. **锚点校验**(`merge_core.anchor_clean` / 事件 `anchor_text` 句内校验):
   所有 mention/alias/事件物品必须**逐字出现在原文**,否则剔除并记入 `_validation`。
2. **id 引用**:Pass2 / 跨章 / 子事件只能引用已存在的 id,机制上无法凭空造实体。
3. **绝对时间纪律**:只认原文字面时间,无明确日期一律 null,绝不推算。
4. **歧义交人工**:跨章/脏名非高置信归并全进 `ambiguities`,代码不擅自终裁。

## 4. 调用配置(动模型参数前对齐)

`format:"json"`(必须,否则全角标点污染 JSON 结构位)、`think:false`、`stream:false`;
temperature 场景 0.15 / 其余 0.12;`app.py` 整章 `num_ctx=49152`,`event_pipeline` 默认 8192。
平台环境替换各文件的 `call_model()`(并对事件管道 `EP.call_model=...`)。

**模型按任务适配(`app.py` 的 `PASS_MODELS` 字典)**:
- **抽取类**(人物/物品/地点识别、共指归并、关系、事件)→ `35b`(`DEFAULT_MODEL`)。容量优势,地点维度尤其明显(如远程地名"长春"只有 35b 稳定判 city)。
- **判断类**(场景边界判断)→ `27b`。实测在场景拆分上比 35b 更稳(35b 在长复杂章过度细切且段数漂移)。详见下方「场景拆分」节。
- 改某 pass 的模型只改 `PASS_MODELS` 字典,不要散落地写死模型名。

## 5. 场景拆分(scene splitting)— 判据与模型

**判据:只在两类客观硬边界处切,其余一律不切**(prompt `01_scene_splitting.txt`):
- `loc` 地点变化:人物身体真实移动到新场所(走出/坐进/进入),原文有地点词/移动动作。
- `time` 往事回放:从当下跳入有明确过去时空标记的客观回放;回放结束拉回当下也算一次。
- **消歧**:一处同时像 loc 又像 time(思绪转到"别时空别处的事")统一标 `time`;loc 只给身体移动。
- **不切的(交给下游事件层)**:互动性质反转(审问→调情)、人物分批进出、内心独白、换话题、情绪变化。
  内心独白绝不独立成段,并入所处当下场景。

**为什么是这两类**:迭代验证(v1→v8)发现,`loc` 和"无边界"模型判得稳(有物理锚点);
`turn`(性质反转)、密集 `time`、分批 `cast` 需语义解读,模型判不稳、段数漂移。
故收敛到只认两类硬边界 + 把软边界判断下放到事件层。

**模型:27b**。场景拆分是判断任务,27b 稳于 35b(6 文本 ×3 跑稳定性:5/6 段数与 cut_reason 三跑一致)。

**输出字段**:每段含 `cut_reason`(loc/time/start),让每一刀的客观依据可审计。

**⚠️ 不要给场景拆分加后处理**。实测合并类后处理(连续 cast 合并 / 内心独白合并)会**放大**漂移
——它对不同结构输入做不同程度合并,把输入的 ±1 差异翻译成更大的输出差异。裸 prompt 输出反而更稳。

**已知局限**:
- "往事夹叙同地点"章节(往事融在心理活动里、非干净回放段)有 ±1 段摆动(算不算独立 time 段)。
- 极密集时空跳转(单段多次内心/回忆层切换)边界计数可能不稳。这两类是文本固有难度,非 bug,勿强行加规则。

## 6. 逐章后处理(确定性,挂在章节产物上)

`analyze_chapter` 在事件抽取后做两步纯确定性后处理(不调模型),结果写进该章 `_merged.json`:

- `_graph` ← `graph_index.build_graph(merged, ev)`:全向邻接表,任意节点一跳列出全部邻居。
- `_gap_suspects` ← `gap_scan.scan(text, merged, ev)`:漏标疑点清单(人物出现未挂事件 / 物品漏挂场景 /
  owner 未匹配 / 关系 id 悬空)。只报不改,供定向补抽。
- 两步各自 try/except 隔离:任一失败只记入 `_postproc_errors`,不影响该章主产物落盘。
- 注:此处后处理是给【事件/图谱】兜底,与上节「场景拆分不加后处理」不矛盾——场景层裸输出,事件/图谱层才确定性兜底。

## 7. 已知坑 / 待修(改前先看,别重复踩)

- **container 关系靠关键字黑白名单**(`sanitize_items` 的 PLACE_WORDS/CONTAINER_WORDS):
  词表外的容器(行李/麻袋等)会漏,需随语料维护;README 已承认会过度标注。
- **跨章并查集 O(n²)**(`cross_chapter.resolve_global_entities`):长篇全本要留意性能。
- **长章多块的块内跨块实体归一**:接口预留未实现,短章无需;要做复用并查集逻辑。
- **文档"五维度 vs 六维度"口径不一**:事件其实是第六个一等中枢,README 标题仍写五维度。
- **历史样本用旧 `events` 键**:`samples/` 里部分 `_merged.json` 用顶层 `events`;新流程产出
  `parent_events`/`sub_events`。`aggregate.py` 已兼容(`m.get("parent_events", m.get("events",[]))`),
  但读旧样本的新代码要注意这个键名差异。

## 8. 改这个项目的工作纪律

- **改提示词**:先在 `samples/` 的真实文本上验证;稳定性测试(同 prompt 跑 3 次)+
  泛化测试(结构不同的文本)再定稿。停在边际收益递减处,别过度工程化 prompt ——
  优先用后处理校验脚本兜底,而不是把规则全堆进 prompt。
- **改归并/校验/后处理代码**:保持纯确定性,不得引入二次模型调用。
- **改清洗/拆章规则**:动 NOISE_PATTERNS / CHAPTER_PATTERNS 后,在多个结构不同的样本上验证不误删/误切。
- **验证产物**:对照 `samples/full_run/` 的三层结构;改落盘逻辑先核 `storage.py` 路径契约。
- **提交方式**:严肃改走 feature 分支 + PR + squash merge;多文件改用一次原子 commit,
  不要 N 次写 main 产生中间红 commit。

## 9. 部署相关(本框架在 AI-Reader-V2 中的位置)

- 默认直连 Ollama `127.0.0.1:11434`;线上经 ops 平台 / 隧道调用时替换 `call_model()`。
- 可视化 `server.py` 纯标准库,可独立起在任意有 output/ 与原文的机器上。
- 改部署/服务配置前报计划等批准(L4 自治档:改 server 配置属"先告诉用户等 OK"类)。

## 10. 可视化前端(web/)· 零依赖纪律豁免

new-design 版的可视化前端独立工程 `web/`(Vite + React),**豁免本仓库「零三方依赖」纪律**——
这是经用户批准的有意决策,仅限可视化层:

- **豁免范围**:仅 `web/`(前端构建链 node/npm/Vite)。**后端 API `pipeline/server.py` 仍纯标准库**,不得引入三方依赖。
- **产物契约**:`npm run build` → `pipeline/static/`。`server.py` 优先托管该目录;`static/` 不存在时回退内嵌 `FRONTEND` 字符串(旧机器/无构建环境仍可独立起)。
- **base 可配**:开发期挂 `8443/new`(`VITE_BASE=/new/` + `server.py --base-path=/new`);成熟后迁顶层只改这两处配置,不改代码。
- **部署形态**:nginx 反代 `8443/new` 透传前缀 → 新起的 server.py 实例(开发约定内部端口 8081)。改部署/nginx 仍按 §9 报计划等批准。
- **旧前端**:`server.py` 内嵌 `FRONTEND` 保留作回退,不删;新功能在 `web/` 做。

## 11. 3B 收口:独立应用包 app/

new-design 已收口为独立可部署应用,根目录 `pipeline/` `web/` `model/` `prompts/` **已移入 `app/`**:
```
app/
  server/    合并后端(Flask 单服务):main.py(create_app+CLI)、readonly.py(只读逻辑)、static/(Vite 产物)
  pipeline/  分析管线(app.py 全流程 + 各阶段模块 + validate)
  prompts/   12 prompt   model/  schema+文档   web/  前端(产物→server/static/)
  requirements.txt  run.sh  README.md
```
- **后端合并**:原 server.py(只读,纯标准库)+ tasks.py(任务,Flask)→ `app/server/main.py` **单 Flask 服务单端口**,同前缀下提供只读 API + 任务 API + 静态。纯标准库纪律在合并后端不再适用(已用 flask)。
- **前端单 base**:`/api` 同时含只读与任务端点;产物输出 `app/server/static/`。
- **启动**:`cd new-design && python3 -m app.server.main --output app/output --raw app/raw --jobs app/jobs --base-path /new --port 8080`(或 `app/run.sh`)。
- **保留在根**(非应用包):samples/、research/、docs/、tools/、AGENT.md 等开发参考。
- **真 ollama 推理**:管线经 `OLLAMA_URL`(默认 18434 隧道)调用;隧道恢复即可端到端跑分析。

## 12. 多小说库(取代单一 output)

上传 txt/zip → 按小说独立存储/分析/浏览。根治"分析完看不到结果"(旧:任务产物落 jobs/,只读读主 output/,数据源不一致)。

**数据布局(LIB 根 = `app/`):**
```
raw/<slug>.txt 或 raw/<slug>/        原始(zip 解压进目录)
input/<slug>/chNN.txt                所有原文逐个清洗+拆章,全局重排
output/<slug>/meta.json              {novel_name, author, source_type, uploaded_at, stage, 进度字段}
output/<slug>/chNN/                  每章中间结果
output/<slug>/global/                global 结果
```
- **slug** = 安全化小说名(去后缀 + 替换 `/\:*?"<>|` 与空白);原始名存 meta.json。
- **重传同名 → 409**。
- **端点**:`/api/upload`(txt/zip)、`/api/analyze/<slug>`、`/api/progress/<slug>`、`/api/novels`;只读端点(summary/graph/events/chapters/reader/dimension/node)全支持 `?novel=<slug>`,缺省取最近上传。
- **readonly.py**:`use_novel(slug)` 上下文管理器加锁按小说装入模块全局(build_* 零改动);`set_library(lib)` 启用库模式;`list_novels()` 读各 meta.json。
- **前端**:全局当前小说状态(App.jsx);阅读页左栏顶部小说选择器,所有视图(图谱/阅读/时间线/场景)跟随;Upload 改 txt/zip 文件流。
- 入口参数改为 **`--lib <app目录>`**(取代 §11 的 `--output/--raw/--jobs`)。

## 13. 生产部署(wangcai · 8543)

独立部署,与 ubuntu 老版本(8011/8443)及平台配置完全隔离。

- **工作区**:`/home/aiops/ai-reader-app/`(库根 = 其下 `app/`)。
- **venv**:`/home/aiops/ai-reader-app/.venv`(get-pip 引导,因系统无 ensurepip);flask 装在此。
- **systemd**:`ai-reader-new.service`(enabled,开机自启 + 崩溃重启)。
  ExecStart:`.venv/bin/python3 -m app.server.main --lib .../app --static .../app/server/static --base-path "" --port 8081`,Environment `OLLAMA_URL=http://127.0.0.1:18434`。监听 127.0.0.1:8081。
- **nginx**:`/etc/nginx/sites-available/ai-reader-new`(独立文件,**不碰平台的 f.xbot.cool 配置**),listen 8543 ssl,复用 letsencrypt f.xbot.cool 证书,login-gated 复用 :8765(同 8443),`location /` → proxy_pass 127.0.0.1:8081,proxy_read_timeout 3600s。
- **前端构建**:`cd app/web && VITE_BASE=/ npm run build` → `app/server/static/`。
- **访问**:`https://f.xbot.cool:8543/`(需登录,复用 dashboard 密码)。
- **流程改代码/数据后 redeploy**:覆盖文件 → 重建前端 → `sudo systemctl restart ai-reader-new`;改 unit 需 daemon-reload。改 nginx 需 `nginx -t` 后 reload。
- **待确认**:8543 外网可达性(云安全组/防火墙)未验证。
- **运维红线**:改 systemd/nginx = L4 需批准;防火墙 = 最高档;不碰 f.xbot.cool 平台配置、ubuntu 老版本、8011/8443。
