# UI 设计规格 · AI-Reader-V2(new-design)

> 逆向自 `app/web/`(Vite + React)实际源码。每条带**可验证依据**(文件:符号)。
> 与代码冲突处以代码为准。本文档描述前端**当前真实形态**,非前瞻设计稿。
>
> 验证基线 commit:`9e287e84`(main)。复核命令示例见每节末「验证」。

## 0. 技术栈与构建(可验证)

| 项 | 值 | 依据 |
|---|---|---|
| 框架 | React 18.3 + ReactDOM 18.3 | `web/package.json` dependencies |
| 构建 | Vite 5.4 + `@vitejs/plugin-react` 4.3 | `web/package.json` devDependencies |
| 运行时 UI 依赖 | **仅 react / react-dom**(无路由库、无组件库、无图表库、无状态库) | `web/package.json` |
| 入口 | `index.html` → `/src/main.jsx` | `web/index.html` |
| 渲染根 | `createRoot(#root)`,包 `StrictMode` + `ErrorBoundary` | `main.jsx` |
| 样式 | 单文件 `theme.css`(原生 CSS + CSS 变量,无预处理器/Tailwind) | `main.jsx` import |
| base 前缀 | `VITE_BASE`(默认 `/new/`) | `vite.config.js` |
| 产物输出 | `../server/static`(= `app/server/static/`),`emptyOutDir` | `vite.config.js` build.outDir |
| 开发代理 | `/new/api` → `http://127.0.0.1:8080` | `vite.config.js` server.proxy |
| dev 端口 | 5173 | `vite.config.js` |

> 验证:`cat app/web/package.json app/web/vite.config.js`。

## 1. 应用结构与导航(可验证)

**单页应用,无路由库**。视图切换由 `App.jsx` 的 `view` 状态控制(`useState('graph')`),
而非 URL 路由。五个顶层视图(`App.jsx` 常量 `VIEWS`):

| key | 标签 | 组件 | 依据 |
|---|---|---|---|
| `library` | 书库 | `views/Library.jsx` | App.jsx import + 条件渲染 |
| `graph` | 图谱 | `components/GraphPane.jsx` + `Filters` + `SidePanel` | App.jsx `view==='graph'` |
| `reader` | 阅读 | `views/Reader.jsx` | App.jsx `view==='reader'` |
| `timeline` | 时间线 | `views/Timeline.jsx` | App.jsx `view==='timeline'` |
| `scenes` | 场景 | `views/Scenes.jsx` | App.jsx `view==='scenes'` |

默认视图 `graph`。顶栏含标题「叙事档案 / NARRATIVE BROWSER」、视图按钮组(`nav.views`)、
统计串(`X人物 · X物品 · X地点 · X事件 · X章`)。窄屏视图按钮折叠为汉堡菜单(`nav-toggle ☰` + `navOpen` 状态)。

> 验证:`grep -n "VIEWS\|view ===\|navOpen" app/web/src/App.jsx`。

## 2. 组件树(可验证)

```
main.jsx
└─ ErrorBoundary                         (main.jsx,渲染异常兜底,见 §7)
   └─ App                                (App.jsx,全局状态 + 视图路由 + 任务轮询)
      ├─ [top bar]  标题 / VIEWS 导航 / stat / 全局进度条 gjob
      ├─ view=graph:
      │   ├─ Filters                     (components/Filters.jsx,三类型显隐复选)
      │   ├─ GraphPane                   (components/GraphPane.jsx,力导向 SVG 图)
      │   └─ SidePanel                   (components/SidePanel.jsx,节点详情 + 原文出处)
      ├─ view=timeline → Timeline        (views/Timeline.jsx)
      ├─ view=scenes   → Scenes          (views/Scenes.jsx)
      ├─ view=reader   → Reader          (views/Reader.jsx)
      └─ view=library  → Library         (views/Library.jsx)
                            └─ RulesPanel (views/RulesPanel.jsx,规则编辑模态)
```

ℹ️ **`views/Upload.jsx` 曾是死代码,已在 `fix/ui-gaps` 删除**(无引用,上传 UI 内联于
`Library.jsx` 的 `uploadFile`+`startAnalyze`)。组件树不再包含独立 Upload 视图。

## 3. 状态管理(可验证 · 无 Redux/Context store)

全应用状态用 `useState`/`useRef` 提升到 `App.jsx`,视图为受控子组件。关键全局状态(`App.jsx`):

| 状态 | 含义 | 依据 |
|---|---|---|
| `view` | 当前视图 key | App.jsx:31 |
| `novel` | **当前小说 slug,所有视图跟随** | App.jsx:34 |
| `novels` | 书库列表 | App.jsx:33 |
| `summary` / `graph` | 概览统计 / 全局图数据 | App.jsx:27-28 |
| `show` | 图谱三类型显隐 `{character,item,location}` | App.jsx:29 |
| `selected` | 图谱选中节点 `{type,id,label}` | App.jsx:30 |
| `job` + `pollRef` + `jobSlugRef` | **应用级进行中任务 + 唯一轮询定时器** | App.jsx:37-39 |

**轮询设计(单一真相)**:任务进度轮询提到 App 层(`startPolling`,`setInterval` 1000ms),
唯一定时器;切视图不中断;实时 `stage` 同步进对应书库卡片(避免顶栏与卡片状态打架);
终态(`done`/`error`/`interrupted` 或 `running===false`)清定时器并拉权威列表。
启动时扫描未完成任务自动重连轮询(刷新页面也能恢复)。
> 验证:`grep -n "startPolling\|pollRef\|jobSlugRef\|TERMINAL" app/web/src/App.jsx`。

## 4. API 层(可验证 · `web/src/api.js`)

单后端单 base:`API = import.meta.env.BASE_URL.replace(/\/$/,'') + '/api'`。
读类统一拼 `?novel=<slug>`(`nq()` 辅助)。封装函数与端点一一对应(见模块规格 §2.1)。

**两个工程细节**:
- 写类请求统一用 `Content-Type: text/plain`,配合后端 `get_json(force=True)` 接受——
  **规避 CORS 预检**(application/json 会触发 preflight)。依据:api.js:31 注释。
- 错误处理:非 2xx 抛 `Error`,优先取响应体 `.error` 字段,挂 `e.status` 供调用方区分(如 409)。

> 验证:`grep -n "text/plain\|e.status\|nq(" app/web/src/api.js`。

## 5. 视图规格(逐视图,可验证)

### 5.1 图谱 Graph(GraphPane + Filters + SidePanel)
- **布局算法**:自实现力导向(`computeLayout`),非三方库。要点(GraphPane.jsx:10-86):
  归一坐标系 `[0,1]` 求解(resize 不重算物理,仅重映射像素);**网格近似斥力**(仅邻近 ±1 格参与,
  O(n²)→近 O(n));收敛即停(能量 `< 1e-6` 提前结束);迭代上限自适应 `min(300,max(80,4000/√n))`。
- **布局缓存**:按「节点 id 集合 + 边数」缓存(`layoutKey`),筛选只隐藏不重算物理(GraphPane.jsx:88-120)。
- **渲染**:纯 SVG `<line>`/`<circle>`/`<text>`;节点半径按类型(character 9 / organization 8 / event 5 / 其余 6);
  自环边过滤(`e.from!==e.to`)。
- **Filters**:五类型(character/item/location/event/organization)显隐复选,默认全开;
  各类节点均可显隐。依据:App.jsx `TYPES`/`show` 五键 + Filters.jsx `TC` 五色(`fix/ui-gaps` 后)。
- **SidePanel**:点节点 → `getNode(type,id,novel)` → 列原文出处;高亮 term 用 `escapeRe` 正则转义
  (修旧前端 `new RegExp(term)` 未转义隐患)。依据:SidePanel.jsx:4-9。

> 验证:`grep -n "computeLayout\|layoutKey\|escapeRe\|r = n.type" app/web/src/components/*.jsx`。

### 5.2 阅读 Reader(views/Reader.jsx)
- 章节列表(`getChapters`)+ 单章原文与高亮(`getReader(ch,novel)`,返回 `{text,highlights}`)。
- 点高亮 → 节点详情(`getNode`);维度数据按需缓存(`dims` 状态 + `getDimension`)。
- 窄屏章节抽屉(`chOpen`);章内跳转落点脉冲动画(`jump` 状态 + CSS `occ-pulse` 2s 渐隐)。

### 5.3 时间线 Timeline(views/Timeline.jsx)
- `getEvents(novel)` 取事件;`getDimension('characters')` 解析参与人物名。
- **故事序/叙述序切换**(`order` 状态,默认 `story`):按 `story_order` 或 `narrative_order` 排序;
  标注倒叙、`storyline`、参与人物。依据:Timeline.jsx:9,26,40-44。

### 5.4 场景 Scenes(views/Scenes.jsx)
- `getDimension('scenes',novel)`;**功能标签可点击 → 跨章筛选**含同标签场景(`activeTag` 状态)。
- 标签来源 `s.tags.function`(清单内)+ `s.tags.function_novel`(清单外);筛选条带计数。
  依据:Scenes.jsx:12-14,30,38。

### 5.5 书库 Library(views/Library.jsx · 功能最重)
- 上传(txt/zip)→ `uploadFile`+`startAnalyze`;卡片网格展示每本书 stage(中文映射:
  分析中/全局聚合/已暂停/停止中/已中断/已分析/部分完成/出错…)。
- 卡片操作:开始/暂停/恢复分析、打开(跳 reader)、编辑 meta、删除(二次确认 `confirmDel`)、
  重新清洗 `reclean`、规则面板(全局/单本两模式)。点卡片放大看分析统计(`getSummary`)。
- 内嵌 `RulesPanel`:规则增删改(`saveCustomRule`)、默认勾选(`setDefaultRules`)、
  用户预设存删(`saveUserPreset`);单本模式支持「继承全局默认」(`inheriting`)。
  依据:Library.jsx:2,7,55,69-118;RulesPanel.jsx:2,28,56-95。

## 6. 视觉设计语言(可验证 · `theme.css`)

**主题:档案/复古做旧(sepia archival)**。CSS 变量(`:root`,theme.css:2-8):

| token | 值 | 用途 |
|---|---|---|
| `--paper` | `#1a1714` | 主背景(深褐近黑) |
| `--paper2` | `#221d18` | 次级面板背景 |
| `--ink` | `#e8dcc8` | 主文字(米白) |
| `--dim` | `#9a8f7d` | 次要文字 |
| `--stamp` | `#a8332a` | 强调红(印章红,= character 色) |
| `--thread` | `#b8884a` | 线索金(= item 色) |
| `--line` | `#3a322a` | 分隔线 |
| `--char/--item/--loc` | `#a8332a / #b8884a / #6f9b8e` | 实体类型色 |

**实体配色全栈一致**(三处同值):`theme.css :root`、`Filters.jsx TC`、`GraphPane.jsx TC`。
GraphPane 另含 `event #9a7db8` / `organization #4a8fb8`(CSS 变量未覆盖,硬编码在 JSX)。

- **字体**:正文衬线中文 `"Songti SC","Noto Serif SC",serif`;元信息/标签用 sans-serif + 字距。
- **布局**:`body{height:100vh;overflow:hidden}` 全屏不滚;顶栏 + 内容区固定高度算式
  (`.main{height:calc(100vh - 52px - 41px)}`);SidePanel 固定宽 380px。
- **动效**:节点 hover 描边、`occ-pulse` 跳转脉冲(`@keyframes`,2s)、`color-mix` 混色 hover。
- **响应式断点**:`@media (max-width:768px)` 与 `@media (max-width:480px)` 两档。

> 验证:`sed -n '1,10p' app/web/src/theme.css`;`grep -n "@media" app/web/src/theme.css`。

## 7. 健壮性约定(可验证)

- **ErrorBoundary**:`main.jsx` 类组件包住 `<App>`,渲染异常显示可读栈(前 6 行)+ 「返回(清除错误)」,
  不再整页黑屏。对应工程纪律「黑屏先加 ErrorBoundary 暴露真实栈,再修真错误,勿猜 CSS」。
- **瞬时失败容忍**:轮询单拍异常忽略,下一拍重试(App.jsx 轮询 catch 空处理)。
- **空态/加载态**:各视图有 `err`/`loading` 状态与空态文案(如 SidePanel「未在原文中定位到出处」)。

> 验证:`grep -n "ErrorBoundary\|getDerivedStateFromError\|componentDidCatch" app/web/src/main.jsx`。

## 8. 缺口整改记录(已修)

以下 5 项在 `fix/ui-gaps` 整改完成。本节保留以备审计;后续如重新出现视为回归。

- ~~**Upload.jsx 死代码**~~ → **已删**:无引用,上传 UI 内联于 Library;移除该文件。
- ~~**Filters 只覆盖三类型**~~ → **已修**:`TYPES`/`show` 扩到 5 类(character/item/location/event/organization),
  Filters 渲染 5 个显隐开关,默认全开;event/organization 节点可显隐(App.jsx `show` + Filters.jsx `TC`)。
- ~~**event/org 颜色硬编码**~~ → **已修**:GraphPane 颜色收敛为单一来源(`TC` 节点表 + `EDGE_C`/`edgeColor()` 边表),
  并在 `theme.css` 新增 `--event/--org/--membership/--edge-org/--edge-char` 变量(JS 与 CSS 同值)。
- ~~**无 URL 路由**~~ → **已修**:加 hash 路由 `#/<view>/<novel>`(无路由库),支持深链、刷新保持、前进/后退;
  初始 hash 指定的小说在有效时优先于「最近上传」(App.jsx `parseHash`/`hashNovelRef`/`hashchange`)。
- ~~**图布局非确定**~~ → **已修**:`computeLayout` 的重叠微扰由 `Math.random()` 改为按节点下标的确定性偏移
  (`(ai*73856093)^(bi*19349663)`),同图多次渲染坐标一致。

附带后端补全:`readonly.py::node_anchors` 新增 `organization` 分支,使 org 节点点击后也能定位原文出处
(此前仅 character/item/location/event;org 入图后若不补会返回空出处)。

> 整改后仍未做(有意保留,非缺口):Filters 的 5 个开关无「全选/全不选」快捷;hash 路由不记录
> 图谱选中节点(`selected` 不进 URL,仅 view/novel 进)。

## 9. 与其它规格的关系

- 端点契约见**模块规格** §2.1 与 `app/model/API.md`;本文档只描述前端如何消费。
- 图谱四类边/节点映射、`is not None` 判空、`escapeRe` 见 `API.md`,前端已落地(SidePanel.escapeRe)。
- 用户故事(`requirements/02_user_stories.md`)中 US-4.x 的验收对应本文档视图行为。
