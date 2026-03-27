import requests
import json
import logging
import time
import copy
from typing import Dict, List, Any, Optional
import pandas as pd

class AIRetriever:
    """
    统一的AI检索接口 - 支持多个LLM提供商
    """
    
    # 支持的Kimi模型列表
    KIMI_MODELS = {
        'kimi-k2-turbo-preview': {
            'context': 262144,  # 256K上下文
            'description': 'K2 Turbo预览版，256K超大上下文，高性能推理',
            'recommended_for': '所有查询类型，特别是需要长上下文的复杂查询'
        },
        'moonshot-v1-8k': {
            'context': 8192,
            'description': '8K上下文，速度快，成本低，适合简单查询',
            'recommended_for': '标准查询、简单过滤'
        },
        'moonshot-v1-32k': {
            'context': 32768,
            'description': '32K上下文，适合复杂查询和数据分析',
            'recommended_for': '复杂查询、多条件组合、统计分析'
        },
        'moonshot-v1-128k': {
            'context': 131072,
            'description': '128K上下文，适合超长文本分析',
            'recommended_for': '超长文本、大批量数据分析'
        }
    }
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.logger = logging.getLogger(__name__)
        
        # 主LLM配置 (Kimi最新模型)
        primary_config = config.get('primary', {})
        self.primary_provider = primary_config.get('provider', 'kimi')
        self.primary_api_key = primary_config.get('api_key')
        # Kimi最新模型: kimi-k2-turbo-preview / moonshot-v1-8k / moonshot-v1-32k / moonshot-v1-128k
        self.primary_model = primary_config.get('model', 'kimi-k2-turbo-preview')
        self.primary_base_url = primary_config.get('base_url', 'https://api.moonshot.cn/v1')
        
        # 备用LLM配置 (也使用Kimi，但不同模型)
        fallback_config = config.get('fallback', {})
        self.fallback_provider = fallback_config.get('provider', 'kimi')
        self.fallback_api_key = fallback_config.get('api_key', self.primary_api_key)
        # 备用使用32K模型，处理更复杂的查询（当主模型失败时）
        self.fallback_model = fallback_config.get('model', 'moonshot-v1-32k')
        self.fallback_base_url = fallback_config.get('base_url', 'https://api.moonshot.cn/v1')
        
        # 策略配置
        strategy = config.get('strategy', {})
        self.temperature = strategy.get('temperature', 0.1)
        self.max_tokens = strategy.get('max_tokens', 4096)
        self.retry_attempts = strategy.get('retry_attempts', 3)
        self.retry_delay = strategy.get('retry_delay', 2)
        
        # 数据库schema（需要外部设置）
        self.database_schema = None
        
        # 记录当前使用的模型
        self.logger.info(f"AI检索器初始化完成，主模型: {self.primary_model}, "
                        f"备用模型: {self.fallback_model}")
    
    def set_database_schema(self, schema: Dict[str, Any]):
        """设置数据库schema信息"""
        self.database_schema = schema
    
    def select_model_for_query(self, query: str, complexity: str = 'auto') -> str:
        """
        根据查询选择合适的Kimi模型
        
        注意: 使用 kimi-k2-turbo-preview (256K上下文) 作为主模型，
        它足以处理所有类型的查询，无需频繁切换
        
        Args:
            query: 用户查询
            complexity: 复杂度级别 ('simple', 'normal', 'complex', 'auto')
        
        Returns:
            模型名称
        """
        # 如果主模型已经是K2 (256K上下文)，直接返回，无需切换
        if 'k2' in self.primary_model.lower():
            return self.primary_model
        
        if complexity == 'auto':
            # 自动判断复杂度
            query_len = len(query)
            word_count = len(query.split())
            
            # 复杂查询特征
            complex_indicators = ['统计', '分析', '对比', '比较', '分布', '多个', '详细', '全部', '所有']
            is_complex = any(indicator in query for indicator in complex_indicators)
            
            if is_complex or word_count > 15 or query_len > 200:
                complexity = 'complex'
            elif word_count > 8 or query_len > 100:
                complexity = 'normal'
            else:
                complexity = 'simple'
        
        # 根据复杂度选择模型 (仅当主模型不是K2时)
        if complexity == 'simple':
            return 'moonshot-v1-8k'  # 8K足够，速度快
        elif complexity == 'normal':
            return self.primary_model  # 使用配置的默认模型
        else:  # complex
            return 'moonshot-v1-32k'  # 32K处理复杂查询
    
    def call_llm(self, 
                 prompt: str, 
                 temperature: Optional[float] = None,
                 max_tokens: Optional[int] = None,
                 use_fallback: bool = False,
                 query: Optional[str] = None) -> str:
        """
        调用LLM
        
        Args:
            prompt: 提示词
            temperature: 温度参数
            max_tokens: 最大token数
            use_fallback: 是否使用备用LLM
            query: 原始用户查询（用于智能选择模型）
        
        Returns:
            LLM响应内容
        """
        temperature = temperature if temperature is not None else self.temperature
        max_tokens = max_tokens if max_tokens is not None else self.max_tokens
        
        provider = self.fallback_provider if use_fallback else self.primary_provider
        
        # 如果提供了查询且是Kimi，智能选择模型
        if query and provider == 'kimi' and not use_fallback:
            selected_model = self.select_model_for_query(query)
            if selected_model != self.primary_model:
                self.logger.info(f"智能选择模型: {selected_model} (查询: {query[:50]}...)")
                # 临时切换模型
                original_model = self.primary_model
                self.primary_model = selected_model
                try:
                    result = self._call_kimi(prompt, temperature, max_tokens, use_fallback)
                    return result
                finally:
                    self.primary_model = original_model
        
        for attempt in range(self.retry_attempts):
            try:
                if provider == 'anthropic':
                    return self._call_anthropic(prompt, temperature, max_tokens, use_fallback)
                elif provider == 'openai':
                    return self._call_openai(prompt, temperature, max_tokens, use_fallback)
                elif provider == 'kimi':
                    return self._call_kimi(prompt, temperature, max_tokens, use_fallback)
                else:
                    raise ValueError(f"不支持的LLM提供商: {provider}")
                    
            except Exception as e:
                self.logger.warning(f"LLM调用失败 (尝试 {attempt + 1}/{self.retry_attempts}): {e}")
                
                if attempt < self.retry_attempts - 1:
                    time.sleep(self.retry_delay)
                else:
                    # 最后一次尝试失败，切换到备用LLM
                    if not use_fallback and self.fallback_api_key:
                        self.logger.info("切换到备用LLM")
                        return self.call_llm(prompt, temperature, max_tokens, use_fallback=True)
                    else:
                        raise
    
    def _call_anthropic(self, prompt: str, temperature: float, max_tokens: int, use_fallback: bool = False) -> str:
        """调用Anthropic Claude"""
        url = "https://api.anthropic.com/v1/messages"
        
        api_key = self.fallback_api_key if use_fallback else self.primary_api_key
        model = self.fallback_model if use_fallback else self.primary_model
        
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }
        
        data = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [
                {"role": "user", "content": prompt}
            ]
        }
        
        response = requests.post(url, headers=headers, json=data, timeout=60)
        response.raise_for_status()
        
        result = response.json()
        return result['content'][0]['text']

    def _call_kimi(self, prompt: str, temperature: float, max_tokens: int, use_fallback: bool = False) -> str:
        """
        调用Kimi (Moonshot AI) API
        支持的模型:
        - moonshot-v1-8k: 8K上下文, 速度快
        - moonshot-v1-32k: 32K上下文, 适合复杂查询
        - moonshot-v1-128k: 128K上下文, 适合超长文本
        """
        api_key = self.fallback_api_key if use_fallback else self.primary_api_key
        model = self.fallback_model if use_fallback else self.primary_model
        base_url = self.fallback_base_url if use_fallback else self.primary_base_url
        
        url = f"{base_url}/chat/completions"
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        # Kimi最新API参数
        data = {
            "model": model,
            "messages": [
                {"role": "system", "content": "你是单细胞RNA-seq数据库查询专家，擅长理解用户意图并转换为精确的数据库查询条件。"},
                {"role": "user", "content": prompt}
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "top_p": 0.95,  # 增加多样性控制
            "presence_penalty": 0.0,
            "frequency_penalty": 0.0
        }
        
        # 根据模型设置超时 (K2模型可能需要更长时间)
        if 'k2' in model.lower():
            timeout = 180  # K2模型给更长的超时
        elif '128k' in model:
            timeout = 120
        elif '32k' in model:
            timeout = 90
        else:
            timeout = 60
        
        response = requests.post(url, headers=headers, json=data, timeout=timeout)
        response.raise_for_status()
        
        result = response.json()
        
        # 记录token使用情况
        if 'usage' in result:
            usage = result['usage']
            self.logger.debug(f"Token使用: prompt={usage.get('prompt_tokens', 0)}, "
                            f"completion={usage.get('completion_tokens', 0)}, "
                            f"total={usage.get('total_tokens', 0)}")
        
        return result['choices'][0]['message']['content']
    
    def _call_openai(self, prompt: str, temperature: float, max_tokens: int, use_fallback: bool = False) -> str:
        """调用OpenAI GPT"""
        url = "https://api.openai.com/v1/chat/completions"
        
        api_key = self.fallback_api_key if use_fallback else self.primary_api_key
        model = self.fallback_model if use_fallback else self.primary_model
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        data = {
            "model": model,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "temperature": temperature,
            "max_tokens": max_tokens
        }
        
        response = requests.post(url, headers=headers, json=data, timeout=60)
        response.raise_for_status()
        
        result = response.json()
        return result['choices'][0]['message']['content']
    
    
    
    def parse_natural_query(self, 
                          query: str, 
                          available_values: Dict[str, List[str]] = None) -> Dict[str, Any]:
        """
        解析自然语言查询为结构化条件
        """
        schema_desc = self._build_schema_description(available_values)
        
        system_prompt = f"""你是单细胞RNA-seq数据库查询专家。请将用户的自然语言查询转换为精确的数据库检索条件。

{schema_desc}

**核心规则（按优先级）：**

### 1. 【复合查询拆解】
用户查询通常包含多个概念，必须分别处理：
- "COVID-19免疫研究" → 疾病概念"COVID-19" + 主题概念"免疫"
- "肺癌10x数据" → 疾病概念"肺癌" + 平台概念"10x"
- "乳腺癌肝组织" → 疾病概念"乳腺癌" + 组织概念"肝"

### 2. 【多字段搜索策略】**
每个概念应该在多个相关字段中搜索：

**疾病概念**（如COVID-19、肺癌、乳腺癌）：
- 必须在 disease_clean 字段搜索（高质量标准化字段）
- 同时在 title 字段搜索（研究标题常含疾病名）
- 同时在 summary 字段搜索（摘要常含疾病描述）
- 在 disease_general 字段搜索（疾病大类）

**组织概念**（如肝、肺、血液）：
- 必须在 tissue_clean 字段搜索
- 同时在 tissue_location 字段搜索
- 同时在 title/summary 中搜索

**技术概念**（如10x、Smart-seq2）：
- 必须在 platform_clean 字段搜索
- 同时在 sequencing_platform 字段搜索
- 同时在 title/summary 中搜索

**主题概念**（如免疫、肿瘤微环境、T细胞）：
- 必须在 title 字段搜索
- 必须在 summary 字段搜索
- 可在 disease_clean 中搜索（如免疫相关疾病）

### 3. 【字段优先级】
- 疾病：disease_clean > disease_general > title > summary
- 组织：tissue_clean > tissue_location > title > summary  
- 平台：platform_clean > sequencing_platform > title > summary
- 主题关键词：title > summary > disease_clean

### 4. 【开放数据过滤】
**仅当用户明确提到"开放数据"、"可下载"、"open"等词时**，才设置 matrix_open = 1。
否则**不要**设置matrix_open过滤条件（因为数据库中60%记录的matrix_open为NULL）

### 5. 【匹配策略】
- 所有文本字段使用 partial_match（模糊匹配）
- 疾病名称尝试中英文映射（如"肺癌"→"Lung Cancer"）
- 避免使用 exact_match（精确匹配）

### 6. 【查询条件结构】
返回的filters中，partial_match应该包含多个字段的搜索条件，确保全面覆盖。

**返回JSON格式：**
{{
    "filters": {{
        "exact_match": {{}},
        "partial_match": {{
            "disease_clean": "疾病名称",
            "title": "关键词",
            "summary": "关键词",
            ...其他相关字段
        }},
        "boolean_match": {{}},
        "range_match": {{}}
    }},
    "intent": "查询意图描述",
    "keywords": ["关键词1", "关键词2"],
    "confidence": 0.95
}}

只返回JSON，不要其他内容。"""

        try:
            response = self.call_llm(
                f"{system_prompt}\n\n用户查询: {query}",
                temperature=0.1,
                query=query  # 传递原始查询以智能选择模型
            )
            
            # 清理和解析响应
            parsed = self._parse_json_response(response)
            
            self.logger.info(f"查询解析完成: {json.dumps(parsed, ensure_ascii=False)[:200]}")
            
            return parsed
            
        except Exception as e:
            self.logger.error(f"查询解析失败: {e}")
            # 返回基础结果
            return {
                "filters": {
                    "exact_match": {},
                    "partial_match": {"title": query},
                    "boolean_match": {},
                    "range_match": {}
                },
                "intent": query,
                "keywords": query.split(),
                "confidence": 0.3
            }
    
    def _build_schema_description(self, available_values: Optional[Dict] = None) -> str:
        """构建schema描述 - 包含标准化字段"""
        desc = """# 数据库字段说明

## 核心检索字段（高质量标准化字段）

### 疾病和组织（推荐使用 _clean 字段）
- disease_clean: 清洗后的疾病名称 (高质量，如: Lung Cancer, COVID-19, Breast Cancer, Glioblastoma)
- tissue_clean: 清洗后的组织名称 (如: Blood, Liver, Brain, Bone Marrow, Breast)
- platform_clean: 清洗后的测序平台 (如: 10x Genomics, Smart-seq2, Illumina NovaSeq 6000)

### 备用字段（原始数据）
- disease_general: 疾病大类 (原始数据，格式不统一)
- tissue_location: 组织位置 (原始数据)
- sequencing_platform: 测序平台 (原始数据)

### 数据可用性
- matrix_open: 表达矩阵是否开放下载 (1=开放, 0=不开放)
- raw_open: 原始数据是否开放下载 (1=开放, 0=不开放)
- matrix_exist: 表达矩阵是否存在 (1=存在, 0=不存在)

### 技术信息
- platform_clean: 清洗后的测序平台 (如: 10x Genomics, Smart-seq2, RNA-Seq, Illumina NovaSeq 6000)
- sample_type: 样本类型 (如: Tumor, Normal, PBMC, Single Cell)

### 研究信息
- title: 研究标题 (支持模糊搜索)
- summary: 研究摘要 (支持模糊搜索)
- source_database: 来源数据库 (小写: geo, sra, CellxGene, cngb)
- publication_date: 发表日期 (格式: YYYY-MM-DD)

### 其他
- sex: 性别 (Male, Female, Mixed, unknown)
- sample_type: 样本类型

### 元数据质量字段
- metadata_completeness: 元数据完整度 (0-1)
- metadata_quality_score: 元数据质量评分 (High/Medium/Low)
- is_duplicate: 是否重复样本 (true/false)
- sample_uid: 样本唯一标识
"""
        
        if available_values:
            desc += "\n\n## 常见字段值示例\n"
            # 优先显示clean字段
            priority_fields = ['disease_clean', 'tissue_clean', 'platform_clean', 
                              'disease_general', 'tissue_location', 'source_database']
            for field in priority_fields:
                if field in available_values and available_values[field]:
                    values = [str(v) for v in available_values[field][:10] if v]
                    if values:
                        desc += f"\n### {field}\n{', '.join(values)}\n"
        
        return desc
    
    def _parse_json_response(self, response: str) -> Dict[str, Any]:
        """解析JSON响应"""
        # 清理响应
        response = response.strip()
        
        # 移除markdown代码块标记
        if '```json' in response:
            response = response.split('```json')[1].split('```')[0]
        elif '```' in response:
            response = response.split('```')[1].split('```')[0]
        
        response = response.strip()
        
        # 解析JSON
        try:
            return json.loads(response)
        except json.JSONDecodeError as e:
            self.logger.error(f"JSON解析失败: {e}\n响应内容: {response}")
            raise
    
    def explain_results(self, 
                       query: str, 
                       results: pd.DataFrame, 
                       total_count: int) -> str:
        """生成结果解释"""
        if results.empty:
            return self._generate_empty_result_suggestion(query)
        
        # 构建统计摘要
        summary = self._build_result_summary(results, total_count)
        
        prompt = f"""请用简洁专业的中文总结这次检索结果。

用户查询: {query}

检索结果统计:
{json.dumps(summary, ensure_ascii=False, indent=2)}

要求：
1. 5-8句话，分段落
2. 说明数据集总数和显示数量
3. 总结主要数据来源、疾病类型、组织分布
4. 说明数据开放性情况
5. 给出使用建议

直接返回总结文本，不要标题。"""

        try:
            return self.call_llm(prompt, temperature=0.5)
        except Exception as e:
            self.logger.error(f"结果解释生成失败: {e}")
            return self._generate_basic_summary(results, total_count)
    
    def _build_result_summary(self, results: pd.DataFrame, total_count: int) -> Dict[str, Any]:
        """构建结果统计摘要"""
        summary = {
            'total': total_count,
            'shown': len(results),
            'statistics': {}
        }
        
        # 统计各维度分布（优先使用标准化字段）
        stat_fields = [
            'database_standardized', 'disease_standardized', 'disease_category',
            'tissue_standardized', 'platform_standardized', 'sample_type_standardized',
            'source_database', 'disease_general', 'disease',
            'tissue_location', 'sequencing_platform', 'sample_type'
        ]
        
        for field in stat_fields:
            if field in results.columns:
                counts = results[field].value_counts().head(5).to_dict()
                if counts:
                    summary['statistics'][field] = counts
        
        # 数据开放性
        if 'matrix_open' in results.columns:
            # 使用布尔类型转换避免 FutureWarning
            matrix_open_bool = results['matrix_open'].astype(bool)
            summary['data_availability'] = {
                'matrix_open': int(matrix_open_bool.sum()),
                'raw_open': int(results['raw_open'].astype(bool).sum()) if 'raw_open' in results.columns else 0
            }
        
        # 引用统计
        if 'citation_count' in results.columns:
            citations = results['citation_count'].dropna()
            if len(citations) > 0:
                summary['citations'] = {
                    'total': int(citations.sum()),
                    'average': float(citations.mean()),
                    'max': int(citations.max())
                }
        
        return summary
    
    def _generate_empty_result_suggestion(self, query: str) -> str:
        """生成空结果建议"""
        prompt = f"""用户查询"{query}"没有找到匹配结果。请给出3-5条实用的建议帮助用户优化查询。

建议要具体、可操作，例如：
- 放宽某个条件
- 使用更通用的术语
- 尝试相关的疾病或组织类型
- 检查拼写

直接返回建议列表，每行一条，用"•"开头。"""

        try:
            return self.call_llm(prompt, temperature=0.7)
        except:
            return """未找到匹配的数据集。建议：
• 尝试使用更通用的疾病或组织类型
• 放宽数据开放性要求
• 检查疾病名称拼写
• 尝试相关的疾病类别"""
    
    def _generate_basic_summary(self, results: pd.DataFrame, total_count: int) -> str:
        """生成基础总结"""
        summary_parts = [f"找到 {total_count} 条相关记录，显示前 {len(results)} 条。"]
        
        if 'source_database' in results.columns:
            top_sources = results['source_database'].value_counts().head(3)
            sources_str = ', '.join([f"{k}({v})" for k, v in top_sources.items()])
            summary_parts.append(f"主要来源: {sources_str}。")
        
        if 'disease' in results.columns:
            top_diseases = results['disease'].value_counts().head(3)
            diseases_str = ', '.join(top_diseases.index.tolist())
            summary_parts.append(f"涉及疾病: {diseases_str}。")
        
        if 'matrix_open' in results.columns:
            open_count = results['matrix_open'].fillna(False).sum()
            summary_parts.append(f"其中 {int(open_count)} 条数据开放下载。")
        
        return ' '.join(summary_parts)
    
    def suggest_queries(self, 
                       current_query: str, 
                       current_results: Optional[pd.DataFrame] = None) -> List[str]:
        """建议相关查询"""
        context = f"当前查询: {current_query}\n"
        
        if current_results is not None and not current_results.empty:
            context += "\n当前结果中包含:\n"
            
            if 'disease' in current_results.columns:
                diseases = current_results['disease'].value_counts().head(3).index.tolist()
                context += f"- 疾病: {', '.join(diseases)}\n"
            
            if 'tissue_location' in current_results.columns:
                tissues = current_results['tissue_location'].value_counts().head(3).index.tolist()
                context += f"- 组织: {', '.join(tissues)}\n"
            
            if 'sequencing_platform' in current_results.columns:
                platforms = current_results['sequencing_platform'].value_counts().head(3).index.tolist()
                context += f"- 测序平台: {', '.join(platforms)}\n"

        prompt = f"""{context}

请基于当前查询和结果，建议3-5个相关的查询方向。建议应该：
1. 与当前查询相关但角度不同
2. 可以更具体或更广泛
3. 关注不同维度（组织/技术/疾病等）
4. 用自然语言表达，用户可直接使用

每行一个建议，不要编号或bullet point。"""

        try:
            response = self.call_llm(prompt, temperature=0.7)
            suggestions = [s.strip('•-').strip() for s in response.split('\n') 
                          if s.strip() and len(s.strip()) > 10]
            return suggestions[:5]
        except Exception as e:
            self.logger.error(f"建议生成失败: {e}")
            return []
    
    def enhance_filters(self, 
                       filters: Dict[str, Any], 
                       available_data: pd.DataFrame) -> Dict[str, Any]:
        """
        增强过滤条件 - 自动扩展查询到相关字段
        
        核心功能：
        1. 将单个字段查询扩展到多个相关字段（OR搜索）
        2. 自动识别疾病/组织/平台/主题概念并映射到对应字段
        3. 中英文疾病名称映射
        """
        enhanced = copy.deepcopy(filters)
        
        # 确保partial_match存在
        if 'partial_match' not in enhanced:
            enhanced['partial_match'] = {}
        
        partial = enhanced['partial_match']
        
        # ========== 疾病概念扩展 ==========
        disease_keywords = []
        if 'disease_clean' in partial:
            disease_keywords.append(partial['disease_clean'])
        if 'disease_general' in partial:
            disease_keywords.append(partial['disease_general'])
        if 'disease' in partial:
            disease_keywords.append(partial['disease'])
            
        # 中英文疾病映射
        disease_mapping = {
            # 中文 -> 英文
            '肺癌': ['Lung Cancer', 'Lung Adenocarcinoma', 'Lung Carcinoma', 'NSCLC'],
            '乳腺癌': ['Breast Cancer', 'Breast Carcinoma', 'Breast Tumor'],
            '肝癌': ['Liver Cancer', 'Hepatocellular Carcinoma', 'HCC', 'Liver Tumor'],
            '胃癌': ['Gastric Cancer', 'Stomach Cancer', 'Gastric Carcinoma'],
            '肠癌': ['Colorectal Cancer', 'Colon Cancer', 'Rectal Cancer', 'CRC'],
            '结直肠癌': ['Colorectal Cancer', 'Colon Cancer', 'Rectal Cancer', 'CRC'],
            '胰腺癌': ['Pancreatic Cancer', 'Pancreatic Ductal Adenocarcinoma', 'PDAC'],
            '卵巢癌': ['Ovarian Cancer', 'Ovarian Carcinoma'],
            '前列腺癌': ['Prostate Cancer', 'Prostate Carcinoma'],
            '脑瘤': ['Brain Tumor', 'Glioma', 'Glioblastoma', 'GBM', 'Neuroblastoma'],
            '胶质瘤': ['Glioma', 'Glioblastoma', 'GBM', 'Astrocytoma'],
            '黑色素瘤': ['Melanoma'],
            '白血病': ['Leukemia', 'AML', 'ALL', 'CML'],
            '淋巴瘤': ['Lymphoma', 'B-cell Lymphoma', 'T-cell Lymphoma'],
            '多发性骨髓瘤': ['Multiple Myeloma', 'MM'],
            '新冠': ['COVID-19', 'COVID19', 'SARS-CoV-2', 'Coronavirus'],
            '糖尿病': ['Diabetes', 'Type 1 Diabetes', 'Type 2 Diabetes', 'T1D', 'T2D'],
            '阿尔茨海默': ['Alzheimer', "Alzheimer's Disease", 'AD'],
            '帕金森': ['Parkinson', "Parkinson's Disease", 'PD'],
            '自闭症': ['Autism', 'ASD', 'Autism Spectrum Disorder'],
            '免疫': ['Immune', 'Immunology', 'Immunotherapy', 'Autoimmune'],
            '感染': ['Infection', 'Infectious'],
            '炎症': ['Inflammation', 'Inflammatory'],
            # 英文 -> 相关术语
            'covid': ['COVID-19', 'COVID19', 'SARS-CoV-2'],
            'covid-19': ['COVID-19', 'SARS-CoV-2', 'Coronavirus'],
            'lung cancer': ['Lung Cancer', 'Lung Adenocarcinoma', 'NSCLC', 'SCLC'],
            'breast cancer': ['Breast Cancer', 'Breast Carcinoma', 'BC'],
        }
        
        # 为每个疾病关键词扩展到多个字段，并翻译中文疾病名
        for keyword in disease_keywords:
            keyword_lower = keyword.lower()
            # 获取映射的疾病别名
            aliases = []
            is_chinese = False
            for cn, en_list in disease_mapping.items():
                if cn in keyword_lower:
                    # 检测到中文疾病名
                    is_chinese = True
                    aliases.extend(en_list)
                elif keyword_lower in cn.lower():
                    is_chinese = True
                    aliases.extend(en_list)
                for en in en_list:
                    if en.lower() in keyword_lower or keyword_lower in en.lower():
                        aliases.append(en)
                        aliases.extend([a for a in en_list if a != en])
            
            # 去重并限制数量
            aliases = list(dict.fromkeys(aliases))[:5]  # 最多5个别名
            
            # 如果是中文疾病名，更新disease_clean为英文
            if is_chinese and aliases:
                english_name = aliases[0]  # 使用第一个英文别名作为主名
                if 'disease_clean' in partial:
                    partial['disease_clean'] = english_name
                    self.logger.info(f"中文疾病名翻译: '{keyword}' → '{english_name}'")
            
            # 扩展到title和summary字段（如果尚未设置）
            if aliases:
                search_terms = ' '.join([keyword] + aliases)
                if 'title' not in partial or not partial['title']:
                    partial['title'] = search_terms
                    self.logger.info(f"疾病查询扩展到title字段: {search_terms}")
                if 'summary' not in partial or not partial['summary']:
                    partial['summary'] = search_terms
                    self.logger.info(f"疾病查询扩展到summary字段: {search_terms}")
        
        # ========== 组织概念扩展 ==========
        tissue_keywords = []
        if 'tissue_clean' in partial:
            tissue_keywords.append(partial['tissue_clean'])
        if 'tissue_location' in partial:
            tissue_keywords.append(partial['tissue_location'])
            
        tissue_mapping = {
            '肝': ['Liver', 'Hepatic'],
            '肺': ['Lung', 'Pulmonary'],
            '脑': ['Brain', 'Cerebral', 'Neural'],
            '心': ['Heart', 'Cardiac'],
            '肾': ['Kidney', 'Renal'],
            '脾': ['Spleen', 'Splenic'],
            '血液': ['Blood', 'PBMC', 'Peripheral Blood'],
            '骨髓': ['Bone Marrow', 'BM', 'Marrow'],
            '皮肤': ['Skin', 'Dermal', 'Cutaneous'],
            '肠': ['Intestine', 'Intestinal', 'Colon', 'Colorectal', 'Gut'],
            '胃': ['Stomach', 'Gastric'],
            '胰腺': ['Pancreas', 'Pancreatic'],
            '乳腺': ['Breast', 'Mammary'],
            '卵巢': ['Ovary', 'Ovarian'],
            '前列腺': ['Prostate', 'Prostatic'],
            '淋巴结': ['Lymph Node', 'Lymphoid', 'Lymph'],
            '胸腺': ['Thymus', 'Thymic'],
            '视网膜': ['Retina', 'Retinal'],
            '角膜': ['Cornea', 'Corneal'],
        }
        
        for keyword in tissue_keywords:
            keyword_lower = keyword.lower()
            aliases = []
            for cn, en_list in tissue_mapping.items():
                if cn in keyword_lower or keyword_lower in cn.lower():
                    aliases.extend(en_list)
            aliases = list(dict.fromkeys(aliases))[:3]
            
            if aliases and 'title' not in partial:
                partial['title'] = ' '.join([keyword] + aliases)
                self.logger.info(f"组织查询扩展到title字段: {partial['title']}")
        
        # ========== 平台概念扩展 ==========
        platform_keywords = []
        if 'platform_clean' in partial:
            platform_keywords.append(partial['platform_clean'])
        if 'sequencing_platform' in partial:
            platform_keywords.append(partial['sequencing_platform'])
            
        platform_mapping = {
            '10x': ['10x Genomics', '10X', 'Chromium', '10x'],
            'smart': ['Smart-seq2', 'Smart-seq', 'Smartseq2'],
            'drop': ['Drop-seq', 'Dropseq', 'inDrop', 'Drop'],
            'bd': ['BD Rhapsody', 'BD'],
            'seqwell': ['Seq-Well', 'SeqWell'],
        }
        
        for keyword in platform_keywords:
            keyword_lower = keyword.lower()
            for k, v in platform_mapping.items():
                if k in keyword_lower:
                    if 'title' not in partial:
                        partial['title'] = ' '.join([keyword] + v)
                        self.logger.info(f"平台查询扩展到title字段: {partial['title']}")
                    break
        
        # ========== 主题关键词扩展（关键：中文→英文映射）==========
        # 注意：数据库中所有文本都是英文，中文关键词必须翻译成英文才能搜到
        topic_keywords = {
            # 免疫相关
            '免疫': ['Immune', 'Immunity', 'Immunology', 'Immunotherapy', 'Autoimmune', 
                    'Lymphocyte', 'T cell', 'B cell', 'Macrophage', 'Cytokine'],
            't细胞': ['T cell', 'T-cell', 'T lymphocyte', 'CD4', 'CD8', 'Treg', 'Th17'],
            'b细胞': ['B cell', 'B-cell', 'B lymphocyte', 'plasma cell', 'antibody'],
            '巨噬细胞': ['macrophage', 'monocyte', 'myeloid', 'M1', 'M2'],
            '树突细胞': ['dendritic cell', 'DC', 'antigen presenting'],
            'nk细胞': ['NK cell', 'natural killer', 'innate lymphoid'],
            
            # 肿瘤相关
            '肿瘤微环境': ['tumor microenvironment', 'TME', 'microenvironment', 'stroma'],
            '微环境': ['microenvironment', 'niche', 'stroma'],
            '转移': ['metastasis', 'metastatic', 'invasion', 'migration', 'EMT'],
            '耐药': ['resistance', 'resistant', 'drug resistance', 'therapy resistance'],
            '复发': ['relapse', 'recurrence', 'recurrent'],
            
            # 细胞类型
            '干细胞': ['stem cell', 'progenitor', 'stemness', 'pluripotent'],
            '祖细胞': ['progenitor', 'precursor', 'stem cell'],
            '成纤维细胞': ['fibroblast', 'CAF', 'stromal'],
            '内皮细胞': ['endothelial', 'EC', 'vascular', 'angiogenesis'],
            
            # 生物学过程
            '发育': ['development', 'differentiation', 'embryonic', 'organogenesis'],
            '衰老': ['aging', 'senescence', 'aged', 'elderly'],
            '炎症': ['inflammation', 'inflammatory', 'cytokine storm'],
            '感染': ['infection', 'infectious', 'pathogen', 'viral', 'bacterial'],
            '疫苗': ['vaccine', 'vaccination', 'immunization'],
            '应激': ['stress', 'stress response', 'hypoxia'],
            '凋亡': ['apoptosis', 'apoptotic', 'cell death'],
            '增殖': ['proliferation', 'proliferating', 'cell cycle'],
            
            # 技术方法
            '单细胞': ['single cell', 'single-cell', 'scRNA-seq', 'scRNA'],
            '空间转录组': ['spatial', 'spatial transcriptomics', 'spatial omics'],
            'atac': ['ATAC-seq', 'ATAC', 'chromatin', 'accessibility'],
            'chip': ['ChIP-seq', 'ChIP', 'histone'],
            'crispr': ['CRISPR', 'Cas9', 'gene editing', 'screen'],
            
            # 分子类型
            '基因': ['gene', 'genetic', 'genomic', 'expression'],
            '蛋白质': ['protein', 'proteomic', 'proteome'],
            '代谢': ['metabolism', 'metabolic', 'metabolite'],
            '通路': ['pathway', 'signaling', 'pathways'],
            '受体': ['receptor', 'receptors', 'ligand'],
        }
        
        # 检查用户原始查询中的中文主题关键词，必须翻译成英文
        query_text = ' '.join(partial.values()) if partial else ''
        query_lower = query_text.lower()
        
        expanded_topics = []
        for topic, aliases in topic_keywords.items():
            if topic in query_lower:
                # 找到中文关键词，使用英文别名替换（不再保留中文）
                expanded_topics.extend(aliases)
                self.logger.info(f"中文主题词翻译: '{topic}' → {aliases[:3]}")
        
        # 将翻译后的英文主题词添加到title和summary搜索中
        if expanded_topics:
            # 去重并限制数量
            unique_topics = list(dict.fromkeys(expanded_topics))[:8]
            topic_terms = ' '.join(unique_topics)
            
            # 合并到现有条件而不是覆盖
            if 'title' in partial:
                partial['title'] = partial['title'] + ' ' + topic_terms
            else:
                partial['title'] = topic_terms
                
            if 'summary' in partial:
                partial['summary'] = partial['summary'] + ' ' + topic_terms
            else:
                partial['summary'] = topic_terms
                
            self.logger.info(f"主题关键词已翻译扩展: {topic_terms[:100]}...")
        
        # ========== COVID-19 特殊处理 ==========
        # 检测COVID-19相关查询并全面扩展
        covid_terms = ['covid', 'covid-19', 'covid19', 'sars-cov-2', 'coronavirus', '新冠']
        query_lower = ' '.join(partial.values()).lower()
        
        if any(term in query_lower for term in covid_terms):
            covid_search_terms = "COVID-19 COVID19 SARS-CoV-2 Coronavirus 新冠"
            
            # 确保disease_clean包含COVID-19
            if 'disease_clean' not in partial:
                partial['disease_clean'] = 'COVID-19'
                self.logger.info("自动添加COVID-19到disease_clean")
            
            # 扩展到title和summary
            if 'title' in partial:
                if not any(t in partial['title'].lower() for t in covid_terms):
                    partial['title'] = partial['title'] + ' ' + covid_search_terms
            else:
                partial['title'] = covid_search_terms
                
            if 'summary' in partial:
                if not any(t in partial['summary'].lower() for t in covid_terms):
                    partial['summary'] = partial['summary'] + ' ' + covid_search_terms
            else:
                partial['summary'] = covid_search_terms
                
            self.logger.info("COVID-19查询已全面扩展到多个字段")
        
        # 清理空值
        enhanced['partial_match'] = {k: v for k, v in partial.items() if v}
        
        self.logger.info(f"增强后的过滤条件: {json.dumps(enhanced['partial_match'], ensure_ascii=False)}")
        return enhanced