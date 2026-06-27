# 部署规格 · AI-Reader-V2(new-design)

> 逆向自 AGENT.md §9/§11/§13 与 `app/server/main.py`、`run.sh`、`requirements.txt`。
> 生产部署在 **wangcai · 8543**,与平台配置、ubuntu 老版本(8011/8443)完全隔离。

## 1. 部署形态总览

```
https://f.xbot.cool:8543/  (需登录,复用 dashboard 密码)
        │
   nginx  /etc/nginx/sites-available/ai-reader-new  (独立文件,不碰平台 f.xbot.cool 配置)
     listen 8543 ssl,复用 letsencrypt f.xbot.cool 证书
     login-gated 复用 :8765(同 8443)
     location / → proxy_pass http://127.0.0.1:8081  (proxy_read_timeout 3600s)
        │
   systemd  ai-reader-new.service  (enabled:开机自启 + 崩溃重启)
     ExecStart: .venv/bin/python3 -m app.server.main \
                  --lib   /home/aiops/ai-reader-app/app \
                  --static /home/aiops/ai-reader-app/app/server/static \
                  --base-path "" --port 8081
     Environment: OLLAMA_URL=http://127.0.0.1:18434
     监听 127.0.0.1:8081
        │
   ollama 隧道 127.0.0.1:18434  (注意:非生产 app.py 历史写死 11434)
     模型 huihui_ai/Qwen3.6-abliterated:35b / :27b
```

## 2. 工作区与运行环境

- **工作区**:`/home/aiops/ai-reader-app/`(库根 = 其下 `app/`)。
- **server uid**:1002(aiops),passwordless sudo。
- **venv**:`/home/aiops/ai-reader-app/.venv`。系统无 ensurepip,用 get-pip 引导;flask 装在此。
- **依赖**:`app/requirements.txt`(后端运行时仅 flask;jsonschema 是开发/CI 依赖,不进运行时)。

## 3. 数据布局(库根 = app/)

```
app/raw/<slug>.txt | raw/<slug>/      原始(zip 解压进目录)
app/input/<slug>/chNN.txt             清洗+拆章后各章原文
app/output/<slug>/meta.json           小说元数据 + 进度状态
app/output/<slug>/chNN/_merged.json   每章中间结果
app/output/<slug>/global/*.json       global 结果(+ 原子提交临时目录)
app/output/<slug>/.review_cache/{review,clean}.json   LLM 人物复核/清洗磁盘缓存(在 novel_root 即 output/<slug>/ 下,非 global/ 内)
```

## 4. 前端构建

```
cd app/web && VITE_BASE=/ npm run build      # 产物 → app/server/static/
```

`server/main.py` 优先托管 `static/index.html`(Vite 产物);不存在则回退 `readonly.py` 内嵌 `FRONTEND`。

## 5. 本地/开发启动(对照)

```
# 开发期挂 8443/new 前缀:
cd new-design && python3 -m app.server.main \
  --lib app --static app/server/static --base-path /new --port 8081
# 或单库简易:OLLAMA_URL=... python -m app.server.main --lib <app目录> --base-path "" --port 8080
# app/run.sh 封装了默认启动参数。
```

入口参数以 **`--lib <app目录>`** 为准(取代早期 `--output/--raw/--jobs`)。

## 6. 改代码/数据后 redeploy

```
1. 覆盖文件(repo/put 或直接 scp/写盘)
2. 重建前端(若动了 web/):cd app/web && VITE_BASE=/ npm run build
3. sudo systemctl restart ai-reader-new
   - 改了 systemd unit:先 sudo systemctl daemon-reload
   - 改了 nginx:先 sudo nginx -t 通过后 sudo systemctl reload nginx
```

## 7. 暖缓存先行(冷启动纪律)

LLM 人物清洗/复核在跨章聚合热路径时,首跑空缓存会触发对全部新词/新对的模型判定,
与逐章分析争抢同一块 GPU,可能拖垮管线(历史现象:增量聚合的全量判定耗时与章分析叠加)。

**注:仓库当前无独立的 warmcache 脚本**;暖缓存是一种**运行策略**,不是现成命令。其原理:

```
缓存载体: output/<slug>/.review_cache/{review,clean}.json
          —— entity_review/entity_clean 命中即复用,仅新词/新对发起模型判定。
策略:    先让聚合(aggregate.aggregate,带 call_model + novel_root)在不与章分析
          抢 GPU 的时机跑一遍,把 .review_cache 填满;之后正式跑/重建 global 时
          判定多为缓存命中,近瞬时,不再与章分析竞争。
```

实现方式(任选其一,均用现有代码,不需新脚本):
- 先单独触发一次跨章聚合(章分析空闲时),填充缓存,再正式重跑;或
- 若要一键化暖缓存,需**单独提 PR 新增 `warmcache.py`**(属功能,不在本规格范围)。

缓存暖化应先于「LLM 判定在热路径」的正式运行。

## 8. 运维红线(L4 自治档)

| 操作 | 档位 |
|---|---|
| 读端点 / 诊断 exec / 写 feature 分支 / CI 查询 | 直接干(事后报) |
| 写 main / 删东西 / 改服务器配置 / 部署 / 跑 ollama 推理 | 先报计划等 OK |
| pr/merge / 重启主机 | 显式批准才做 |
| 改 systemd / nginx | L4 需批准 |
| 改 sshd / 防火墙 | 最高档,显式批准 |

**绝不触碰**:平台 f.xbot.cool 配置、ubuntu 老版本、8011/8443 端口、平台自身仓库与密钥端点。

## 9. 待确认 / 风险

- **8543 外网可达性**(云安全组/防火墙)未验证。
- 生产 `app.py` 默认 OLLAMA 端口与隧道端口不一致(写死 11434 vs 隧道 18434),
  生产经 `OLLAMA_URL=http://127.0.0.1:18434` 环境变量覆盖,改部署时务必保留该 Environment。
- 跨章并查集 O(n²),超长全本注意性能。

## 10. 回滚

- 代码:`git revert` 对应 PR 或切回上一 tag → 覆盖 → 重建前端 → restart。
- 数据:`global/` 原子提交(`commit_global` 用 `os.replace` + `global.swapold` 暂存),
  半成品不会污染正式 global;单本损坏可删 `output/<slug>/` 重新分析(断点续跑)。
- 服务:`systemctl` enabled,崩溃自动重启;`systemctl status/restart ai-reader-new` 排障。
