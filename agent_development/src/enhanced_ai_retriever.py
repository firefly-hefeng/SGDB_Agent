"""
增强版AI检索器 - 数据感知的智能解析
特点：
1. 将数据库实际内容注入Prompt
2. 支持基于值的智能匹配
3. 提供查询可行性反馈
"""

import json
import logging
from typing import Dict, List, Any, Optional
import pandas as pd

from .ai_retriever import AIRetriever
from .schema_knowledge_base import SchemaKnowledgeBase


class EnhancedAIRetriever(AIRetriever):
    """
    增强版AI检索器
    
    在原有功能基础上，增加：
    - 数据感知：了解数据库中实际存储的值
    - 智能验证：验证查询条件的可行性
    - 自适应建议：根据数据分布给出建议
    """
    
    def __init__(self, config: Dict[str, Any], knowledge_base: Optional[SchemaKnowledgeBase] = None):
        super().__init__(config)
        self.kb = knowledge_base
        self.logger = logging.getLogger(__name__)
        
        # 统计信息缓存
        self._schema_stats_cache = None
    
    def parse_natural_query_with_knowledge(self,
                                          query: str,
                                          knowledge_base: SchemaKnowledgeBase,
                                          available_values: Dict[str, List[str]] = None) -> Dict[str, Any]:
        """
        使用Schema知识解析自然语言查询
        """
        self.kb = knowledge_base
        
        # 构建数据感知的Schema描述
        schema_desc = self._build_knowledge_aware_schema()
        
        # 提取查询中的概念
        concepts = self._extract_query_concepts(query)
        
        # 预先查找数据库中的匹配值
        value_suggestions = self._find_value_suggestions(concepts)
        
        # 构建增强的Prompt
        system_prompt = self._build_enhanced_prompt(
            schema_desc, 
            value_suggestions,
            query
        )
        
        try:
            response = self.call_llm(
                f"{system_prompt}\n\n用户查询: {query}",
                temperature=0.1,
                query=query
            )
            
            # 解析响应
            parsed = self._parse_json_response(response)
            
            # 使用知识库验证和优化
            validated = self._validate_with_knowledge(parsed, concepts)
            
            self.logger.info(f"增强查询解析完成: {json.dumps(validated, ensure_ascii=False)[:200]}")
            
            return validated
            
        except Exception as e:
            self.logger.error(f"增强解析失败: {e}")
            # 回退到基础解析
            return self.parse_natural_query(query, available_values)
    
    def _build_knowledge_aware_schema(self) -> str:
        """构建数据感知的Schema描述"""
        if not self.kb:
            return super()._build_schema_description()
        
        lines = ["# 数据库Schema（基于实际数据分布）\n"]
        lines.append("## 重要提示")
        lines.append("以下字段值是数据库中实际存在的，请优先使用这些值：\n")
        
        # 按语义类型组织
        semantic_types = {
            'disease': '🏥 疾病相关字段',
            'tissue': '🧬 组织相关字段',
            'platform': '🔬 测序平台字段',
            'database': '💾 数据库来源',
            'text': '📝 文本字段（标题/摘要）'
        }
        
        for sem_type, title in semantic_types.items():
            fields = self.kb.get_semantic_fields(sem_type)
            if not fields:
                continue
            
            lines.append(f"\n## {title}")
            
            for field in fields[:3]:  # 只显示前3个字段
                stats = self.kb.get_field_statistics(field)
                if not stats:
                    continue
                
                lines.append(f"\n### {field}")
                lines.append(f"- 有效记录: {stats.total_records - stats.null_count:,} / {stats.total_records:,}")
                
                if stats.top_values:
                    # 显示常见值及其数量
                    examples = []
                    for v in stats.top_values[:8]:
                        examples.append(f"'{v.value}'({v.count:,})")
                    lines.append(f"- 常见值: {', '.join(examples)}")
                    
                    # 如果有空值比例高，给出警告
                    if stats.null_percentage > 50:
                        lines.append(f"- ⚠️ 注意: {stats.null_percentage:.1f}%记录此字段为空")
        
        lines.append("\n\n## 查询规则")
        lines.append("1. 优先使用'_clean'或'_standardized'后缀的标准化字段")
        lines.append("2. 每个概念（如疾病、组织）只选择一个最合适的字段")
        lines.append("3. 如果查询词与常见值不完全匹配，使用LIKE模糊匹配")
        lines.append("4. 避免在同一语义类型的多个字段上同时设置条件")
        lines.append("5. 文本搜索（title/summary）可以与其他字段条件组合")
        
        return '\n'.join(lines)
    
    def _extract_query_concepts(self, query: str) -> Dict[str, str]:
        """从查询中提取概念"""
        concepts = {}
        query_lower = query.lower()
        
        # 疾病概念检测
        disease_keywords = {
            '肺癌': 'lung cancer', '乳腺癌': 'breast cancer', '肝癌': 'liver cancer',
            '脑瘤': 'brain tumor', '胶质瘤': 'glioma', '新冠': 'covid-19',
            'covid': 'covid-19', 'covid-19': 'covid-19', 'covid19': 'covid-19'
        }
        
        for keyword, concept in disease_keywords.items():
            if keyword in query_lower:
                concepts['disease'] = concept
                break
        
        # 组织概念检测
        tissue_keywords = {
            '脑': 'brain', '脑组织': 'brain', '大脑': 'brain',
            '肝': 'liver', '肺': 'lung', '心': 'heart',
            '肾': 'kidney', '血液': 'blood', '骨髓': 'bone marrow'
        }
        
        for keyword, concept in tissue_keywords.items():
            if keyword in query_lower:
                concepts['tissue'] = concept
                break
        
        # 平台概念检测
        platform_keywords = {
            '10x': '10x', 'smart-seq': 'smart-seq', 'smartseq': 'smart-seq'
        }
        
        for keyword, concept in platform_keywords.items():
            if keyword in query_lower:
                concepts['platform'] = concept
                break
        
        return concepts
    
    def _find_value_suggestions(self, concepts: Dict[str, str]) -> Dict[str, List[Dict]]:
        """为概念查找数据库中的匹配值建议"""
        suggestions = {}
        
        if not self.kb:
            return suggestions
        
        for concept_type, value in concepts.items():
            fields = self.kb.get_semantic_fields(concept_type)
            
            for field in fields[:2]:
                similar = self.kb.find_similar_values(field, value, top_k=5)
                if similar:
                    suggestions[field] = [
                        {'value': v, 'score': s} for v, s in similar
                    ]
        
        return suggestions
    
    def _build_enhanced_prompt(self, 
                              schema_desc: str,
                              value_suggestions: Dict[str, List[Dict]],
                              original_query: str) -> str:
        """构建增强的Prompt"""
        
        prompt_parts = [
            "你是单细胞RNA-seq数据库查询专家。请将用户的自然语言查询转换为精确的数据库检索条件。",
            "\n",
            schema_desc
        ]
        
        # 添加值建议
        if value_suggestions:
            prompt_parts.append("\n\n## 数据库值匹配建议")
            prompt_parts.append(f"根据查询'{original_query}'，数据库中可能匹配的值：")
            
            for field, values in value_suggestions.items():
                if values:
                    prompt_parts.append(f"\n字段 '{field}':")
                    for v in values[:3]:
                        prompt_parts.append(f"  - '{v['value']}' (相似度: {v['score']:.2f})")
        
        # 添加详细的查询规则
        prompt_parts.append("""

## 查询构建规则（重要！）

### 1. 字段选择规则
- 疾病概念 → 优先使用 disease_clean，不要在 disease_clean 和 disease_general 上同时设置条件
- 组织概念 → 优先使用 tissue_clean，不要在 tissue_clean 和 tissue_location 上同时设置条件  
- 平台概念 → 优先使用 platform_clean
- 主题关键词 → 使用 title 或 summary

### 2. 匹配策略
- 如果数据库建议的值与查询词非常相似（相似度>0.8），使用 exact_match
- 如果相似度中等（0.5-0.8），使用 partial_match
- 如果不确定，使用 partial_match

### 3. 避免过度约束
- 不要在同一概念类型的多个字段上设置AND条件
- 例如：不要同时约束 tissue_clean='Brain' AND tissue_location='Brain'
- 选择数据质量最好的一个字段即可

### 4. 返回格式
```json
{
    "filters": {
        "exact_match": {},
        "partial_match": {},
        "boolean_match": {},
        "range_match": {}
    },
    "intent": "查询意图描述",
    "keywords": ["关键词1", "关键词2"],
    "confidence": 0.95,
    "reasoning": "解释为什么选择这些条件"
}
```

只返回JSON，不要其他内容。""")
        
        return '\n'.join(prompt_parts)
    
    def _validate_with_knowledge(self, 
                                parsed: Dict[str, Any],
                                original_concepts: Dict[str, str]) -> Dict[str, Any]:
        """使用知识库验证和优化解析结果"""
        if not self.kb:
            return parsed
        
        filters = parsed.get('filters', {})
        
        # 检测潜在冲突
        conflicts = self.kb.detect_conflicting_conditions(filters)
        
        if conflicts:
            self.logger.warning(f"检测到查询冲突: {conflicts}")
            
            # 自动修复冲突
            for conflict in conflicts:
                if conflict['severity'] == 'critical':
                    # 严重冲突，移除多余字段
                    fields_to_remove = conflict['fields'][1:]  # 保留第一个
                    for field in fields_to_remove:
                        for match_type in ['exact_match', 'partial_match']:
                            if field in filters.get(match_type, {}):
                                del filters[match_type][field]
                                self.logger.info(f"自动移除冲突字段: {field}")
        
        # 估算结果数
        estimated = self.kb.estimate_result_count(filters)
        parsed['estimated_results'] = estimated
        
        if estimated == 0:
            parsed['warning'] = '当前条件可能返回零结果，建议放宽条件'
        elif estimated < 10:
            parsed['warning'] = f'预计只返回 {estimated} 条记录，建议放宽条件'
        
        parsed['filters'] = filters
        return parsed
    
    def suggest_query_refinement(self, 
                                 original_query: str,
                                 zero_result_filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        当查询返回零结果时，建议精化方案
        """
        if not self.kb:
            return []
        
        suggestions = []
        
        # 分析哪些条件导致了零结果
        for match_type, conditions in zero_result_filters.items():
            for field, value in conditions.items():
                field_stats = self.kb.get_field_statistics(field)
                if not field_stats:
                    continue
                
                # 查找相似值
                similar = self.kb.find_similar_values(field, str(value), top_k=5)
                
                if similar:
                    suggestions.append({
                        'type': 'value_replacement',
                        'field': field,
                        'original_value': value,
                        'suggested_values': [
                            {'value': v, 'score': s} for v, s in similar[:3]
                        ],
                        'reason': f"字段 '{field}' 中没有精确匹配 '{value}' 的记录"
                    })
                else:
                    # 没有相似值，建议移除该条件
                    suggestions.append({
                        'type': 'remove_condition',
                        'field': field,
                        'original_value': value,
                        'reason': f"字段 '{field}' 中没有匹配 '{value}' 的记录，建议移除此条件"
                    })
        
        return suggestions
    
    def explain_query_strategy(self, 
                              natural_query: str,
                              filters: Dict[str, Any],
                              result_count: int) -> str:
        """
        生成查询策略的详细解释
        """
        if not self.kb:
            return super().explain_results(natural_query, pd.DataFrame(), result_count)
        
        parts = [f"查询 '{natural_query}' 的检索策略：\n"]
        
        # 解释每个条件
        parts.append("应用的检索条件：")
        for match_type, conditions in filters.items():
            if not conditions:
                continue
            
            type_name = {
                'exact_match': '精确匹配',
                'partial_match': '模糊匹配',
                'boolean_match': '布尔匹配',
                'range_match': '范围匹配'
            }.get(match_type, match_type)
            
            for field, value in conditions.items():
                field_stats = self.kb.get_field_statistics(field)
                
                if field_stats:
                    exact_count = field_stats.value_distribution.get(str(value), 0)
                    if exact_count > 0:
                        parts.append(f"  • {type_name} {field}='{value}' (数据库中 {exact_count:,} 条匹配)")
                    else:
                        parts.append(f"  • {type_name} {field} LIKE '%{value}%'")
                else:
                    parts.append(f"  • {type_name} {field}='{value}'")
        
        parts.append(f"\n查询结果：找到 {result_count:,} 条记录。")
        
        if result_count == 0:
            parts.append("\n⚠️ 未找到匹配记录。建议：")
            refinements = self.suggest_query_refinement(natural_query, filters)
            for i, ref in enumerate(refinements[:3], 1):
                if ref['type'] == 'value_replacement':
                    values = ', '.join([v['value'] for v in ref['suggested_values']])
                    parts.append(f"  {i}. 尝试使用相关值: {values}")
                else:
                    parts.append(f"  {i}. {ref['reason']}")
        
        return '\n'.join(parts)
