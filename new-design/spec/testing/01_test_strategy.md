# 测试规格 · AI-Reader-V2(new-design)

> 逆向自 `app/validate.py`、`tools/schema_check.py`、AGENT.md 工作纪律。
> 本系统测试分两半:**结构校验**(CI 侧 jsonschema)+ **语义校验**(运行时纯标准库 R1–R6),
> 外加提示词稳定性/泛化测试这一**经验性**验收口径。

## 1. 测试金字塔

```
       ┌──────────────────────────────┐
       │ 端到端:wangkai 实跑分析全本    │  人工 + meta partial/done 判定
       ├──────────────────────────────┤
       │ 提示词稳定性 / 泛化测试         │  同 prompt×3 跑 + 结构不同文本
       ├──────────────────────────────┤
       │ 语义校验 R1–R6(validate.py)   │  运行时,纯标准库
       ├──────────────────────────────┤
       │ 结构校验(schema_check.py)     │  CI,jsonschema(开发依赖)
       └──────────────────────────────┘
```

## 2. 结构校验(CI 侧)

工具:`tools/schema_check.py`,依赖 `jsonschema`(开发依赖,不进运行时后端)。

```
python tools/schema_check.py --global-dir output/<slug>/global --schema-dir app/model/schema
```

校验对:`global_characters/items/locations/timeline/scenes.schema.json` vs 对应 `*.json`。
全 PASS 返回 0,任一失败返回 1 并打印前 8 条错误(path → message)。校验类型/必填/枚举/形态。

API schema 也在 CI 侧用真实样本模拟响应跑通(summary/graph/node/events 全 PASS;
graph 用真实数据生成含事件层增强图 66 节点 43 边,验证契约补全了旧前端三缺口)。

## 3. 语义校验 R1–R6(运行时)

模块:`app/pipeline/validate.py`,**纯标准库**(后端零依赖红线)。实现 Schema 表达不了的跨字段语义。

```python
from validate import validate_global, ValidationReport
rep = validate_global(global_dir="output/<slug>/global", raw_by_chapter={1: "原文..."})
if not rep.ok: ...   # rep = {ok, errors:[Issue], warnings:[Issue]}, Issue={rule, path, detail}
```

| 规则 | 校验内容 | 失败标记 |
|---|---|---|
| R1 锚点逐字命中 | evidence/start_text/end_text/anchor 是原文逐字子串(去空白后) | `_anchor_miss`(不静默丢弃) |
| R2 引用完整性 | 所有 `*_id/*_ref/*_global` 非 null 时被指 id 必须存在 | `_dangling_ref` |
| R3 绝对时间纪律 | abs_interval 仅在文本有明确依据时填,否则必须 null | — |
| R4 歧义留痕 | 跨章疑似同体不能可靠缝合的进 ambiguities,不硬合并 | — |
| R5 provenance 自洽 | members 每个 (chapter,local_id) 可在该章找到;all_names ⊇ 成员名并集 | — |
| R6 枚举闭合 | enum 字段取值在声明集合内;自由文本(role/storyline/label)不校验 | — |

锚点匹配细节:evidence 内引号包裹的逐字片段(`_QUOTE`),片段内 `...`/`……` 视为省略切段分别匹配(`_ELLIPSIS`);
`_norm` 去空白后做子串比对。relation_type 枚举闭合集:
`{social,kin,affective,attitude,event,awareness,adjacency,containment,movement,remote}`,confidence `{high,medium,low}`。

## 4. 提示词稳定性 / 泛化测试(经验性验收)

改提示词的纪律(AGENT.md §8):
- **稳定性测试**:同 prompt 在 `samples/` 真实文本上跑 **3 次**,看输出一致性。
  场景拆分基准:6 文本×3 跑,**5/6 段数与 cut_reason 三跑一致**(27b)。
- **泛化测试**:在结构不同的文本上验证不退化。
- 停在边际收益递减处,别过度工程化 prompt;优先后处理校验脚本兜底,而非把规则堆进 prompt。
- 改 model-judgment 逻辑(合并/清洗 prompt)前,在 live wangcai 推理上做 3-run 稳定性检查再合。

LLM 复核层自身的稳健性保证:`entity_review`/`entity_clean` 用 **3 票多数自洽投票**防模型漂移;
带磁盘缓存(pair+profile-hash / word-level),仅新增项发起判定。

## 5. 场景拆分专项验收(判断类任务)

- 只在两类硬边界切(loc 物理移动 / time 往事回放);消歧统一标 time;内心独白并入当下场景。
- **不加合并类后处理**(实测放大漂移,裸 prompt 更稳)。
- 输出每段含 `cut_reason`(loc/time/start),让每一刀客观依据可审计。
- 已知 ±1 摆动场景(往事夹叙同地点 / 极密集时空跳转)是文本固有难度,**非 bug,不强加规则**。

## 6. 端到端验收口径

- 单章错误隔离:逐章 try/except,失败记 `chapter_error` 继续;**完结时据实复核**——有失败或未跑满则
  标 `partial`(`error_count`/`succeeded_count`/`partial_reason`/`first_error`),不一律 done。
- 断点续跑:已有 `_merged.json` 的章跳过,可重跑续跑。
- 历史基准(生产已验证一次):168 人物 / 2425 关系 / 0 id 越界 / 正确合并 / 无超级簇。
- 冷启动验收:首跑空缓存时增量聚合触发全量 LLM 判定(约 55 min)与章分析争 GPU 会拖垮管线;
  **先离线 warmcache(约 66 min)→ 用缓存聚合(近瞬时)**。缓存暖化必须先于 LLM 在热路径的正式跑。

## 7. 诊断纪律(踩坑)

- **黑屏/白屏 bug**:先加 `ErrorBoundary` 暴露真实 JS 栈,再修真错误,**绝不猜 CSS**。
- **实体过合并**:单章数据干净,所有 merge 问题源于跨章聚合阶段,**先查 cross_chapter**。
- 改 prompt 必须实跑验证(wangcai→ollama);提完 PR 不自动 merge,等用户发话。
