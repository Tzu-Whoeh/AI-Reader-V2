# 分析任务层(M2)

独立应用的"上传 → 启动分析 → 进度"后端。包装 `app.py` 的全流程管线,**不改其分析逻辑**。

## 组成
- `tasks.py` — Flask 任务层:upload / analyze / progress / jobs。
- `app.py` — 既有 CLI 管线,M2 仅做两处最小改动:
  - `call_model` 的 ollama 端点改为可配 `OLLAMA_URL`(默认 `127.0.0.1:18434` 隧道,非生产 11434)。
  - `run()` 增加可选 `progress_cb` 回调,任务层据此写 `progress.json`(原子写)。纯 CLI 行为不变。

## 端点
| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /api/upload | 上传文本(multipart file 或 raw body)→ {job_id} |
| POST | /api/analyze/<job_id>[?presplit=1] | 后台异步触发分析 |
| GET | /api/progress/<job_id> | 进度 {stage, done, total, chapters[], counts?, error?} |
| GET | /api/jobs | 任务列表 |

产物落 `JOBS_DIR/<job_id>/output/`,其 `global/` 可被只读 `server.py` 直接消费。

## 运行
```bash
OLLAMA_URL=http://127.0.0.1:18434 python tasks.py --port 8090 --jobs ./jobs
```

## 进度 stage 流转
`uploaded → analyzing(逐章) → aggregating → done`(失败章隔离,记入 chapters[].error,不中断全局聚合)。

## 验证状态
- ✅ 全链路(upload→analyze→async→progress→done→产物)经 mock call_model 实测跑通:
  单章产出 2人物/1物品/1地点/1场景,progress 逐章上报正确,失败章隔离正确。
- ⏳ **真 ollama 推理未验证**:wangcai 18434 隧道当前 down(探测无监听)。隧道恢复后,
  设 `OLLAMA_URL` 指向隧道即可接真模型,无需改码。
