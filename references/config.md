# 简历筛选评分系统 — 配置参考

## 飞书 Base 信息

| 项目 | 值 |
|------|----|
| Base URL | https://g4wt0dn9mss.sg.larksuite.com/base/JbkRbkGf6aAqfnsCDHHlJMjbg3b |
| base-token | JbkRbkGf6aAqfnsCDHHlJMjbg3b |
| 主数据表 table-id | tbll1fWOund3PSgd |
| 飞书 App ID | cli_a9361aaf32619eed（bot 身份） |

## 关键字段 ID

### 输入字段（VM 填写）
| 字段名 | Field ID | 类型 |
|--------|---------|------|
| 姓名 | fldSAfsOJf | text |
| 语言对 | fldBvHUo5K | select |
| 简历 | fld7W0W7e2 | attachment |
| 人工翻译单价 | fldS6L635G | number |
| AIPE单价 | fld1S3tCII | number |
| 报价商议空间 | fldVAMT8Pz | select |
| 提供的服务 | fld9GdKXnB | select（多选） |
| 项目经历 | fldaQKJa1J | text |
| 其他相关经验 | fldjMCovnE | text |
| 熟悉的IP | fldZZftCZ0 | text |

### LLM 解析字段（parse_resumes.py 写入，可手动纠正）
| 字段名 | Field ID | 类型 | 说明 |
|--------|---------|------|------|
| 解析字数 | flduKRhgTV | number | 游戏翻译实际字数，手动纠正直接改这里 |
| 解析年限 | flde0kTB3Z | number | 游戏翻译从业年限 |
| 解析项目数 | fldfpo5X1f | number | 游戏项目数量 |
| 解析知名实体 | fld3cWjCaA | text | 知名游戏/厂商/LSP，逗号分隔 |
| 简历解析时间 | fldh8Ebrxl | datetime | 最后一次解析时间 |

### 评分输出字段（rescore_and_write.py 写入）
| 字段名 | Field ID | 类型 |
|--------|---------|------|
| 总分 | fldSAqhqXF | number |
| 初始评级 | fldzclgjwZ | select |
| 有效简历 | fldUNWHXoU | select |
| 评分依据 | fldl0mRETk | text |
| AI建议 | fldrIjaOr9 | text |
| 招募状态 | fldfp6Pn7l | select |

## 评分引擎路径

| 文件 | 路径 |
|------|------|
| 引擎主文件 | `/Users/dataozi/Downloads/resource-management-scripts/scripts/resume_screening_engine_v2.py` |
| 价格规则 | `/Users/dataozi/.openclaw/workspace/scripts/pricing_rules.json` |
| PDF 缓存目录 | `/tmp/rescore_pdf_cache/` |

## 评分规则摘要（V2.1）

### 总分构成
- **价格维度**：50分
- **资历维度**：50分
- **微调**：±5分

### 价格评分（50分）
- 取 AIPE单价 / 人工翻译单价 中较优者
- 有议价空间：价格×0.9（有一些）或×0.7（较大）
- 满分标准：调整后价格 ≤ 语言对目标价
- 超出上限（hard_limit）：0分
- 价格规则按语言对配置，见 `pricing_rules.json`

### 资历评分（50分）
**优先级**：LLM 解析字段 > 正则提取 > 年限估算 > 项目数估算

- 字数 ≥ 50万：满分 30分（主要维度）
- 知名游戏/厂商经验：+10分（次要维度1）
- LQA/配音/咨询经验：+10分（次要维度2）
- 次要维度满足其一即视为完全符合（secondary≥10）

### 档位划分
| 总分 | 初始档位 |
|------|---------|
| ≥90 | S（优先录用） |
| 70-89 | A（优先联系） |
| 50-69 | B（备选考虑） |
| <50 | C（暂不录用） |

### 微调规则（最多浮动一档）
- +3：游戏/文娱领域从业超10年
- +2：多品类游戏经验（≥3类）
- +1：有独游经验
- -2：仅单一游戏品类
- -1：服务类型单一

## 两阶段工作流

```
阶段1（解析）：parse_resumes.py
  简历PDF + 飞书字段 → LLM提取 → 写回「解析字数/年限/项目数/知名实体」字段
  每份约1000-2000 token，一次性运行，可按需对单人重跑

阶段2（评分）：rescore_and_write.py  
  优先读「解析字段」→ 确定性规则计算 → 写回「总分/档位/评分依据/AI建议/有效简历/招募状态」
  无 LLM，完全确定性，可反复重跑
```

## 手动纠正流程

当 VM 发现评分不准时：
1. 直接在飞书表中修改「解析字数」「解析年限」「解析项目数」等字段
2. 重跑 `python3 scripts/rescore_and_write.py --name "候选人姓名"`
3. 评分自动更新

不需要重新解析 PDF，也不依赖 LLM。
