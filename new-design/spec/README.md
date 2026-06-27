# spec/ · AI-Reader-V2(new-design)规格文档

> **逆向规格**:本目录据 `new-design/app/` 实际代码逆向归纳,描述系统**当前真实形态**,
> 不是前瞻设计稿。任何与代码冲突处,**以代码为准**并提 issue 修文档。
> 领域数据模型的单一事实源仍是 `app/model/MODEL.md` + `app/model/schema/*.schema.json`;
> 本目录是面向「需求 / 架构 / 模块 / 测试 / 部署」五个切面的工程规格集。

## 目录

| 子目录 | 内容 | 主文档 |
|---|---|---|
| `requirements/` | 需求规格:产品目标、功能性/非功能性需求、可靠性红线、约束 | `01_product_requirements.md` |
| `architecture/` | 架构规格:系统分层、数据流、存储布局、模型适配、部署拓扑 | `01_system_architecture.md` |
| `modules/` | 模块规格:每个 pipeline / server 模块的职责、输入输出、依赖 | `01_module_catalog.md` |
| `testing/` | 测试规格:校验四道防线、CI 结构校验、提示词稳定性测试、验收口径 | `01_test_strategy.md` |
| `deployment/` | 部署规格:wangcai 生产部署、systemd/nginx、构建、运维红线、回滚 | `01_deployment_guide.md` |

## 与既有文档的关系

- `AGENT.md` —— agent 协作手册(红线/纪律/坑)。本 spec 不重复纪律细节,聚焦「系统是什么」。
- `README.md` / `APP_USAGE.md` / `BROWSER_USAGE.md` —— 使用说明。本 spec 聚焦「为什么这样设计」。
- `docs/01..07` —— 各维度抽取的设计随笔(scene/character/item/location/time/normalize/event)。
  本 spec 在模块章节引用它们,不复制。
- `app/model/` —— 领域模型 SSOT(MODEL.md / API.md / schema)。本 spec 引用,不另立模型。

## 一句话定位(摘自 AGENT.md)

中文叙事文本(网文/小说)结构化分析框架。核心原则:**模型做判断、代码兜底校验、不确定项交人工**。
