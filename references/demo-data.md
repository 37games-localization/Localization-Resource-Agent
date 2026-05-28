# Demo 数据 — 本地化资源管理全流程演示

## 模拟候选人

```json
{
  "record_id": "DEMO-001",
  "姓名": "山田花子",
  "邮箱": "demo-candidate@example.com",
  "语言对": "English to Japanese",
  "AIPE单价": 0.04,
  "人工翻译单价": 0.08,
  "报价商议空间": "有一些",
  "提供的服务": ["翻译", "LQA"],
  "项目经历": "Monster Hunter Rise (Capcom) - 200,000 words\nFinal Fantasy XIV (Square Enix) - 150,000 words\nNier: Automata (PlatinumGames) - 80,000 words\nFull-time game localization experience: 7 years",
  "其他相关经验": "Previously worked with SIDE and Keywords Studios",
  "招募状态": "📋 简历待筛选"
}
```

## LLM 解析预期结果

```json
{
  "解析字数": 430000,
  "解析年限": 7.0,
  "解析项目数": 3,
  "解析知名实体": "Monster Hunter Rise,Final Fantasy XIV,Nier: Automata,Capcom,Square Enix,SIDE,Keywords Studios"
}
```

## 评分预期结果

- AIPE单价 0.04（en>ja 目标约 0.05）→ 价格满分 50
- 字数 43万 ≥ 30万阈值 → 资历高分
- 知名游戏 + 知名厂商 + 知名LSP → 次要维度满分
- 预期档位：**S 优先录用**，总分 ≥ 90

## 测试题邮件草稿（英文）

```
Subject: Game Localization Test Assignment — 山田花子

Dear 山田花子,

Thank you for your interest in joining our localization team.

We would like to invite you to complete a translation test to assess your skills.
Please find the test assignment attached.

Kindly return your completed translation within 5 business days.

If you have any questions, please feel free to reach out.

Best regards,
本地化团队
```

## 合同信息（模拟）

```json
{
  "contractor_name": "山田花子",
  "contractor_name_en": "Yamada Hanako",
  "id_number": "DEMO-ID-00001",
  "bank_name": "Demo Bank",
  "bank_account": "DEMO1234567890",
  "bank_account_name": "Yamada Hanako",
  "swift_code": "DEMOSWIFT",
  "address": "Tokyo, Japan",
  "email": "demo-candidate@example.com",
  "contract_no": "DEMO-2026-001"
}
```

## 状态推进顺序（全流程演示）

```
📋 简历待筛选
→ ✅ 初筛通过       （评分完成后）
→ 📤 测试中         （测试题发送后）
→ ✅ 测试通过       （VM 确认）
→ 📧 合同信息收集中 （合同信息收集后）
→ 📄 合同待生成     （信息填写完成）
→ 📮 合同已发送     （合同生成+发送后）
→ 🔏 等待签署       （等待回签）
```
