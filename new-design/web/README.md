# 叙事档案浏览器 · 前端(Vite + React)

new-design 版 AI Reader 的可视化前端。与根目录老版本完全独立;开发期挂在
`8443/new` 下,成熟后迁顶层路径(改 base 配置即可,无需改代码)。

> ⚠️ 纪律豁免:本目录(`web/`)是可视化层,豁免仓库「零三方依赖」纪律,
> 走 Vite 构建。后端 API(`pipeline/server.py`)仍保持纯标准库。详见 AGENT.md §9。

## 开发
```bash
cd new-design/web
npm install
npm run dev          # http://127.0.0.1:5173/new/
```
开发期 dev server 把 `/new/api/*` 透传到本地后端(server.py --base-path=/new,起在 :8081)。

## 构建
```bash
npm run build        # 产物输出到 ../pipeline/static/
```
产物由 server.py 静态托管。

## base 路径(可配)
- 开发/部署在 `/new`:默认 `VITE_BASE=/new/`。
- 迁顶层:`VITE_BASE=/ npm run build`,后端 server.py 改 `--base-path=/` 或留空。

## 结构
```
web/
  index.html
  vite.config.js        # base 可配;build.outDir → ../pipeline/static;dev proxy → :8081
  src/
    main.jsx
    App.jsx             # 顶栏 + 筛选 + 图谱 + 详情面板 布局
    api.js              # fetch 封装,路径跟随 base
    theme.css           # 叙事档案配色(从旧前端平移)
    components/
      Filters.jsx       # 类型筛选
      GraphPane.jsx     # 力导向关系图(平移旧逻辑,参数对齐)
      SidePanel.jsx     # 节点详情 + 原文出处(已修正则转义)
    views/
      Timeline.jsx      # 占位 · 待实现
      Scenes.jsx        # 占位 · 待实现
```

## 当前状态(骨架阶段)
- ✅ 关系图 + 详情面板平移跑通(对接现有 4 个 API)。
- ⬜ Timeline / Scenes 仅占位。
- ⬜ 图谱增强(物品边、事件节点)、拖拽/缩放、搜索 —— 后续迭代。
