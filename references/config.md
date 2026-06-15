# 简历筛选评分系统 — 配置参考

## 飞书 Base 信息

这里不再保存真实 token / table-id。VM 更换表或部署新环境时，应先在本机 `config.local.yaml` 中填写真实配置，再运行 `schema_mapping_checkpoint.py propose --table all` 做表头识别和映射确认。

| 项目 | 用途 | 填写位置 |
|------|----|
| 简历收集表 base-token | 读取候选人、简历、评分、状态 | `lark.base_token` |
| 简历收集表 table-id | 主数据表 | `lark.resume_table_id` |
| 合同信息表 base-token | 读取收款信息、证件、签回合同 | `lark.contract_base_token` |
| 合同信息表 table-id | 合同信息收集表 | `lark.contract_table_id` |
| 签约信息收集表单地址 | 发给资源商填写合同/银行/证件信息 | `lark.contract_info_form_url` |
| 合同模板表 base-token | 读取合同模板 | `lark.template_base_token` |
| 合同模板表 table-id | 合同模板表 | `lark.template_table_id` |
| 飞书 App ID | bot 绑定用，找项目维护人获取 | 不写入文档 |

## LLM API Key

简历解析需要 LLM API Key。请在本机 `config.local.yaml` 中填写：

```yaml
llm:
  base_url: "https://ai-proxy.37wan.com/anthropic"
  model: "claude-sonnet-4-5-20250929"
  api_key: "你的apiKey"
```

也可以设置环境变量 `LOC_LLM_API_KEY`。skill 不会自动读取 OpenClaw provider 或 `openclaw.json`，避免静默消耗 OpenClaw 月度额度。

## 关键字段映射

本仓库不保存真实 Field ID。实际运行优先读取 `config/lark-field-mapping.yaml`；VM 更换 Lark 表后，Agent 先运行 `python3 scripts/schema_mapping_checkpoint.py propose --table all` 生成 checkpoint。VM 确认或描述调整后，再运行 `adjust` / `confirm` 刷新新映射。

### 输入字段（VM 填写）
| 字段名 | 映射键 | 类型 |
|--------|--------|------|
| 姓名 | candidate.name | text |
| 语言对 | candidate.language_pair | select |
| 简历 | candidate.resume | attachment |
| 人工翻译单价 | candidate.human_price | number |
| AIPE单价 | candidate.aipe_price | number |
| 报价商议空间 | candidate.price_flexibility | select |
| 提供的服务 | candidate.services | select（多选） |
| 项目经历 | candidate.project_experience | text |
| 其他相关经验 | candidate.other_experience | text |
| 熟悉的IP | candidate.familiar_ips | text |

### LLM 解析字段（parse_resumes.py 写入，可手动纠正）
| 字段名 | 映射键 | 类型 | 说明 |
|--------|--------|------|------|
| 解析字数 | candidate.parsed_word_count | number | 游戏翻译实际字数，手动纠正直接改这里 |
| 解析年限 | candidate.parsed_years | number | 游戏翻译从业年限 |
| 解析项目数 | candidate.parsed_project_count | number | 游戏项目数量 |
| 解析知名实体 | candidate.parsed_known_entities | text | 知名游戏/厂商/LSP，逗号分隔 |
| 简历解析时间 | candidate.parsed_at | datetime | 最后一次解析时间 |

### 评分输出字段（rescore_and_write.py 写入）
| 字段名 | 映射键 | 类型 |
|--------|--------|------|
| 总分 | candidate.score | number |
| 初始评级 | candidate.rating | select |
| 有效简历 | candidate.valid_resume | select |
| 评分依据 | candidate.score_basis | text |
| AI建议 | candidate.ai_suggestion | text |
| 招募状态 | candidate.status | select |

## 评分引擎路径

| 文件 | 路径 |
|------|------|
| 引擎主文件 | `scripts/resume_screening_engine_v2.py` |
| 评分规则与价格范围 | `config/resume_screening_rules_v2.json` |
| PDF 缓存目录 | `~/.loc-resume-cache/` |

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
- 价格规则按语言对配置，见 `config/resume_screening_rules_v2.json` 的 `price_rules`

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
