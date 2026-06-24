# AI Reader (new-design) · 独立应用

一个完整的中文叙事分析应用:**上传文本 → 启动分析 → 看进度 → 阅读(人物/物品/地点高亮+点击属性)+ 图谱/时间线/场景**。
不依赖根目录 v2 代码;`app/` 是可独立部署的包。

## 结构
```
app/
  server/        合并后端(Flask 单服务):只读 API + 任务 API + 静态托管
    main.py      入口(create_app + CLI)
    readonly.py  只读逻辑(graph/reader/dimension/node/summary/events)
    static/      Vite 产物(npm run build 生成)
  pipeline/      分析管线(app.py 全流程 + 各阶段模块 + validate)
  prompts/       12 个分析 prompt
  web/           前端(Vite+React);产物 → server/static/
  model/         领域模型 schema + 文档
  requirements.txt  run.sh  README.md
```

## 一次性构建前端
```bash
cd app/web && npm install && VITE_BASE=/new/ npm run build
# 产物输出到 app/server/static/
```

## 启动(单服务单端口)
```bash
cd app && OLLAMA_URL=http://127.0.0.1:18434 ./run.sh 8080 /new
# 访问 http://127.0.0.1:8080/new/
```
或直接:
```bash
cd new-design && python3 -m app.server.main --output app/output --raw app/raw \
  --jobs app/jobs --base-path /new --port 8080
```

## 端点(全部挂在 base 前缀下)
- 只读:`/api/summary|graph|events|chapters|reader/<ch>|dimension/<name>|node/<type>/<id>`
- 任务:`/api/upload | /api/analyze/<job> | /api/progress/<job> | /api/jobs`
- 静态:`/`(Vite 产物,缺失则回退内嵌前端)

## 迁顶层
`VITE_BASE=/ npm run build` + `--base-path ""`,无需改码。

## 依赖
后端仅 flask(见 requirements.txt);前端见 web/package.json。
