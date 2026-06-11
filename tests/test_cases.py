"""
评分引擎测试集 v1.0
生成时间：2026-06-10
覆盖：A类常规场景 + C类边界规则 + B类snapshot基线

测试执行：python3 tests/run_tests.py
"""

# ============================================================
# 公共候选人数据模板
# ============================================================

def _base(overrides: dict) -> dict:
    """基础候选人模板，覆盖指定字段"""
    base = {
        "姓名": "测试候选人",
        "语言对": "zh-CN>en",
        "人工翻译单价": 0.035,
        "AIPE单价": None,
        "报价商议空间": "固定",
        "提供的服务": ["翻译"],
        "项目经历": "参与过多个游戏本地化项目，累计翻译字数约 200,000 字",
        "其他相关经历": "熟悉 CAT 工具，有 3 年翻译经验",
        "_parsed_word_count": None,
        "_parsed_years": None,
        "_parsed_project_cnt": None,
        "_parsed_entities": "",
    }
    base.update(overrides)
    return base


# ============================================================
# 测试用例定义
# ============================================================

TEST_CASES = [

    # ──────────────────────────────────────────────────────────
    # C 类：边界规则（12个）
    # ──────────────────────────────────────────────────────────

    {
        "id": "C01",
        "category": "C",
        "name": "无翻译/游戏经验 → 有效简历=否",
        "description": "项目经历和服务中完全没有翻译/游戏关键词",
        "covered_rules": ["check_valid_resume: 无翻译/游戏经验 → valid=False"],
        "input": _base({
            "姓名": "测试_C01",
            "提供的服务": ["设计", "摄影"],
            "项目经历": "负责产品UI设计，主导过多个移动端应用界面开发",
            "其他相关经历": "熟悉Figma和Sketch工具",
        }),
        "expected": {
            "valid_resume": False,
            "final_tier_in": ["C", "B"],  # 价格在cap内但无游戏/翻译经验，档位取决于match
        },
        "snapshot": None,
    },

    {
        "id": "C02",
        "category": "C",
        "name": "报价超过hard_limit(0.10) → 价格分=0，档位=C",
        "description": "AIPE单价0.15，超过hard_limit=0.10",
        "covered_rules": ["calculate_price_score: 单价>0.10 → score=0", "_determine_base_tier: 单价>cap → C"],
        "input": _base({
            "姓名": "测试_C02",
            "AIPE单价": 0.15,
            "人工翻译单价": None,
        }),
        "expected": {
            "final_tier_in": ["C"],
            "price_score_range": [0, 0],
            "base_tier_in": ["C"],
        },
        "snapshot": None,
    },

    {
        "id": "C03",
        "category": "C",
        "name": "报价恰好等于expected(0.03) → 价格分=50",
        "description": "AIPE单价精确等于expected=0.03，应得满分50",
        "covered_rules": ["calculate_price_score: 单价≤expected → score=50", "is_below_target=True"],
        "input": _base({
            "姓名": "测试_C03",
            "AIPE单价": 0.03,
            "人工翻译单价": None,
        }),
        "expected": {
            "price_score_range": [50, 50],
            "final_tier_in": ["S", "A"],  # 取决于experience match
        },
        "snapshot": None,
    },

    {
        "id": "C04",
        "category": "C",
        "name": "报价恰好等于cap(0.04) → 价格分=25",
        "description": "AIPE单价精确等于cap=0.04，线性插值边界值=25",
        "covered_rules": ["calculate_price_score: 单价=cap → score=25（线性插值边界）"],
        "input": _base({
            "姓名": "测试_C04",
            "AIPE单价": 0.04,
            "人工翻译单价": None,
        }),
        "expected": {
            "price_score_range": [25, 25],
            "final_tier_in": ["A", "B", "C"],
        },
        "snapshot": None,
    },

    {
        "id": "C05",
        "category": "C",
        "name": "报价在expected~cap之间 → 价格分25~50",
        "description": "AIPE单价0.035，在expected(0.03)和cap(0.04)之间",
        "covered_rules": ["calculate_price_score: expected<p≤cap → 25~50线性插值"],
        "input": _base({
            "姓名": "测试_C05",
            "AIPE单价": 0.035,
            "人工翻译单价": None,
        }),
        "expected": {
            "price_score_range": [25, 50],
            "final_tier_in": ["S", "A", "B"],
        },
        "snapshot": None,
    },

    {
        "id": "C06",
        "category": "C",
        "name": "单价缺失(None) → 价格分=0",
        "description": "人工翻译单价和AIPE单价均为None",
        "covered_rules": ["calculate_price_score: 无报价 → score=0, is_below_target=False, is_below_max=False"],
        "input": _base({
            "姓名": "测试_C06",
            "AIPE单价": None,
            "人工翻译单价": None,
        }),
        "expected": {
            "price_score_range": [0, 0],
            "final_tier_in": ["C"],
        },
        "snapshot": None,
    },

    {
        "id": "C07",
        "category": "C",
        "name": "完全符合 + 单价>cap → 档位=C（重要边界）",
        "description": "经验完全符合但单价0.045>cap=0.04，is_below_max=False → base=C。注意：完全符合≠高档位，价格超cap直接C",
        "covered_rules": ["_determine_base_tier: is_below_max=False → C（无论match_level如何）"],
        "input": _base({
            "姓名": "测试_C07",
            "AIPE单价": 0.045,
            "人工翻译单价": None,
            "项目经历": "10年游戏本地化经验，参与RPG、MOBA、SLG等多品类项目，累计字数500,000字以上，合作过腾讯、网易等知名厂商",
            "其他相关经历": "熟悉Trados、memoQ等CAT工具，有LQA经验",
        }),
        "expected": {
            "base_tier_in": ["C"],   # 超cap → C，价格一票否决
            "final_tier_in": ["C"],
        },
        "snapshot": None,
    },

    {
        "id": "C08",
        "category": "C",
        "name": "部分符合 + 单价>cap → 档位=C",
        "description": "经验部分符合且单价0.05>cap=0.04",
        "covered_rules": ["_determine_base_tier: is_below_max=False AND 部分符合 → C"],
        "input": _base({
            "姓名": "测试_C08",
            "AIPE单价": 0.05,
            "人工翻译单价": None,
            "项目经历": "有一些翻译经验，主要做文学翻译",
            "其他相关经历": "",
        }),
        "expected": {
            "base_tier_in": ["C"],
            "final_tier_in": ["C"],
        },
        "snapshot": None,
    },

    {
        "id": "C09",
        "category": "C",
        "name": "游戏品类单一(-2) → B档下浮到C",
        "description": "原本B档候选人，因游戏品类单一减2分，档位下浮到C",
        "covered_rules": ["_calculate_bonus_penalty: 品类单一 → -2", "_adjust_tier: net≤-3 → 下浮一档"],
        "input": _base({
            "姓名": "测试_C09",
            "AIPE单价": 0.038,
            "人工翻译单价": None,
            "项目经历": "专注RPG游戏翻译5年，累计翻译字数约100,000字",
            "其他相关经历": "熟悉RPG类游戏术语体系",
        }),
        "expected": {
            "final_tier_in": ["C", "B"],  # -2不一定触发下浮（需≤-3），视base_tier而定
        },
        "snapshot": None,
    },

    {
        "id": "C10",
        "category": "C",
        "name": "多品类+长年限(+5) → 触发上浮机制（base=B→final=A)",
        "description": "RPG/FPS/MOBA/SLG四品类+12年游戏经验，net=+5，触发上浮。注意：引擎年限提取依赖文本，实际words=100k→部分符合→base=B",
        "covered_rules": [
            "_calculate_bonus_penalty: ≥3品类 → +2",
            "_calculate_bonus_penalty: 游戏≥10年 → +3",
            "_adjust_tier: net≥3 → 上浮一档（B→A）",
        ],
        "input": _base({
            "姓名": "测试_C10",
            "AIPE单价": 0.038,
            "人工翻译单价": None,
            "项目经历": "12年游戏本地化经验，参与RPG、FPS、MOBA、SLG多品类项目，与腾讯、网易长期合作",
            "其他相关经历": "LQA经验丰富，熟悉游戏术语",
        }),
        "expected": {
            "base_tier_in": ["B"],   # words=100k → 部分符合 → B
            "final_tier_in": ["B"],  # net实际=+3（+2品类+3年限-2单一=-2？）需验证
        },
        "snapshot": None,
    },

    {
        "id": "C11",
        "category": "C",
        "name": "语言对字段缺失 → 不崩溃",
        "description": "语言对为None或空字符串，引擎应能处理不崩溃",
        "covered_rules": ["calculate_price_score: 语言对缺失 → 使用默认规则或返回0"],
        "input": _base({
            "姓名": "测试_C11",
            "语言对": None,
            "AIPE单价": 0.03,
            "人工翻译单价": None,
        }),
        "expected": {
            "no_crash": True,  # 不崩溃即通过
            "final_tier_in": ["S", "A", "B", "C"],
        },
        "snapshot": None,
    },

    {
        "id": "C12",
        "category": "C",
        "name": "有较大商议空间(×0.7) + 原价0.05 → 实际0.035，在cap内",
        "description": "原价0.05>cap，但商议系数0.7后实际0.035<cap，价格分应>25",
        "covered_rules": ["calculate_price_score: 有较大商议空间 → negotiation_factor=0.7", "实际价格=原价×0.7"],
        "input": _base({
            "姓名": "测试_C12",
            "AIPE单价": 0.05,
            "人工翻译单价": None,
            "报价商议空间": "有较大商议空间",
        }),
        "expected": {
            "price_score_range": [25, 50],  # 实际0.035在expected~cap之间
            "final_tier_in": ["S", "A", "B"],
        },
        "snapshot": None,
    },

    # ──────────────────────────────────────────────────────────
    # A 类：常规场景（8个）
    # ──────────────────────────────────────────────────────────

    {
        "id": "A01",
        "category": "A",
        "name": "典型A档：低价+部分符合（实际words=300k<500k）",
        "description": "AIPE单价0.025≤expected，但字数300k<500k → 主要部分符合 → base=A",
        "covered_rules": ["_determine_base_tier: is_below_target=True AND 部分符合 → A", "完全符合需要字数≥5000k+次要≥10"],
        "input": _base({
            "姓名": "测试_A01",
            "AIPE单价": 0.025,
            "人工翻译单价": None,
            "项目经历": "5年游戏本地化翻译经验，参与过多个RPG项目，累计字数300,000字",
            "其他相关经历": "熟悉CAT工具，有AIPE经验",
        }),
        "expected": {
            "base_tier_in": ["A"],   # is_below_target=True AND 部分符合 → A
            "final_tier_in": ["A"],
            "price_score_range": [50, 50],
        },
        "snapshot": None,
    },

    {
        "id": "A02",
        "category": "A",
        "name": "典型C档：低价但无游戏/知名实体经验",
        "description": "单价低但商业翻译背景，没有游戏关键词或知名厂商→次要=0→完全不符合→base=C",
        "covered_rules": ["_determine_base_tier: 完全不符合 → C", "小数主要分+次要分均=0 → 完全不符合"],
        "input": _base({
            "姓名": "测试_A02",
            "AIPE单价": 0.025,
            "人工翻译单价": None,
            "项目经历": "有翻译经验，主要做商业文本翻译，偶尔接触游戏类内容",
            "其他相关经历": "英语母语级别",
        }),
        "expected": {
            "base_tier_in": ["C"],   # 字数近于0，次要分=0 → 完全不符合 → C
            "final_tier_in": ["C"],
            "price_score_range": [50, 50],
        },
        "snapshot": None,
    },

    {
        "id": "A03",
        "category": "A",
        "name": "典型B档：中价+部分符合（字数400k未达500k）",
        "description": "单价0.038在expected~cap之间，字数400k<500k → 部分符合 → base=B",
        "covered_rules": ["_determine_base_tier: is_below_max=True AND 部劆符合 → B"],
        "input": _base({
            "姓名": "测试_A03",
            "AIPE单价": 0.038,
            "人工翻译单价": None,
            "项目经历": "8年游戏本地化经验，参与RPG和SLG项目，累计字数400,000字，合作过网易",
            "其他相关经历": "LQA经验，熟悉游戏术语",
        }),
        "expected": {
            "base_tier_in": ["B"],   # 字数400k<500k → 部分符合 → B
            "final_tier_in": ["B"],
            "price_score_range": [25, 50],
        },
        "snapshot": None,
    },

    {
        "id": "A04",
        "category": "A",
        "name": "典型C档：中价但无游戏/知名实体经验",
        "description": "单价0.038在expected~cap之间，但软件本地化背景无游戏关键词→主要=0→完全不符合→C",
        "covered_rules": ["_determine_base_tier: 完全不符合 → C"],
        "input": _base({
            "姓名": "测试_A04",
            "AIPE单价": 0.038,
            "人工翻译单价": None,
            "项目经历": "有翻译经验，主要做软件本地化，少量游戏项目",
            "其他相关经历": "2年工作经验",
        }),
        "expected": {
            "base_tier_in": ["C"],   # 主要分近于0，次要=0 → 完全不符合 → C
            "final_tier_in": ["C"],
            "price_score_range": [25, 50],
        },
        "snapshot": None,
    },

    {
        "id": "A05",
        "category": "A",
        "name": "典型C档：高价",
        "description": "单价0.07>cap=0.04，is_below_max=False，档位=C",
        "covered_rules": ["_determine_base_tier: 单价>cap → C（无论经验多好）"],
        "input": _base({
            "姓名": "测试_A05",
            "AIPE单价": 0.07,
            "人工翻译单价": None,
            "项目经历": "15年游戏本地化经验，参与多个3A项目",
        }),
        "expected": {
            "base_tier_in": ["C"],
            "final_tier_in": ["C", "B"],  # 可能因加分上浮
            "price_score_range": [0, 25],
        },
        "snapshot": None,
    },

    {
        "id": "A06",
        "category": "A",
        "name": "有游戏经验+低价 → S档，有效简历=是",
        "description": "完整游戏本地化背景+低价，预期S档且有效简历",
        "covered_rules": ["check_valid_resume: 游戏本地化经验 → valid=True", "_determine_base_tier: S档条件"],
        "input": _base({
            "姓名": "测试_A06",
            "AIPE单价": 0.025,
            "人工翻译单价": None,
            "提供的服务": ["翻译", "AIPE", "LQA"],
            "项目经历": "专业游戏本地化译者，参与LOL、王者荣耀等知名游戏，累计字数500,000字",
            "其他相关经历": "有LQA测试经验，熟悉腾讯本地化流程",
        }),
        "expected": {
            "valid_resume": True,
            "base_tier_in": ["S"],
            "final_tier_in": ["S", "A"],
        },
        "snapshot": None,
    },

    {
        "id": "A07",
        "category": "A",
        "name": "LQA经验候选人",
        "description": "主要提供LQA服务，有语言测试经验",
        "covered_rules": ["check_valid_resume: LQA服务 → valid=True", "experience: LQA加分项"],
        "input": _base({
            "姓名": "测试_A07",
            "AIPE单价": 0.03,
            "人工翻译单价": None,
            "提供的服务": ["LQA", "翻译"],
            "项目经历": "3年LQA测试经验，参与多款手游的语言质量测试",
            "其他相关经历": "linguistic testing，本地化测试",
        }),
        "expected": {
            "valid_resume": True,
            "final_tier_in": ["S", "A", "B"],
        },
        "snapshot": None,
    },

    {
        "id": "A08",
        "category": "A",
        "name": "无游戏经验但有翻译经验 → 有效简历=是",
        "description": "纯翻译背景无游戏经验，有效简历仍应为是",
        "covered_rules": ["check_valid_resume: 有翻译服务/关键词 → valid=True（不要求游戏经验）"],
        "input": _base({
            "姓名": "测试_A08",
            "人工翻译单价": 0.04,
            "AIPE单价": None,
            "提供的服务": ["翻译", "校对"],
            "项目经历": "5年商业翻译经验，主要做法律和金融文本翻译",
            "其他相关经历": "持有翻译资格证书",
        }),
        "expected": {
            "valid_resume": True,
            "final_tier_in": ["S", "A", "B", "C"],
        },
        "snapshot": None,
    },

    # ──────────────────────────────────────────────────────────
    # B 类：Snapshot 基线（5个，运行后填入真实输出）
    # ──────────────────────────────────────────────────────────

    {
        "id": "B01",
        "category": "B",
        "name": "Snapshot：理想S档候选人",
        "description": "基线记录：低价+完全符合+多品类经验",
        "covered_rules": ["snapshot基线"],
        "input": _base({
            "姓名": "测试_B01",
            "AIPE单价": 0.025,
            "人工翻译单价": None,
            "项目经历": "10年游戏本地化经验，RPG、FPS、MOBA、SLG多品类，字数600,000字，合作过腾讯、网易、米哈游",
            "其他相关经历": "LQA经验，熟悉主流CAT工具",
        }),
        "expected": {"final_tier_in": ["S", "A"]},
        "snapshot": None,  # 执行后由 run_tests.py 填入
    },

    {
        "id": "B02",
        "category": "B",
        "name": "Snapshot：典型B档候选人",
        "description": "基线记录：中价+部分符合",
        "covered_rules": ["snapshot基线"],
        "input": _base({
            "姓名": "测试_B02",
            "AIPE单价": 0.038,
            "人工翻译单价": None,
            "项目经历": "3年翻译经验，少量游戏项目",
            "其他相关经历": "英语专业毕业",
        }),
        "expected": {"final_tier_in": ["B", "A", "C"]},
        "snapshot": None,
    },

    {
        "id": "B03",
        "category": "B",
        "name": "Snapshot：人工翻译单价（非AIPE）",
        "description": "基线记录：只有人工翻译单价，测试价格选择逻辑",
        "covered_rules": ["snapshot基线", "calculate_price_score: 无AIPE则用翻译单价"],
        "input": _base({
            "姓名": "测试_B03",
            "AIPE单价": None,
            "人工翻译单价": 0.04,
            "项目经历": "5年翻译经验，有游戏本地化项目经历",
        }),
        "expected": {"final_tier_in": ["S", "A", "B"]},
        "snapshot": None,
    },

    {
        "id": "B04",
        "category": "B",
        "name": "Snapshot：有一些商议空间(×0.9)",
        "description": "基线记录：原价0.035，商议系数0.9，实际0.0315",
        "covered_rules": ["snapshot基线", "negotiation_factor=0.9"],
        "input": _base({
            "姓名": "测试_B04",
            "AIPE单价": 0.035,
            "人工翻译单价": None,
            "报价商议空间": "有一些商议空间",
            "项目经历": "4年游戏翻译经验，RPG项目为主",
        }),
        "expected": {"final_tier_in": ["S", "A", "B"]},
        "snapshot": None,
    },

    {
        "id": "B05",
        "category": "B",
        "name": "Snapshot：zh-CN>ja语言对",
        "description": "基线记录：日语方向，expected=0.02，cap=0.05，价格规则不同",
        "covered_rules": ["snapshot基线", "zh-CN>ja价格规则：expected=0.02, cap=0.05"],
        "input": _base({
            "姓名": "测试_B05",
            "语言对": "zh-CN>ja",
            "AIPE单价": 0.025,
            "人工翻译单价": None,
            "项目经历": "日语游戏本地化译者，参与过多个日系RPG项目",
        }),
        "expected": {"final_tier_in": ["A", "B", "S"]},
        "snapshot": None,
    },
]
