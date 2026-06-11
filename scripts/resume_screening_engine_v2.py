"""
简历筛选规则引擎 V2 - 严格按原始逻辑实现
"""
import json
import re
from typing import Dict, List, Optional, Tuple
from pathlib import Path

from pricing_rules import PricingRulesError, load_price_rules


class ResumeScreeningEngineV2:
    """简历筛选规则引擎 V2 - 严格遵循原始评分逻辑"""
    
    def __init__(
        self,
        config_path: str = None,
        *,
        allow_local_rules: bool = True,
        require_lark_rules: bool = False,
    ):
        """初始化引擎"""
        if config_path is None:
            config_path = Path(__file__).parent.parent / "config" / "resume_screening_rules_v2.json"
        
        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = json.load(f)
        
        if require_lark_rules or not allow_local_rules:
            lark_rules, meta = load_price_rules(
                allow_local_rules=allow_local_rules,
                require_lark_rules=require_lark_rules,
            )
            self.price_rules = self._price_rules_for_engine(lark_rules)
            self.price_rules_meta = meta
        else:
            self.price_rules = self.config['price_rules']
            self.price_rules_meta = {"source": "local", "count": 0}
        self.job_requirements = self.config['job_requirements']
        self.basic_validation = self.config.get('basic_validation', {})
        self.business_types = self.config.get('business_types', {})
        self.valid_resume_rules = self.config.get('valid_resume_rules', {})
        self.valid_resume_rules = self.config.get('valid_resume_rules', {})

    @staticmethod
    def _price_rules_for_engine(flat_rules: dict) -> dict:
        price_rules = {"aipe": {}, "translation": {}}
        for key, rule in flat_rules.items():
            for normalized_key in {key, str(key).lower()}:
                price_rules["aipe"][normalized_key] = {
                    "target": rule["aipe_target"],
                    "max": rule["aipe_max"],
                }
                price_rules["translation"][normalized_key] = {
                    "target": rule["trans_target"],
                    "max": rule["trans_max"],
                }
        return price_rules
    
    def validate_basic(self, candidate_data: Dict) -> Dict:
        """
        3. 基础信息验证
        
        验证项：
        - 单价验证：翻译或AIPE单价在0.01-0.2区间
        - 目标语言验证：目标语言为母语或有翻译经验
        """
        results = {
            "price_validation": self._validate_price(candidate_data),
            "target_language_validation": self._validate_target_language(candidate_data),
            "overall_pass": False
        }
        
        # 基础验证通过 = 单价验证通过 AND 目标语言验证通过
        results["overall_pass"] = results["price_validation"]["pass"] and results["target_language_validation"]["pass"]
        
        return results
    
    def _validate_price(self, candidate_data: Dict) -> Dict:
        """
        单价验证
        满足以下一项则为验证通过：
        - 翻译单价不为空 AND 处于0.01-0.2的区间内
        - AIPE单价不为空 AND 处于0.01-0.2的区间内
        """
        trans_price = self._to_float(candidate_data.get('人工翻译单价'))
        aipe_price = self._to_float(candidate_data.get('AIPE单价'))
        
        min_price = 0.01
        max_price = 0.20
        
        # 检查翻译单价
        trans_valid = False
        if trans_price is not None:
            trans_valid = min_price <= trans_price <= max_price
        
        # 检查AIPE单价
        aipe_valid = False
        if aipe_price is not None:
            aipe_valid = min_price <= aipe_price <= max_price
        
        # 满足一项即通过
        passed = trans_valid or aipe_valid
        
        return {
            "pass": passed,
            "trans_price": trans_price,
            "trans_valid": trans_valid,
            "aipe_price": aipe_price,
            "aipe_valid": aipe_valid,
            "valid_range": f"{min_price}-{max_price} USD/字"
        }
    
    def _validate_target_language(self, candidate_data: Dict) -> Dict:
        """
        目标语言验证
        满足以下一项则为验证通过：
        - 目标语言为母语
        - 有目标语言的翻译经验
        
        注：判断候选人母语时，可综合参考以下信息：
        - 简历中明确提到的母语
        - 姓名特点
        - 学校所在地、工作地、常居地等地理信息
        """
        lang_pair = candidate_data.get('语言对', '')
        
        # 提取目标语言
        target_lang = None
        if '>en' in lang_pair or '>英语' in lang_pair:
            target_lang = '英语'
        elif '>ja' in lang_pair or '>日语' in lang_pair:
            target_lang = '日语'
        elif '>ko' in lang_pair or '>韩语' in lang_pair:
            target_lang = '韩语'
        elif '>de' in lang_pair or '>德语' in lang_pair:
            target_lang = '德语'
        elif '>fr' in lang_pair or '>法语' in lang_pair:
            target_lang = '法语'
        elif '>es' in lang_pair or '>西班牙语' in lang_pair:
            target_lang = '西班牙语'
        elif '>pt' in lang_pair or '>葡萄牙语' in lang_pair:
            target_lang = '葡萄牙语'
        elif '>ru' in lang_pair or '>俄语' in lang_pair:
            target_lang = '俄语'
        elif '>it' in lang_pair or '>意大利语' in lang_pair:
            target_lang = '意大利语'
        else:
            target_lang = '其他'
        
        # 检查是否为目标语言母语
        is_native = self._check_native_language(candidate_data, target_lang)
        
        # 检查是否有目标语言翻译经验
        has_experience = self._check_translation_experience(candidate_data, target_lang)
        
        # 满足一项即通过
        passed = is_native or has_experience
        
        return {
            "pass": passed,
            "target_lang": target_lang,
            "is_native": is_native,
            "has_experience": has_experience,
            "evidence": self._get_language_evidence(candidate_data)
        }
    
    def _check_native_language(self, candidate_data: Dict, target_lang: str) -> bool:
        """检查目标语言是否为母语"""
        # 从常居地推断
        location = candidate_data.get('常居地', '').lower()
        
        # 英语母语地区
        if target_lang == '英语' and any(c in location for c in ['美国', '英国', '加拿大', '澳大利亚', 'usa', 'uk', 'canada', 'australia']):
            return True
        
        # 日语母语地区
        if target_lang == '日语' and '日本' in location:
            return True
        
        # 韩语母语地区
        if target_lang == '韩语' and '韩国' in location:
            return True
        
        # 德语母语地区
        if target_lang == '德语' and any(c in location for c in ['德国', '奥地利', '瑞士']):
            return True
        
        # 法语母语地区
        if target_lang == '法语' and any(c in location for c in ['法国', '加拿大', '魁北克']):
            return True
        
        # 西班牙语母语地区
        if target_lang == '西班牙语' and any(c in location for c in ['西班牙', '墨西哥', '阿根廷', '智利', '哥伦比亚']):
            return True
        
        # 葡萄牙语母语地区
        if target_lang == '葡萄牙语' and any(c in location for c in ['巴西', '葡萄牙']):
            return True
        
        return False
    
    def _check_translation_experience(self, candidate_data: Dict, target_lang: str) -> bool:
        """检查是否有目标语言的翻译经验"""
        # 从项目经历中检测
        project_exp = str(candidate_data.get('项目经历', '')).lower()
        
        # 检测目标语言相关经验（更宽泛的匹配）
        lang_patterns = {
            '英语': ['英语', 'english', 'en>', '>en', '英中', '中英', '英译', '译英'],
            '日语': ['日语', 'japanese', 'ja>', '>ja', '日中', '中日', '日译', '译日'],
            '韩语': ['韩语', 'korean', 'ko>', '>ko', '韩中', '中韩', '韩译', '译韩'],
            '德语': ['德语', 'german', 'de>', '>de', '德中', '中德', '德译', '译德'],
            '法语': ['法语', 'french', 'fr>', '>fr', '法中', '中法', '法译', '译法'],
            '西班牙语': ['西班牙语', 'spanish', 'es-la', 'es>', '>es', '西中', '中西', '西译', '译西'],
            '葡萄牙语': ['葡萄牙语', 'portuguese', 'pt-br', 'pt>', '>pt', '葡中', '中葡', '葡译', '译葡'],
            '俄语': ['俄语', 'russian', 'ru>', '>ru', '俄中', '中俄', '俄译', '译俄'],
            '意大利语': ['意大利语', 'italian', 'it>', '>it', '意中', '中意', '意译', '译意'],
        }
        
        patterns = lang_patterns.get(target_lang, [])
        return any(p in project_exp for p in patterns)
    
    def _get_language_evidence(self, candidate_data: Dict) -> Dict:
        """获取语言相关证据"""
        evidence = {
            "简历中提到的母语": None,
            "姓名特点": None,
            "学校所在地": None,
            "工作地": None,
            "常居地": candidate_data.get('常居地')
        }
        
        # 可扩展：解析简历PDF内容提取更多信息
        
        return evidence
    
    def check_valid_resume(self, candidate_data: Dict) -> Dict:
        """
        4. 有效简历判断
        
        满足以下一项则为有效简历：
        - 有游戏经验
        - 有游戏从业经验
        - 有翻译经验
        """
        total_text = self._get_candidate_full_text(candidate_data)
        
        # 检查是否有游戏经验
        has_game_exp = self._check_game_experience(total_text)
        
        # 检查是否有游戏从业经验
        has_game_work_exp = self._check_game_work_experience(total_text)
        
        # 检查是否有翻译经验
        has_translation_exp = self._check_translation_experience_general(total_text)
        
        # 满足一项即有效
        is_valid = has_game_exp or has_game_work_exp or has_translation_exp
        
        return {
            "is_valid": is_valid,
            "has_game_experience": has_game_exp,
            "has_game_work_experience": has_game_work_exp,
            "has_translation_experience": has_translation_exp,
            "details": {
                "game_keywords": self._get_game_keywords() if has_game_exp else [],
                "game_work_keywords": self._get_game_work_keywords() if has_game_work_exp else [],
                "translation_keywords": self._get_translation_keywords() if has_translation_exp else []
            }
        }
    
    def _get_candidate_full_text(self, candidate_data: Dict) -> str:
        """获取候选人完整文本信息"""
        fields = ['项目经历', '其他相关经历', '熟悉的IP', '提供的服务', '个人简介']
        texts = []
        for field in fields:
            value = candidate_data.get(field, '')
            if value:
                texts.append(str(value))
        return ' '.join(texts).lower()
    
    def _check_game_experience(self, text: str) -> bool:
        """检查是否有游戏经验"""
        # 游戏相关关键词
        game_keywords = [
            # 游戏类型
            '游戏', 'game', 'gaming',
            '手游', 'mobile game', '手机游戏',
            '端游', 'pc game',
            '主机游戏', 'console game',
            '单机游戏', 'single player',
            '网络游戏', 'online game', 'mmorpg',
            'rpg', 'fps', 'moba', 'slg', '卡牌', '休闲', '动作', '冒险',
            
            # 游戏平台
            'steam', 'ios', 'android', 'playstation', 'xbox', 'nintendo', 'switch',
            'app store', 'google play', 'taptap',
            
            # 知名游戏（部分）
            'pubgm', 'pubg', '王者荣耀', 'honor of kings',
            '原神', 'genshin impact',
            '英雄联盟', 'league of legends', 'lol',
            'valorant',
            'apex', 'apex legends',
            'fortnite',
            'minecraft',
            'call of duty', 'cod',
            'gta',
            '刺客信条', 'assassin\'s creed',
            '巫师', 'the witcher',
            '艾尔登法环', 'elden ring',
            '塞尔达', 'zelda',
        ]
        
        return any(kw in text for kw in game_keywords)
    
    def detect_service_types(self, candidate_data: Dict) -> Dict:
        """
        检测候选人提供的业务类型
        
        业务类型：
        - 翻译：量级单位为字数
        - PE (Post-editing)：量级单位为字数
        - 校对：量级单位为字数
        - LQA (Linguistic Testing)：量级单位为小时
        - 质量评估：量级单位为字数或小时
        - 本地化咨询：量级单位为小时
        """
        services = candidate_data.get('提供的服务', []) or []
        services_text = ' '.join(str(s) for s in services).lower()
        
        detected_types = []
        
        # 翻译
        if any(kw in services_text for kw in ['翻译', 'translation', 'translate', 'trans']):
            detected_types.append({
                "type": "翻译",
                "unit": "字数",
                "matched": True
            })
        
        # PE (Post-editing)
        if any(kw in services_text for kw in ['aipe', 'ai pe', 'post-editing', 'post editing', '译后编辑', 'ai译后编辑']):
            detected_types.append({
                "type": "PE (Post-editing)",
                "unit": "字数",
                "matched": True
            })
        
        # 校对
        if any(kw in services_text for kw in ['校对', 'proofreading', 'proofread', 'proof reading']):
            detected_types.append({
                "type": "校对",
                "unit": "字数",
                "matched": True
            })
        
        # LQA (Linguistic Testing)
        if any(kw in services_text for kw in ['lqa', 'linguistic testing', 'localization testing', '语言测试', '跑测']):
            detected_types.append({
                "type": "LQA (Linguistic Testing)",
                "unit": "小时",
                "matched": True
            })
        
        # 质量评估
        if any(kw in services_text for kw in ['质量评估', 'quality assessment', 'qa assessment', '质量审核']):
            detected_types.append({
                "type": "质量评估",
                "unit": "字数或小时",
                "matched": True
            })
        
        # 本地化咨询
        if any(kw in services_text for kw in ['咨询', 'consulting', 'consultant', '顾问']):
            detected_types.append({
                "type": "本地化咨询",
                "unit": "小时",
                "matched": True
            })
        
        return {
            "detected_types": detected_types,
            "count": len(detected_types),
            "has_word_based": any(t['unit'] == '字数' for t in detected_types),
            "has_hour_based": any(t['unit'] == '小时' or t['unit'] == '字数或小时' for t in detected_types)
        }
    
    def _check_game_work_experience(self, text: str) -> bool:
        """检查是否有游戏从业经验"""
        # 游戏从业相关关键词
        work_keywords = [
            # 游戏公司
            '游戏公司', 'game company', 'gaming company',
            '游戏工作室', 'game studio',
            '游戏开发商', 'game developer', 'game development',
            '游戏发行商', 'game publisher',
            '游戏厂商',
            
            # 游戏职位
            '游戏本地化', 'game localization', 'gaming localization',
            '游戏翻译', 'game translation',
            '游戏策划', 'game designer', 'game design',
            '游戏运营', 'game operation', 'community manager',
            '游戏测试', 'game testing', 'qa',
            '游戏美术', 'game art', 'game artist',
            '游戏程序', 'game programmer', 'game engineering',
            '游戏音效', 'game audio', 'sound designer',
            
            # 知名游戏公司
            '腾讯', 'tencent', '天美', '光子',
            '网易', 'netease',
            '米哈游', 'mihoyo', 'hoyoverse',
            '暴雪', 'blizzard',
            '拳头', 'riot games', 'riot',
            '育碧', 'ubisoft',
            'ea', 'electronic arts',
            'valve',
            'epic games', 'epic',
        ]
        
        return any(kw in text for kw in work_keywords)
    
    def _check_translation_experience_general(self, text: str) -> bool:
        """检查是否有翻译经验（通用）"""
        # 翻译相关关键词
        translation_keywords = [
            '翻译', 'translator', 'translation',
            '本地化', 'localization', 'l10n',
            '译员', '译者',
            '笔译', 'written translation',
            '口译', 'interpretation', 'interpreter',
            '审校', 'review', 'proofreading',
            '校对', 'editing',
            '翻译经验', 'translation experience',
            '翻译项目', 'translation project',
            '翻译字数', 'word count',
        ]
        
        return any(kw in text for kw in translation_keywords)
    
    def _get_game_keywords(self) -> List[str]:
        """获取匹配的游戏关键词"""
        return ['游戏相关经验']
    
    def _get_game_work_keywords(self) -> List[str]:
        """获取匹配的游戏从业关键词"""
        return ['游戏从业经验']
    
    def _get_translation_keywords(self) -> List[str]:
        """获取匹配的翻译关键词"""
        return ['翻译经验']
    
    def calculate_price_score(self, candidate_data: Dict) -> Dict:
        """
        计算单价维度得分（0-50分）
        
        规则：
        - 单价≤预期：50分
        - 预期<单价≤上限：25 + 25*(上限-实际)/(上限-预期)
        - 上限<单价≤0.1：25 - 25*(实际-上限)/(0.1-上限)
        - 单价>0.1：0分
        """
        lang_pair = candidate_data.get('语言对', '')
        lang_pair_normalized = self._normalize_lang_pair(lang_pair)
        
        # 获取价格（优先AIPE，其次翻译）
        aipe_price = self._to_float(candidate_data.get('AIPE单价'))
        trans_price = self._to_float(candidate_data.get('人工翻译单价'))
        
        # 获取议价空间系数
        negotiation = candidate_data.get('报价商议空间', '') or ''
        negotiation_factor = 1.0
        if '有一些商议空间' in negotiation:
            negotiation_factor = 0.9
        elif '有较大商议空间' in negotiation:
            negotiation_factor = 0.7
        
        # 使用AIPE价格（如果存在），否则使用翻译价格
        actual_price = None
        price_type = None
        
        if aipe_price is not None:
            actual_price = aipe_price * negotiation_factor
            price_type = 'aipe'
        elif trans_price is not None:
            actual_price = trans_price * negotiation_factor
            price_type = 'translation'
        
        if actual_price is None:
            return {
                "score": 0,
                "level": "无报价",
                "original_price": None,
                "adjusted_price": None,
                "is_below_target": False,
                "is_below_max": False
            }
        
        # 查找价格规则
        price_config = self.price_rules.get('aipe', {}).get(lang_pair_normalized) or \
                       self.price_rules.get('translation', {}).get(lang_pair_normalized)
        
        if price_config is None:
            if self.price_rules_meta.get("source") == "local":
                target = 0.03
                max_price = 0.04
            else:
                raise PricingRulesError(
                    f"找不到语言对「{lang_pair}」({lang_pair_normalized}) 的价格规则。"
                    "请在 Lark「评分规则配置」表维护该语言对后重试。"
                )
        else:
            target = price_config.get('target', 0.03)
            max_price = price_config.get('max', 0.04)
        
        # 计算得分
        hard_limit = 0.10
        
        if actual_price <= target:
            score = 50
            level = "低于预期"
            is_below_target = True
            is_below_max = True
        elif actual_price <= max_price:
            # 预期<单价≤上限
            score = 25 + 25 * (max_price - actual_price) / (max_price - target)
            level = "预期-上限之间"
            is_below_target = False
            is_below_max = True
        elif actual_price <= hard_limit:
            # 上限<单价≤0.1
            score = 25 - 25 * (actual_price - max_price) / (hard_limit - max_price)
            level = "高于上限"
            is_below_target = False
            is_below_max = False
        else:
            score = 0
            level = "超过硬上限"
            is_below_target = False
            is_below_max = False
        
        return {
            "score": round(score, 1),
            "level": level,
            "original_price": aipe_price if price_type == 'aipe' else trans_price,
            "adjusted_price": round(actual_price, 4),
            "negotiation_factor": negotiation_factor,
            "target": target,
            "max": max_price,
            "rule_source": self.price_rules_meta.get("source", "unknown"),
            "rule_count": self.price_rules_meta.get("count", 0),
            "is_below_target": is_below_target,
            "is_below_max": is_below_max
        }
    
    def calculate_experience_match(self, candidate_data: Dict) -> Dict:
        """
        计算资历匹配度
        
        返回：
        - match_level: "完全符合" / "部分符合" / "完全不符合"
        - primary_score: 主要关键词得分 (0-30)
        - secondary_score: 次要关键词得分 (0-20)
        - total_score: 资历维度总分 (0-50)
        """
        project_exp = str(candidate_data.get('项目经历', ''))
        other_exp = str(candidate_data.get('其他相关经历', ''))
        familiar_ip = str(candidate_data.get('熟悉的IP', ''))
        services = candidate_data.get('提供的服务', [])
        
        total_text = project_exp + ' ' + other_exp + ' ' + familiar_ip
        
        # ========== 主要关键词评分 (30分) ==========
        # 要求：泛文娱领域翻译和校对字数≥50万字
        
        # 优先读 LLM 解析字段（由 parse_resumes.py 写入，准确率最高）
        parsed_word_count  = candidate_data.get('_parsed_word_count')   # int or None
        parsed_years       = candidate_data.get('_parsed_years')         # float or None
        parsed_project_cnt = candidate_data.get('_parsed_project_cnt')  # int or None
        parsed_entities    = candidate_data.get('_parsed_entities', '') # str
        has_parsed = parsed_word_count is not None  # 0 也视为已解析
        
        # 提取总字数（有 LLM 解析结果则直接用，否则走正则 fallback）
        total_words = parsed_word_count if has_parsed else self._extract_word_count(total_text)
        
        # 计算其他字数来源
        years = self._extract_years(total_text)
        # 年限估算：必须有游戏行业实际翻译/本地化从业经验才生效
        # 光有关键词不够，需要文本里出现「游戏翻译/本地化项目」的实质从业描述
        # 且必须同时出现数字（字数/项目数/年份区间），说明有真实项目记录
        GAME_WORK_KEYWORDS = [
            'game locali', 'game translat', 'video game', 'locali',
            '游戏翻译', '游戏本地化', '游戏项目', 'game content',
            'lqa', 'linguistic testing', '本地化测试',
        ]
        # 年限估算（有 LLM 解析年限则优先用，否则走正则）
        if has_parsed and parsed_years is not None:
            years = parsed_years
            word_count_from_years = 0  # 已有精确字数，不需要年限估算
        else:
            years = self._extract_years(total_text)
            # 年限估算：必须有游戏行业实际翻译/本地化从业经验才生效
            GAME_WORK_KEYWORDS = [
                'game locali', 'game translat', 'video game', 'locali',
                '游戏翻译', '游戏本地化', '游戏项目', 'game content',
                'lqa', 'linguistic testing', '本地化测试',
            ]
            import re as _re
            has_business_numbers = bool(_re.search(
                r'\d+[Kk]\s*(?:words?|chars?)|\d+\s*(?:万字|words?|hours?|小时|字)',
                total_text, _re.IGNORECASE
            ))
            has_game_work_exp = (
                any(kw in total_text.lower() for kw in GAME_WORK_KEYWORDS)
                and has_business_numbers
            )
            word_count_from_years = (years * 100000) if has_game_work_exp else 0
        
        # 项目估算（有 LLM 解析项目数则优先用）
        if has_parsed and parsed_project_cnt is not None:
            # 已知项目数，如果已有实际字数则不需要项目估算
            # 如果字数为 0 且项目数有值，按 50,000 字/项（保守估算）
            if total_words == 0 and parsed_project_cnt > 0:
                project_words = parsed_project_cnt * 50000
            else:
                project_words = 0  # 已有字数，项目估算不叠加
        else:
            project_words = self._estimate_project_words(total_text)
        
        # 取最高值
        final_word_count = max(total_words, word_count_from_years, project_words)
        
        # 主要关键词得分
        threshold = 500000
        if final_word_count >= threshold:
            primary_score = 30
            primary_status = "完全符合"
        else:
            primary_score = 30 * (final_word_count / threshold)
            primary_status = "部分符合"
        
        # ========== 次要关键词评分 (20分) ==========
        # 次要关键词1：知名游戏项目/厂商经验 (10分)
        # 次要关键词2：LQA/配音/咨询经验 (10分)
        
        secondary_score = 0
        secondary_items = []
        secondary_details = []
        
        # ========== 次要关键词1：知名游戏/厂商经验 (10分) ==========
        # 优先使用 LLM 解析的知名实体（如果有）
        if has_parsed and parsed_entities:
            # LLM 已识别知名实体，直接视为命中
            notable_games   = [e.strip() for e in parsed_entities.split(',') if e.strip()][:5]
            notable_vendors = []
        else:
            # fallback：正则匹配
            notable_games   = self._check_notable_games(total_text)
            notable_vendors = self._check_notable_vendors(total_text)
        
        if notable_games or notable_vendors:
            secondary_score += 10
            secondary_items.append("知名游戏/厂商经验")
            if notable_games:
                secondary_details.append(f"知名游戏: {notable_games}")
            if notable_vendors:
                secondary_details.append(f"知名厂商: {notable_vendors}")
        
        # ========== 次要关键词2：LQA/配音/本地化咨询经验 (10分) ==========
        # 注1：LQA = Language Quality Assurance，本地化语言测试
        lqa_related = self._check_lqa_experience(services, total_text)
        
        if lqa_related:
            secondary_score += 10
            secondary_items.append("LQA/配音/咨询经验")
            secondary_details.append(f"相关经验: {lqa_related}")
        
        # 总分
        total_score = primary_score + secondary_score
        
        # 判定匹配级别
        # 完全符合 = 主要完全符合 AND 次要满足（知名游戏/厂商 OR LQA，任一10分即可）
        # 业务语义：有知名项目 OR 有LQA，都代表专业深度，有其一即视为次要维度满足
        if primary_status == "完全符合" and secondary_score >= 10:
            match_level = "完全符合"
        # 部分符合 = 有任意满足
        elif primary_score > 0 or secondary_score > 0:
            match_level = "部分符合"
        else:
            match_level = "完全不符合"
        
        return {
            "match_level": match_level,
            "primary_score": round(primary_score, 1),
            "primary_status": primary_status,
            "word_count": final_word_count,
            "secondary_score": secondary_score,
            "secondary_items": secondary_items,
            "secondary_details": secondary_details,
            "notable_games": notable_games[:3] if notable_games else [],
            "notable_vendors": notable_vendors[:3] if notable_vendors else [],
            "lqa_items": lqa_related,
            "total_score": round(total_score, 1)
        }
    
    def calculate_final_result(self, candidate_data: Dict) -> Dict:
        """
        计算最终结果 - 严格按5.3流程
        
        流程：
        1）计算单价维度分值
        2）计算资历维度分值
        3）加总得出初始评分并确定档位
        4）通过加减分微调（上下浮动一个档位）
        """
        # 1) 计算单价维度
        price_result = self.calculate_price_score(candidate_data)
        
        # 2) 计算资历维度
        exp_result = self.calculate_experience_match(candidate_data)
        
        # 3) 加总得出初始评分
        initial_score = price_result['score'] + exp_result['total_score']
        
        # 判定基础档位（基于组合条件，这是V2引擎核心逻辑）
        base_tier = self._determine_base_tier(
            price_result['is_below_target'],
            price_result['is_below_max'],
            exp_result['match_level']
        )
        
        # 4) 计算加减分
        bonus_penalty = self._calculate_bonus_penalty(candidate_data)
        adjustment = bonus_penalty['net_adjustment']
        
        # 应用微调（上下浮动一个档位）
        final_tier = self._adjust_tier(base_tier, adjustment)
        
        # 最终评分（用于展示，不影响档位判定）
        final_score = max(0, min(100, initial_score + adjustment))
        
        return {
            "initial_score": initial_score,
            "final_score": final_score,
            "base_tier": base_tier,
            "final_tier": final_tier,
            "tier_name": self._get_tier_name(final_tier),
            "price_result": price_result,
            "experience_result": exp_result,
            "bonus_penalty": bonus_penalty
        }
    
    def _determine_base_tier(self, is_below_target: bool, is_below_max: bool, 
                            match_level: str) -> str:
        """
        判定基础档位（基于组合条件）- V2引擎核心逻辑
        
        S: 单价≤预期 AND 完全符合
        A: (单价≤预期 AND 部分符合) OR (单价≤上限 AND 完全符合)
        B: 单价≤上限 AND 部分符合
        C: 单价>上限 OR 完全不符合
        """
        if is_below_target and match_level == "完全符合":
            return "S"
        elif (is_below_target and match_level == "部分符合") or \
             (is_below_max and match_level == "完全符合"):
            return "A"
        elif is_below_max and match_level == "部分符合":
            return "B"
        else:
            return "C"
    
    def _adjust_tier(self, base_tier: str, adjustment: int) -> str:
        """
        通过加减分微调档位（上下浮动一个档位）
        """
        tier_order = ['C', 'B', 'A', 'S']
        
        try:
            current_idx = tier_order.index(base_tier)
        except ValueError:
            return base_tier
        
        # 正分加分：向更高档位移动
        # 负分减分：向更低档位移动
        if adjustment >= 3:  # 加分显著
            new_idx = min(len(tier_order) - 1, current_idx + 1)
        elif adjustment <= -3:  # 减分显著
            new_idx = max(0, current_idx - 1)
        else:
            new_idx = current_idx
        
        return tier_order[new_idx]
    
    def _get_tier_name(self, tier: str) -> str:
        """获取档位名称 - V2引擎定义"""
        names = {
            'S': '优先录用',
            'A': '优先联系',
            'B': '可备选',
            'C': '淘汰'
        }
        return names.get(tier, '淘汰')
    
    def _calculate_bonus_penalty(self, candidate_data: Dict) -> Dict:
        """计算加减分项"""
        project_exp = str(candidate_data.get('项目经历', ''))
        other_exp = str(candidate_data.get('其他相关经历', ''))
        total_text = project_exp + ' ' + other_exp
        
        bonus = 0
        penalty = 0
        bonus_reasons = []
        penalty_reasons = []
        
        # 加分项
        years = self._extract_years(total_text)
        # 从业超过10年：必须是游戏/文娱领域，纯营销/翻译通用领域不算
        # 游戏领域判定：长词直接子串，短词（≤5字符）用词边界防误匹配
        import re as _re2
        GAME_WORK_BONUS_KW_LONG = [
            'game locali', 'game translat', 'video game', 'locali',
            '游戏翻译', '游戏本地化', '游戏项目', 'game content', 'lqa',
            'gaming',
        ]
        GAME_WORK_BONUS_KW_SHORT = ['game', '游戏']  # 短词需词边界
        has_game_industry = (
            any(kw in total_text.lower() for kw in GAME_WORK_BONUS_KW_LONG)
            or any(bool(_re2.search(r'(?<![\w\u4e00-\u9fff])' + _re2.escape(kw) + r'(?![\w\u4e00-\u9fff])', total_text, _re2.IGNORECASE))
                   for kw in GAME_WORK_BONUS_KW_SHORT)
        )
        if years >= 10 and has_game_industry:
            bonus += 3
            bonus_reasons.append("游戏/文娱领域从业超过10年")
        
        # 多品类经验
        game_types = ['RPG', 'FPS', 'MOBA', 'SLG', '卡牌', '休闲', '动作', '冒险']
        type_count = sum(1 for t in game_types if t in total_text)
        if type_count >= 3:
            bonus += 2
            bonus_reasons.append(f"多品类经验({type_count}类)")
        
        # 减分项
        if type_count == 1:
            penalty += 2
            penalty_reasons.append("游戏品类单一")
        
        return {
            "bonus": bonus,
            "penalty": penalty,
            "net_adjustment": bonus - penalty,
            "bonus_reasons": bonus_reasons,
            "penalty_reasons": penalty_reasons
        }
    
    # ============ 辅助方法 ============
    
    def _normalize_lang_pair(self, lang_pair: str) -> str:
        """
        标准化语言对格式
        
        支持格式：
        - en>ru, en→ru, en到ru
        - English to Russian, English>Russian
        - English>Russian
        """
        if lang_pair is None:
            return ''
        
        lang_pair = str(lang_pair).strip()
        
        # 语言名称映射
        lang_map = {
            'english': 'en',
            'chinese': 'zh-CN',
            'simplified chinese': 'zh-CN',
            'japanese': 'ja',
            'korean': 'ko',
            'vietnamese': 'vi',
            'thai': 'th',
            'indonesian': 'id',
            'russian': 'ru',
            'german': 'de',
            'french': 'fr',
            'italian': 'it',
            'spanish': 'es',
            'polish': 'pl',
            'dutch': 'nl',
            'turkish': 'tr',
            'malay': 'ms',
            'arabic': 'ar',
            'portuguese': 'pt',
        }
        
        # 处理 "English to Russian" 格式
        lower_pair = lang_pair.lower()
        if ' to ' in lower_pair:
            parts = lower_pair.split(' to ')
            if len(parts) == 2:
                src = parts[0].strip()
                tgt = parts[1].strip()
                src_code = lang_map.get(src, src)
                tgt_code = lang_map.get(tgt, tgt)
                return f"{src_code}>{tgt_code}"
        
        # 处理标准格式
        lang_pair = lang_pair.replace('→', '>').replace('到', '>').replace(' ', '')
        
        # 处理 "English>Russian" 格式
        if '>' in lang_pair:
            parts = lang_pair.split('>')
            if len(parts) == 2:
                src = parts[0].lower().strip()
                tgt = parts[1].lower().strip()
                src_code = lang_map.get(src, src)
                tgt_code = lang_map.get(tgt, tgt)
                return f"{src_code}>{tgt_code}"
        
        return lang_pair
    
    def _to_float(self, value) -> Optional[float]:
        """转换为浮点数"""
        if value is None:
            return None
        try:
            return float(value)
        except:
            return None
    
    def _extract_word_count(self, text: str) -> int:
        """提取字数（累加所有匹配）"""
        total = 0
        
        # 模式1: xxx,xxx字 或 xxxxxx字
        pattern1 = re.findall(r'(\d{1,3}(?:,\d{3})+|\d{5,})\s*字', text)
        for match in pattern1:
            num = int(match.replace(',', ''))
            total += num
        
        # 模式2: xx万字
        pattern2 = re.findall(r'(\d+)\s*万\s*字?', text)
        for match in pattern2:
            total += int(match) * 10000
        
        # 模式3: 英文格式 xxx,xxx words (英文简历常用)
        pattern3 = re.findall(r'(\d{1,3}(?:,\d{3})+)\s*(?:words?|chars?)', text, re.IGNORECASE)
        for match in pattern3:
            num = int(match.replace(',', ''))
            total += num
        
        # 模式4: 英文格式 xxK words (如 40K words)
        pattern4 = re.findall(r'(\d+(?:\.\d+)?)\s*[Kk]\s*(?:words?|chars?)', text, re.IGNORECASE)
        for match in pattern4:
            num = float(match) * 1000
            total += int(num)
        
        # 模式5: 英文格式 xxxxx words (纯数字)
        pattern5 = re.findall(r'(\d{4,})\s*(?:words?|chars?)', text, re.IGNORECASE)
        for match in pattern5:
            total += int(match)

        # 模式6: 空格分隔千位数字 (欧洲格式，如 1 000 000 words)
        pattern6 = re.findall(r'(\d{1,3}(?:\s\d{3})+)\s*(?:words?|chars?)', text, re.IGNORECASE)
        for match in pattern6:
            num = int(match.replace(' ', ''))
            total += num

        # 模式7: million words (如 over 1 million words)
        pattern7 = re.findall(r'(\d+(?:\.\d+)?)\s*million\s*(?:words?|chars?)?', text, re.IGNORECASE)
        for match in pattern7:
            total += int(float(match) * 1_000_000)

        # 模式8: 游戏项目列表中 trans/proof/translation 上下文的逗号千位数字
        # 例: WoW (trans 500,000, proof 500,000) / Mass Effect (trans 400,000)
        pattern8 = re.findall(
            r'(?:trans(?:lation)?|proof(?:reading)?|edit(?:ing)?)\s+(\d{1,3}(?:,\d{3})+)',
            text, re.IGNORECASE
        )
        for match in pattern8:
            total += int(match.replace(',', ''))

        return total
    
    def _check_notable_games(self, text: str) -> List[str]:
        """
        注2：检测知名游戏
        满足以下一项则可视作"知名游戏"：
        - 3A 游戏
        - 商业成绩突出
        - 获得媒体/奖项认可
        - 知名 IP 改编或系列作品
        - 在行业或玩家群体中有广泛讨论
        """
        text_lower = text.lower()
        matched_games = []
        
        # 3A游戏 / 知名大作
        aaa_games = [
            'PUBGM', '绝地求生', '王者荣耀', '原神', '幻塔', 'Genshin Impact',
            '太吾绘卷', '黑神话', '黑神话：悟空', 'Black Myth',
            '艾尔登法环', 'Elden Ring', '塞尔达', 'Zelda',
            '最终幻想', 'Final Fantasy', 'FF14', 'FFXIV',
            '使命召唤', 'Call of Duty', 'COD',
            '战地', 'Battlefield',
            '刺客信条', 'Assassin\'s Creed',
            '巫师', 'The Witcher', 'Cyberpunk', '赛博朋克',
            'GTA', 'Grand Theft Auto',
            'Red Dead Redemption', '荒野大镖客',
            '战神', 'God of War',
            '最后生还者', 'The Last of Us',
            '神秘海域', 'Uncharted',
            '血源诅咒', 'Bloodborne',
            '黑暗之魂', 'Dark Souls',
            '只狼', 'Sekiro',
            '怪物猎人', 'Monster Hunter', 'MH',
            '生化危机', 'Resident Evil',
            '鬼泣', 'Devil May Cry', 'DMC',
            '仁王', 'Nioh',
            '对马岛之魂', 'Ghost of Tsushima',
            '地平线', 'Horizon',
            '死亡搁浅', 'Death Stranding',
        ]
        
        # 知名IP / 热门手游
        popular_ips = [
            '哈利波特', 'Harry Potter',
            '宝可梦', 'Pokemon', 'Pokémon',
            '英雄联盟', 'League of Legends', 'LOL',
            'DOTA', 'DOTA2',
            'CS', 'CS:GO', 'CS2', 'Counter-Strike',
            'Valorant', '无畏契约',
            'Apex', 'Apex Legends',
            'Fortnite', '堡垒之夜',
            'Minecraft', '我的世界',
            'Roblox',
            'Mobile Legends', '决胜巅峰', 'MLBB',
            'Honor of Kings', 'Arena of Valor',
            'Free Fire',
            'PUBG', '和平精英',
            'Call of Duty Mobile', 'CODM', '使命召唤手游',
            '原神', '崩坏', 'Honkai', '星穹铁道', 'Star Rail',
            '明日方舟', 'Arknights',
            '少女前线', 'Girls\' Frontline',
            '碧蓝航线', 'Azur Lane',
            'FGO', 'Fate/Grand Order',
            '阴阳师', 'Onmyoji',
            '第五人格', 'Identity V',
            '光遇', 'Sky: Children of Light',
        ]
        
        # 高口碑独立游戏
        indie_hits = [
            '风之旅人', 'Journey',
            '哈迪斯', 'Hades',
            '空洞骑士', 'Hollow Knight',
            '茶杯头', 'Cuphead',
            'Inside',
            'Limbo',
            'Braid',
            'Celeste', '蔚蓝',
            '星露谷物语', 'Stardew Valley',
            '死亡细胞', 'Dead Cells',
            '杀戮尖塔', 'Slay the Spire',
            '哈迪斯', 'Hades',
            '双人成行', 'It Takes Two',
            '奥日', 'Ori',
            'Gris',
            'Journey',
            'Stray', '迷失',
            'Cult of the Lamb', '咩咩启示录',
            'Vampire Survivors', '吸血鬼幸存者',
        ]
        
        # 检测匹配（词边界，避免 cosmetics 误匹配 CS 等短词）
        for game in aaa_games + popular_ips + indie_hits:
            # 短词（<=3字符）要求词边界；长词直接子串匹配
            if len(game) <= 5:
                pattern = r'(?<![\w\u4e00-\u9fff])' + re.escape(game) + r'(?![\w\u4e00-\u9fff])'
                matched = bool(re.search(pattern, text, re.IGNORECASE))
            else:
                matched = game.lower() in text_lower or game in text
            if matched and game not in matched_games:
                matched_games.append(game)
        
        return matched_games[:5]  # 最多返回5个
    
    def _check_notable_vendors(self, text: str) -> List[str]:
        """
        注3：检测知名厂商
        满足以下一项则可视作"知名厂商"：
        - 全球头部开发商/发行商
        - 头部手游发行商
        - 高口碑独立游戏工作室
        - 大型厂商旗下的内部工作室
        - 知名游戏本地化/语言服务提供商(LSP)
        """
        text_lower = text.lower()
        matched_vendors = []
        
        # 欧美头部开发商/发行商
        western_tier1 = [
            'Riot Games', 'Riot',
            'Blizzard', '暴雪',
            'Rockstar',
            'EA', 'Electronic Arts',
            'Ubisoft', '育碧',
            'Bethesda',
            'Valve',
            'CD Projekt Red', 'CDPR',
            '2K',
            'Activision',
            'Epic Games', 'Epic',
            'Naughty Dog',
            'Santa Monica Studio',
            'Insomniac',
            'Bungie',
            '343 Industries',
        ]
        
        # 日韩头部开发商/发行商
        jp_kr_tier1 = [
            'Nintendo', '任天堂',
            'Sony', '索尼', 'PlayStation', 'PS',
            'Square Enix', 'SE',
            'Capcom', '卡普空',
            'Sega', '世嘉',
            'Bandai Namco', '万代南梦宫',
            'FromSoftware',
            'Nexon',
            'NCSoft',
            'Krafton',
            'Smilegate',
            'Pearl Abyss',
            'Netmarble',
        ]
        
        # 中国头部开发商/发行商
        china_tier1 = [
            '腾讯', 'Tencent', '天美', 'TiMi', '光子',
            '网易', 'NetEase',
            '米哈游', 'MiHoYo', 'HoYoverse',
            '莉莉丝', 'Lilith',
            '字节', 'ByteDance',
            '叠纸', 'Paper Games',
            '鹰角', 'Hypergryph',
            '散爆', 'Sunborn',
            '心动', 'X.D.',
            '英雄游戏', 'Hero Games',
            '三七', '37Games',
            'FunPlus', '趣加',
            'IGG',
            '完美世界', 'Perfect World',
        ]
        
        # 头部手游发行商
        mobile_publishers = [
            'Supercell',
            'King',
            'Playrix',
            'FunPlus', '趣加',
            'Scopely',
            'Zynga',
            'Century Games',
            'Elex',
            'Outfit7',
            'Voodoo',
            'Garena',
            'Glu',
            'Machine Zone',
        ]
        
        # 知名LSP (语言服务提供商)
        notable_lsps = [
            'Keywords Studios', 'Keywords',
            'PTW', 'Pole To Win',
            'Altagram',
            'Terra Translations',
            'Testronic',
            'Lionbridge',
            'TransPerfect',
            'ULTRA',
            'MoGi Group',
            'Nitro',
            'Andovar',
            'Synthesis',
            'Berba',
        ]
        
        # 高口碑独立工作室
        indie_studios = [
            'Thatgamecompany',
            'Supergiant Games',
            'Playdead',
            'Team Cherry',
            'ConcernedApe',
            'Studio MDHR',
            'Mojang',
            'Mossmouth',
            'Number None',
            'DrinkBox',
            'House House',
        ]
        
        # 检测匹配（短词要求词边界）
        all_vendors = western_tier1 + jp_kr_tier1 + china_tier1 + mobile_publishers + notable_lsps + indie_studios
        for vendor in all_vendors:
            if len(vendor) <= 5:
                pattern = r'(?<![\w\u4e00-\u9fff])' + re.escape(vendor) + r'(?![\w\u4e00-\u9fff])'
                matched = bool(re.search(pattern, text, re.IGNORECASE))
            else:
                matched = vendor.lower() in text_lower or vendor in text
            if matched and vendor not in matched_vendors:
                matched_vendors.append(vendor)
        
        return matched_vendors[:5]  # 最多返回5个
    
    def _check_lqa_experience(self, services: List, text: str) -> List[str]:
        """
        注1：检测LQA/配音/本地化咨询经验
        LQA = Language Quality Assurance，本地化语言测试
        """
        text_lower = text.lower()
        matched_items = []
        
        # LQA相关
        lqa_keywords = [
            'LQA', 'linguistic testing', 'localization testing',
            '语言测试', '本地化测试', '跑测', 'linguistic QA',
            'language quality assurance', '语言质量',
        ]
        
        # 配音相关
        voice_keywords = [
            '配音', 'voice over', 'VO', 'dubbing', 'audio',
            'voice acting', 'narration', 'audiobook',
        ]
        
        # 咨询/QA相关
        qa_keywords = [
            '咨询', 'consulting', 'consultant',
            'QA', 'quality assurance', '质量保证',
            '测试', 'testing', '审校', 'review',
            '本地化工程', 'localization engineering',
            'CAT', 'TM', 'TB', '术语库', '记忆库',
        ]
        
        # 检查服务列表
        services_text = ' '.join(str(s) for s in (services or [])).lower()
        
        # 检测LQA
        for kw in lqa_keywords:
            if kw.lower() in text_lower or kw.lower() in services_text:
                if 'LQA' not in matched_items and '语言测试' not in matched_items:
                    matched_items.append('LQA/语言测试')
                break
        
        # 检测配音
        for kw in voice_keywords:
            if kw.lower() in text_lower or kw.lower() in services_text:
                if '配音' not in matched_items:
                    matched_items.append('配音/音频')
                break
        
        # 检测咨询
        for kw in qa_keywords:
            if kw.lower() in text_lower or kw.lower() in services_text:
                if '咨询/QA' not in matched_items:
                    matched_items.append('本地化咨询/QA')
                break
        
        return matched_items
    
    def _extract_years(self, text: str) -> int:
        """
        提取工作年限
        
        支持格式：
        - 5年经验 / 5 years experience
        - since 2012 / 自2012年起
        - 2012-2024 / 2012至2024
        - over 10 years / 10+ years
        """
        if not text:
            return 0
        
        text_lower = text.lower()
        
        # 模式1: 直接数字 + 年/years
        patterns = [
            r'(\d+)\s*年\s*(经验|从业|工作)',
            r'(\d+)\s*years?\s*(of\s*)?(experience|exp)?',
            r'(\d+)\s*yrs?',
            r'(\d+)\+?\s*years?',  # 10+ years
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text_lower, re.IGNORECASE)
            if match:
                return int(match.group(1))
        
        # 模式2: since + 年份（支持月份）
        since_pattern = r'since\s*(?:january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)?\s*(\d{4})'
        match = re.search(since_pattern, text_lower)
        if match:
            start_year = int(match.group(1))
            current_year = 2026
            years = current_year - start_year
            return max(0, years)
        
        # 模式3: 年份范围 2012-2024 / 2012 to 2024
        range_patterns = [
            r'(\d{4})\s*[-~至to]\s*(\d{4}|present|now|current)',
            r'(\d{4})\s*[-~至]\s*至今',
        ]
        
        for pattern in range_patterns:
            match = re.search(pattern, text_lower, re.IGNORECASE)
            if match:
                start_year = int(match.group(1))
                end_str = match.group(2).lower() if match.group(2) else "至今"
                if end_str in ['present', 'now', 'current', '至今']:
                    end_year = 2026
                else:
                    end_year = int(end_str)
                years = end_year - start_year
                return max(0, years)
        
        # 模式4: over/more than + 数字 + years
        over_pattern = r'(over|more than|over)\s*(\d+)\s*years?'
        match = re.search(over_pattern, text_lower)
        if match:
            return int(match.group(2))
        
        # 模式5: 中文数字 + 年
        chinese_numbers = {
            '一': 1, '二': 2, '两': 2, '三': 3, '四': 4, '五': 5,
            '六': 6, '七': 7, '八': 8, '九': 9, '十': 10,
            '十一': 11, '十二': 12, '十三': 13, '十四': 14, '十五': 15,
        }
        for cn_num, num in chinese_numbers.items():
            if f'{cn_num}年' in text or f'{cn_num}年经验' in text:
                return num
        
        return 0
    
    def _estimate_project_words(self, text: str) -> int:
        """
        根据项目类型估算字数。
        策略：
        1. 中文关键词（SLG/AAA/3A）直接按权重估算
        2. 检测文本中出现的知名游戏数量，按均值估算（100,000字/项）
        3. 项目列表里项目数量多（≥10个）且有游戏本地化上下文，给基础估算
        取三者之和（不重复计算，知名游戏已包含在项目列表里，只取最高路径）
        """
        import re as _re

        # 路径1：中文关键词权重
        weights = {
            '轻量级': 10000,
            'SLG': 100000,
            '中型': 100000,
            'AAA': 200000,
            '3A': 200000,
        }
        kw_total = 0
        for keyword, weight in weights.items():
            if keyword in text:
                kw_total += weight

        # 路径2：知名游戏命中数量估算
        # 每个知名游戏项目估算 100,000 字（中型游戏均值）
        notable = self._check_notable_games(text)
        known_game_total = len(notable) * 100000

        # 路径3：从简历全文中匹配游戏/工作室/LSP 关键词，统计命中数量
        # 精确计数已知实体，按均值估算（比短行统计更可靠）
        # - 知名游戏：已在 known_game_total 里，这里额外统计「出现次数」
        # - 知名厂商/LSP：有多个说明合作方多元，有实际项目经验
        all_vendors = self._check_notable_vendors(text)
        # 游戏×100K + 厂商×50K（厂商不等于独立项目，保守一些）
        entity_total = len(notable) * 100000 + len(all_vendors) * 50000

        # 取最高路径（避免叠加）
        project_words = max(kw_total, known_game_total, entity_total)
        return project_words


# ============ 测试代码 ============

if __name__ == "__main__":
    engine = ResumeScreeningEngineV2()
    
    # 李全鸿数据
    candidate = {
        "姓名": "李全鸿",
        "语言对": "zh-CN>en",
        "人工翻译单价": 0.04,
        "AIPE单价": 0.03,
        "报价商议空间": "有一些商议空间",
        "提供的服务": ["翻译", "AIPE", "校对", "LQA"],
        "项目经历": """《绝地求生手游》(PUBGM)，中英翻译，300,000字
《决胜巅峰》（Mobile Legends: Bang Bang）, 英中审校, 150,000字
《太吾绘卷》，AIPE，350,000字
《矿野求生》，中英翻译，100,000字
《幻塔》，中英翻译，200,000字
《深空之眼》，中英翻译，100,000字
《胜利女神：新的希望》，中英翻译，100,000字
《龙迹之城》，中英翻译，180,000字
《完蛋！我被美女包围了 2》，中英翻译，80,000字
开放世界动作RPG游戏，中英翻译，200,000字""",
        "熟悉的IP": "",
        "其他相关经历": ""
    }
    
    # 计算结果
    result = engine.calculate_final_result(candidate)
    
    # 输出结果
    print("=" * 70)
    print("简历筛选结果 - 李全鸿（V2 引擎）")
    print("=" * 70)
    print()
    print(f"候选人: {candidate['姓名']}")
    print(f"语言对: {candidate['语言对']}")
    print()
    print("【单价维度】")
    print(f"  得分: {result['price_result']['score']}/50")
    print(f"  级别: {result['price_result']['level']}")
    print(f"  调整后单价: ${result['price_result']['adjusted_price']}")
    print(f"  是否≤预期: {result['price_result']['is_below_target']}")
    print(f"  是否≤上限: {result['price_result']['is_below_max']}")
    print()
    print("【资历维度】")
    exp = result['experience_result']
    print(f"  得分: {exp['total_score']}/50")
    print(f"  匹配级别: {exp['match_level']}")
    print(f"  主要关键词: {exp['primary_score']}/30")
    print(f"    - 字数: {exp['word_count']:,}")
    print(f"    - 状态: {exp['primary_status']}")
    print(f"  次要关键词: {exp['secondary_score']}/20")
    print(f"    - 满足项: {exp['secondary_items']}")
    if exp.get('notable_games'):
        print(f"    - 检测到的知名游戏: {exp['notable_games']}")
    if exp.get('notable_vendors'):
        print(f"    - 检测到的知名厂商: {exp['notable_vendors']}")
    if exp.get('lqa_items'):
        print(f"    - 检测到的LQA经验: {exp['lqa_items']}")
    print()
    print("【加减分】")
    print(f"  加分: {result['bonus_penalty']['bonus']}")
    print(f"    - {result['bonus_penalty']['bonus_reasons']}")
    print(f"  减分: {result['bonus_penalty']['penalty']}")
    print(f"    - {result['bonus_penalty']['penalty_reasons']}")
    print(f"  净调整: {result['bonus_penalty']['net_adjustment']:+d}")
    print()
    print("=" * 70)
    print("【最终结果】")
    print("=" * 70)
    print(f"初始评分: {result['initial_score']}/100")
    print(f"基础档位: {result['base_tier']}")
    print(f"最终档位: {result['final_tier']} ({result['tier_name']})")
    print(f"最终评分: {result['final_score']}/100")
    print("=" * 70)
