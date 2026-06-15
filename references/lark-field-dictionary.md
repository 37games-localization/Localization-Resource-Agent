# Lark 字段语义字典

> 用途：VM 更换 Lark 表、修改表头、或复制新表时，用这份字典判断哪些列必须保留、每列存什么、影响哪个 Agent 节点。

## 使用规则

- `key` 是 Agent 内部稳定字段名，不建议改。
- VM 可以改 Lark 表头中文名，但不要改变字段承载的业务含义。
- 换新表时，先跑 `python3 scripts/schema_mapping_checkpoint.py propose --table all`，Agent 会按表头和别名生成字段映射 checkpoint。
- 如果校验报告提示缺字段，先看本字典确认字段用途，再决定新增列或映射到已有列。
- 映射只有在 VM 确认并运行 `schema_mapping_checkpoint.py confirm --token <checkpoint_token>` 后才会保存。
- `required=true` 表示当前生产链路必须有；`required=false` 表示对应能力启用时需要。

## 候选人主表 `candidate`

| key | 建议表头 | 用途 | 读/写 | 必需 | 影响节点 |
|---|---|---|---|---:|---|
| `candidate.name` | 姓名 | 候选人主显示名，用于 VM 按姓名触发、邮件称呼、看板展示。 | 读 | 是 | 全部候选人相关节点 |
| `candidate.nickname` | 昵称 | 候选人别名/常用名，用于模糊匹配和 VM 口语触发。 | 读 | 否 | 候选人匹配 |
| `candidate.email` | 邮箱 | 候选人收件地址；TEST_MODE 下仅作为原始目标展示。 | 读 | 是 | 测试题邮件、合同邮件 |
| `candidate.language_pair` | 语言对 | 评分规则、测试题邮件说明、候选人分类的关键输入。 | 读 | 是 | 评分、测试题邮件 |
| `candidate.resume` | 简历 | 简历附件；LLM/PDF 解析和评分补充信息来源。 | 读 | 否 | 简历解析、评分 |
| `candidate.status` | 招募状态 | 16 节点状态机的当前状态；决定下一步建议和看板状态。 | 读/写 | 是 | 状态推进、统一入口、看板 |
| `candidate.manual_translation_price` | 人工翻译单价 | 候选人的人工翻译报价，进入价格评分。 | 读 | 否 | 评分 |
| `candidate.aipe_price` | AIPE单价 | 候选人的 AIPE 报价，进入价格评分。 | 读 | 否 | 评分 |
| `candidate.price_flexibility` | 报价商议空间 | 用于折算报价，如有一些/较大商议空间。 | 读 | 否 | 评分 |
| `candidate.services` | 提供的服务 | 判断翻译、LQA、配音等服务能力。 | 读 | 否 | 评分、有效简历判断 |
| `candidate.project_experience` | 项目经历 | 项目经历文本，补充游戏/翻译经验判断。 | 读 | 否 | 评分、有效简历判断 |
| `candidate.other_experience` | 其他相关经验 | 其他经验文本，补充从业、游戏、LQA 等判断。 | 读 | 否 | 评分、有效简历判断 |
| `candidate.parsed_word_count` | 解析字数 | LLM 从简历中提取的游戏/翻译字数；VM 可手动纠正后重跑评分。 | 读/写 | 否 | 简历解析、评分 |
| `candidate.parsed_years` | 解析年限 | LLM 从简历中提取的相关从业年限；可手动纠正。 | 读/写 | 否 | 简历解析、评分 |
| `candidate.parsed_project_count` | 解析项目数 | LLM 从简历中提取的游戏/翻译项目数量；可手动纠正。 | 读/写 | 否 | 简历解析、评分 |
| `candidate.parsed_entities` | 解析知名实体 | LLM 提取的知名游戏、厂商、LSP 等实体。 | 读/写 | 否 | 简历解析、评分 |
| `candidate.resume_parsed_at` | 简历解析时间 | 最后一次 LLM 解析简历的时间，用于判断是否需要重跑解析。 | 写/读 | 否 | 简历解析、看板 |
| `candidate.score` | 总分 | 规则引擎计算出的最终分数。 | 写/读 | 是 | 评分、看板 |
| `candidate.tier` | 初始评级 | 评分档位 S/A/B/C/D。 | 写/读 | 是 | 评分、初筛判断、看板 |
| `candidate.valid_resume` | 有效简历 | 是否满足基本翻译/游戏/从业信号。 | 写/读 | 是 | 初筛判断、看板 |
| `candidate.score_basis` | 评分依据 | 评分计算过程和关键依据，供 VM 快速复核。 | 写/读 | 是 | 评分、看板 |
| `candidate.ai_suggestion` | AI建议 | 下一步建议，如优先录用、人工复核、不建议录用。 | 写/读 | 是 | 评分、VM 决策 |
| `candidate.test_sent_at` | 测试发送时间 | 测试题邮件发送后记录时间。 | 写/读 | 否 | 测试题邮件、看板 |
| `candidate.contract_id` | 合同编号 | 甲方内部合同审批编号；乙方签回后由 VM/审批流程补充，供后续追踪和归档。 | 写/读 | 否 | 合同审批、财务登记、归档 |
| `candidate.supplier_id` | 供应商编号 | 财务/供应商系统登记后的供应商编号，供资源入库和后续结算追踪。 | 写/读 | 否 | 供应商登记、财务审批、入库 |
| `candidate.badcase_flag` | 是否Badcase | VM 标记运行结果不符合预期。 | 读/写 | 否 | Badcase 回流 |
| `candidate.expected_result` | 期望结果 | VM 对 badcase 的一句话期望结果。 | 读/写 | 否 | Badcase 回流 |
| `candidate.badcase_snapshot` | Badcase快照 | 自动生成的脱敏 snapshot JSON 附件。 | 写/读 | 否 | Badcase 回流 |

## 评分规则配置表 `pricing_rules`

评分规则配置表是独立规则资产：它可以和候选人主表在同一个 Base，也可以放在单独的规则 Base 中复用。VM 更换简历收集表时，不应默认重建评分规则表；只有评分策略或语言对价格规则变化时才需要切换或维护这张表。

| key | 建议表头 | 用途 | 读/写 | 必需 | 影响节点 |
|---|---|---|---|---:|---|
| `pricing.language_pair` | 语言对 | 价格规则命中的语言对 key，例如 `zh-CN>en` 或 `简中>英语`。 | 读 | 是 | 评分 |
| `pricing.aipe_target` | AIPE预期价 | AIPE 报价低于或等于该值时价格维度满分。 | 读 | 是 | 评分 |
| `pricing.aipe_max` | AIPE上限价 | AIPE 报价高于该值时价格维度判为不合格区间。 | 读 | 是 | 评分 |
| `pricing.translation_target` | 翻译预期价 | 人工翻译报价低于或等于该值时价格维度满分。 | 读 | 是 | 评分 |
| `pricing.translation_max` | 翻译上限价 | 人工翻译报价高于该值时价格维度判为不合格区间。 | 读 | 是 | 评分 |
| `pricing.version` | 规则版本 | 标记价格规则版本，便于追溯评分依据。 | 读 | 否 | 评分、审计 |
| `pricing.enabled` | 启用 | 可临时停用某条语言对规则；空值默认启用。 | 读 | 否 | 评分 |

## 流程日志表 `workflow_log`

| key | 建议表头 | 用途 | 读/写 | 必需 | 影响节点 |
|---|---|---|---|---:|---|
| `workflow.run_id` | run_id | 同一次脚本运行的稳定 ID，用于聚合一轮执行过程。 | 写/读 | 是 | 可视化、审计 |
| `workflow.candidate_record_id` | candidate_record_id | 候选人在主表里的 Lark record_id，用于把日志挂回候选人。 | 写/读 | 是 | 看板聚合、恢复决策 |
| `workflow.candidate_name` | candidate_name | 日志展示用候选人姓名。 | 写/读 | 是 | 看板、待决策列表 |
| `workflow.step_name` | step_name | 当前动作或 checkpoint 名称。 | 写/读 | 是 | 看板、待决策列表 |
| `workflow.step_type` | step_type | 动作类型：action/checkpoint/decision/error。 | 写/读 | 是 | 看板筛选、审计 |
| `workflow.status` | status | 步骤状态：running/done/waiting/decided/skipped/failed。 | 写/读 | 是 | 待决策恢复、看板 |
| `workflow.input_summary` | input_summary | 本步骤使用了什么输入，脱敏摘要。 | 写/读 | 是 | 可视化、审计 |
| `workflow.output_summary` | output_summary | 本步骤输出了什么结果；checkpoint token 存在这里。 | 写/读 | 是 | 可视化、恢复决策 |
| `workflow.decision` | decision | VM 的人工决策，如写入、跳过、继续、取消。 | 写/读 | 否 | Human Decision 节点 |
| `workflow.created_at` | created_at | 日志创建时间。 | 写/读 | 是 | 看板排序、审计 |

## 合同信息表 `contract_info`

| key | 建议表头 | 用途 | 读/写 | 必需 | 影响节点 |
|---|---|---|---|---:|---|
| `contract.name` | 姓名（全名） | 合同乙方姓名；用于匹配候选人和填充合同变量。 | 读 | 是 | 合同生成 |
| `contract.email` | 常用工作邮箱 | 合同邮件收件人；TEST_MODE 下仅作为原始目标展示。 | 读 | 是 | 合同生成/发送 |
| `contract.id_number` | 身份证或护照号 | 合同身份信息变量。 | 读 | 是 | 合同生成 |
| `contract.address` | 个人住址 | 合同乙方地址变量。 | 读 | 否 | 合同生成 |
| `contract.phone` | 联系电话 | 合同乙方联系电话变量。 | 读 | 否 | 合同生成 |
| `contract.account_type` | 收款账号类型 | 判断个人账户/公司账户，影响合同模板和变量。 | 读 | 是 | 合同模板匹配 |
| `contract.bank_account_name` | 个人账户 - 账户名 | 收款账户名；会和姓名做拼音/一致性提示。 | 读 | 是 | 合同生成、风险提示 |
| `contract.bank_account_number` | 个人账户 - 账号 | 收款账号/IBAN，填充合同变量。 | 读 | 是 | 合同生成 |
| `contract.bank_name` | 个人账户 - 银行名 | 个人账户银行名称变量。 | 读 | 否 | 合同生成 |
| `contract.bank_address` | 个人账户 - 支行地址 | 个人账户银行地址变量。 | 读 | 否 | 合同生成 |
| `contract.company_bank_account_name` | 公司账户 - 账户名 | 公司账户户名变量；公司合同使用。 | 读 | 否 | 合同生成 |
| `contract.company_bank_account_number` | 公司账户 - 账号 | 公司账户账号变量；公司合同使用。 | 读 | 否 | 合同生成 |
| `contract.company_bank_name` | 公司账户 - 银行名 | 公司账户银行名称变量；公司合同使用。 | 读 | 否 | 合同生成 |
| `contract.company_bank_address` | 公司账户 - 支行地址 | 公司账户银行地址变量；公司合同使用。 | 读 | 否 | 合同生成 |
| `contract.swift` | SWIFT | 银行 SWIFT code，填充合同变量。 | 读 | 是 | 合同生成 |
| `contract.currency` | 收款货币 | 合同付款币种变量。 | 读 | 否 | 合同生成 |
| `contract.id_scan` | 身份证/护照扫描件 | 个人合同需插入或核对的证件附件。 | 读 | 否 | 合同生成、签字核查 |
| `contract.signed_contract` | 合同签署 | 合同信息表中的签署状态/勾选结果。 | 读/写 | 否 | 合同生成、签字核查 |
| `contract.progress` | 合同进度 | 合同信息表中的签署或处理进度。 | 读/写 | 否 | 签字核查、看板 |

## VM 换表前检查清单

1. 主表至少保留：姓名、邮箱、语言对、招募状态、总分、初始评级、有效简历、评分依据、AI建议。
2. 若要跑测试题邮件，必须保留：邮箱、语言对、招募状态、测试发送时间。
3. 若要跑合同，必须配置合同信息表，并保留合同信息表中的必需字段。
4. 若要覆盖合同审批/供应商入库，主表需要保留或新增：合同编号、供应商编号。
5. 若要看板/待决策恢复，必须保留或创建 `Agent流程日志` 表。
6. 若要 badcase 回流，必须保留：是否Badcase、期望结果、Badcase快照。

## 当前 Badcase 字段映射

当前候选人主表已经创建并映射：

| key | Lark 表头 | 当前 Field ID | 用法 |
|---|---|---|---|
| `candidate.badcase_flag` | 是否Badcase | `flduSa1I3n` | VM 标记 `⚠️ 是` 后进入 badcase 导出队列；后续可标记 `✅ 已处理` |
| `candidate.expected_result` | 期望结果 | `fldcqij7pB` | VM 填一句话说明“应该是什么结果” |
| `candidate.badcase_snapshot` | Badcase快照 | `fldINLSImt` | Agent 上传脱敏 snapshot JSON 附件 |

VM 使用方式：

1. 在候选人主表把「是否Badcase」选为 `⚠️ 是`。
2. 在「期望结果」填写一句话，例如“应该进入人工复核，不该直接婉拒”。
3. 运行 `python3 scripts/export_badcase_snapshots.py --dry-run` 预览。
4. 确认无误后运行 `python3 scripts/export_badcase_snapshots.py` 上传脱敏快照到「Badcase快照」。

脚本不再硬编码这些 Field ID，会从 `config/lark-field-mapping.yaml` 读取当前映射。VM 换表后，只要重新跑 schema 校验生成映射，badcase 导出会跟随新表。
