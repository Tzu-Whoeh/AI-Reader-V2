# 叙事档案浏览器 · 使用说明

带后端的本地 Web 服务,读取 `output/` 分析产物 + 原文,提供交互式浏览:
- **总览图**:全局实体关系网络(人物/物品/地点),可按类型筛选、力导向布局、缩放。
- **下钻**:点击任一节点 → 右侧面板显示该节点详情 + **它在原文的所有出处**(锚点定位的句子,关键词高亮)。

## 启动
```bash
python server.py --output output/ --raw raw_chapters/ --port 8080
# 浏览器打开 http://127.0.0.1:8080
```
- `--output`:app.py 生成的分析产物目录(含 global/ 与 chNN/)。
- `--raw`:按章拆分的原文目录(chNN.txt),用于"节点→原文出处"反查。
- 仅用 Python 标准库,无三方依赖。

## API
- `GET /api/summary` 概览统计 + 章节列表
- `GET /api/graph` 全局节点 + 边
- `GET /api/dimension/<name>` 某维度全局数据(characters/items/locations/timeline/scenes)
- `GET /api/node/<type>/<id>` 节点详情 + 原文出处(occurrences)

## 原文出处的实现
每个实体的锚点(人物 all_names、物品 name+mentions、地点 all_names、事件 anchor_text)
在各章原文里做字符串定位,返回含该词的句子。泛指代词(他/她/单字)已过滤以减少误命中。

## 担大部头
后端按需读取、不内嵌全量数据到页面,适合多章长篇;前端只在点击时请求单节点出处。
