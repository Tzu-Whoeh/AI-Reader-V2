# 物品分析(两-pass 架构)· 说明文档

中文叙事文本物品分析的完整方案。把任务拆成两个独立、各自可稳定收敛的子任务,再用一个带硬校验的管道合并,避免单 prompt 多目标时"加一个约束、崩两个旧能力"的相互干扰。

## 为什么拆 pass

早期单 prompt 版本(物品分析 V1–V6)在叠加"共指 + 分类 + 归属 + 部件关系 + 成套关系 + 统称不脑补"六个目标后,出现严重相互干扰:每修一个目标就破坏另一个(如修服装脑补→环境排除松动)。35b 的指令遵循容量有限,目标越多越互相挤占。

拆分后:每个 pass 目标单一、提示词短、可独立验证;后一个 pass 只读前一个 pass 的固定输出,协调一致由"引用而非重新生成"保证。

## 文件清单

| 文件 | 作用 |
|---|---|
| `物品分析_Pass1_抽取共指分类.txt` | Pass1 提示词:抽取物品 + 共指归并 + prop/set 分类,给每项分配 id |
| `物品分析_Pass2_关系标注.txt` | Pass2 提示词:在 Pass1 固定清单上标 part_of(部件/容器)+ set_group(成套),带 confidence |
| `物品分析_合并管道.py` | 合并脚本:跑两 pass + 两道硬校验,输出最终结构 |

## 数据流

```
原文 ──Pass1──> {items:[{id,name,category,mentions,owner,...}]}
                      │
原文 + items清单 ──Pass2──> {relations:[{id,part_of,set_group}]}
                      │
              merge + 两道硬校验
                      │
         最终: items 每项带 part_of / set_group
```

## 两道硬校验(确定性,无模型)

这是架构可靠性的根本保障,把模型的偶发幻觉拦在最终输出之外:

1. **锚点校验**:每个 `mention` 必须逐字出现在原文(`mention in text`),否则剔除并记入 `_validation.dropped_mentions`。若某物品 name 和所有 mention 都不在原文 → 标记"疑似幻觉物品"。这条彻底封死了"散落的衣物→脑补出旗袍/丝袜/高跟鞋"这类内容幻觉。
2. **id 引用校验**:`part_of.whole_id` 必须指向存在的 id 且非自指,否则该关系作废、置 null,记入 `dropped_relations`。因为 Pass2 只能引用 Pass1 已有的 id,**机制上无法凭空创造新物品**。

## 调用配置

两个 pass 同配置:模型 `huihui_ai/Qwen3.6-abliterated:35b`,`temperature 0.12`,`format:"json"`,`num_ctx 8192`,`think:false`,`stream:false`。

管道脚本里 `call_model()` 给的是通用 HTTP 版(直连 `127.0.0.1:11434`);若经 ops 平台 exec 调用,替换该函数即可(base64 分块上传 payload + 本地 curl)。

## 最终输出结构

```json
{
  "item_count": 10,
  "items": [
    {
      "id": 7,
      "name": "手枪",
      "category": "prop",
      "mentions": ["枪袋里的手枪"],
      "owner": "",
      "part_of": {"relation": "container", "whole_id": 6, "confidence": "high"},
      "set_group": "",
      "function": "...",
      "confidence": "high",
      "note": ""
    }
  ],
  "_validation": {
    "dropped_mentions": [{"id": 9, "name": "卷烟纸", "dropped": ["(一张)卷烟纸"]}],
    "dropped_relations": []
  }
}
```

`part_of.relation` 取值:`part`(部件,如 车牌 part 轿车)/ `container`(容器内含,如 手枪 container 枪袋)。
`set_group`:同一套/同一批物品共享的组名(原文逐件列出时才标)。

## 验证结论

- **Pass1**(抽取/共指/分类):文本 A、B 各跑均 10 项,id 连续唯一,共指正确(雪佛来三说法、烙铁三态归一),环境排除干净,**锚点全命中**。这是整套方案最稳的基座。
- **Pass2**(关系):手枪→枪袋(container)、车牌→轿车(part)等清晰关系稳定判对;**id 引用完整性始终 ✓**(零脑补)。
- **端到端管道**:合并结构正确,锚点闸成功剔除了 Pass1 偶发的幻觉 mention("(一张)卷烟纸"),confidence 透传到最终输出。

## 已知局限(不粉饰)

1. **container 关系会过度标注**:35b 倾向把"空间接近/有过接触"判成容器内含(如"烙铁扔进火盆"被判 container,"水果糖放进衣兜"+"穿外衣"被误连)。已加"临时动作/捆绑/放置不算"的排除规则,仍无法根治——这是模型语义判断的天花板。
   → **应对**:`part_of` 视为**建议关系**,带 confidence 输出,**交人工复核**,不作可直接信任的结论。误判类型单一(过度标注而非漏标),复核时一眼可否决。
2. **confidence 未完全校准**:部分误判仍被标 high。medium 能捞出一部分可疑项(如绳子→刑凳),但不是可靠过滤器。
3. **人/物边界**:Pass1 偶尔把"司机"这类人误收为物品 → 后处理可对照人物识别结果排除。
4. **平台 500**:经 ops exec 调用时偶发响应缺 `stdout`,管道已内置 `sleep 30 + 重试`。

**总原则**:`mention`/`name` 经锚点校验后可信;`part_of` 关系是建议,信 high、复核 medium、人工终裁。
