"""
自适应查询引擎 - 数据感知的智能检索
核心特性：
1. 渐进式查询 - 从宽松到严格
2. 零结果自动恢复
3. 查询条件动态优化
4. 基于实际数据的智能匹配
"""

import logging
import json
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import pandas as pd
from datetime import datetime

from .schema_knowledge_base import SchemaKnowledgeBase, FieldKnowledge
from .db_manager import DatabaseManager


class QueryStrategy(Enum):
    """查询策略"""
    EXACT = "exact"           # 精确匹配
    STANDARD = "standard"     # 标准策略（推荐）
    FUZZY = "fuzzy"          # 模糊策略（宽松）
    SEMANTIC = "semantic"     # 语义策略（最宽松）


@dataclass
class QueryAttempt:
    """查询尝试记录"""
    attempt_id: int
    strategy: QueryStrategy
    filters: Dict[str, Any]
    result_count: int
    execution_time: float
    timestamp: datetime


class AdaptiveQueryEngine:
    """
    自适应查询引擎
    
    工作流程：
    1. 接收用户查询，AI解析初始条件
    2. 使用Schema知识库分析条件可行性
    3. 预估算结果数，检测潜在冲突
    4. 如存在风险，自动调整查询策略
    5. 执行查询，如零结果则自动恢复
    6. 返回结果并解释查询策略
    """
    
    def __init__(self, db_manager: DatabaseManager, knowledge_base: SchemaKnowledgeBase):
        self.db_manager = db_manager
        self.kb = knowledge_base
        self.logger = logging.getLogger(__name__)
        
        # 查询历史
        self._query_history: List[QueryAttempt] = []
        
        # 策略参数
        self._strategy_params = {
            QueryStrategy.EXACT: {
                'match_threshold': 1.0,
                'max_conditions_per_concept': 1,
                'allow_or_expansion': False
            },
            QueryStrategy.STANDARD: {
                'match_threshold': 0.8,
                'max_conditions_per_concept': 2,
                'allow_or_expansion': True
            },
            QueryStrategy.FUZZY: {
                'match_threshold': 0.5,
                'max_conditions_per_concept': 3,
                'allow_or_expansion': True
            },
            QueryStrategy.SEMANTIC: {
                'match_threshold': 0.3,
                'max_conditions_per_concept': 5,
                'allow_or_expansion': True
            }
        }
    
    def execute_adaptive_query(self, 
                              natural_query: str,
                              ai_parsed_filters: Dict[str, Any],
                              session_context: Optional[Dict] = None,
                              max_attempts: int = 3) -> Dict[str, Any]:
        """
        执行自适应查询
        
        Args:
            natural_query: 原始自然语言查询
            ai_parsed_filters: AI解析的初始过滤条件
            session_context: 会话上下文
            max_attempts: 最大尝试次数
        
        Returns:
            查询结果和策略信息
        """
        start_time = datetime.now()
        self.logger.info(f"开始自适应查询: {natural_query}")
        
        # 步骤1：分析初始条件
        analysis = self._analyze_filters(ai_parsed_filters)
        self.logger.info(f"条件分析: {json.dumps(analysis, ensure_ascii=False)}")
        
        # 步骤2：根据分析选择初始策略
        initial_strategy = self._select_initial_strategy(analysis)
        
        # 步骤3：应用策略优化条件
        optimized_filters = self._apply_strategy(
            ai_parsed_filters, 
            initial_strategy,
            analysis
        )
        
        # 步骤4：渐进式查询尝试
        last_result = None
        successful_attempt = None
        
        for attempt in range(max_attempts):
            attempt_start = datetime.now()
            
            # 如果这不是第一次尝试，放宽策略
            if attempt > 0:
                strategy = self._relax_strategy(initial_strategy, attempt)
                optimized_filters = self._apply_strategy(
                    ai_parsed_filters,
                    strategy,
                    analysis
                )
                self.logger.info(f"尝试 {attempt + 1}: 使用更宽松策略 {strategy.value}")
            else:
                strategy = initial_strategy
            
            # 执行查询
            try:
                results = self.db_manager.search(optimized_filters, limit=100)
                count = self.db_manager.count_results(optimized_filters)
                
                execution_time = (datetime.now() - attempt_start).total_seconds()
                
                attempt_record = QueryAttempt(
                    attempt_id=attempt,
                    strategy=strategy,
                    filters=optimized_filters,
                    result_count=count,
                    execution_time=execution_time,
                    timestamp=datetime.now()
                )
                self._query_history.append(attempt_record)
                
                self.logger.info(f"尝试 {attempt + 1} 结果: {count} 条记录")
                
                if count > 0:
                    # 成功！
                    successful_attempt = attempt_record
                    last_result = {
                        'results': results,
                        'total_count': count,
                        'filters': optimized_filters,
                        'strategy': strategy.value,
                        'attempts': attempt + 1,
                        'query_analysis': analysis
                    }
                    break
                else:
                    # 零结果，记录但继续尝试
                    last_result = {
                        'results': pd.DataFrame(),
                        'total_count': 0,
                        'filters': optimized_filters,
                        'strategy': strategy.value,
                        'attempts': attempt + 1,
                        'query_analysis': analysis
                    }
                    
            except Exception as e:
                self.logger.error(f"查询执行失败: {e}")
                if attempt == max_attempts - 1:
                    raise
        
        # 步骤5：生成结果解释
        total_time = (datetime.now() - start_time).total_seconds()
        
        if last_result:
            last_result['execution_time'] = total_time
            last_result['explanation'] = self._generate_explanation(
                natural_query, 
                last_result,
                successful_attempt
            )
            
            # 如果使用了宽松策略，给出建议
            if successful_attempt and successful_attempt.strategy != initial_strategy:
                last_result['suggestions'] = self._generate_refinement_suggestions(
                    ai_parsed_filters,
                    successful_attempt.filters
                )
        
        return last_result or {
            'results': pd.DataFrame(),
            'total_count': 0,
            'error': '所有查询策略均返回零结果',
            'execution_time': total_time
        }
    
    def _analyze_filters(self, filters: Dict[str, Any]) -> Dict[str, Any]:
        """
        分析过滤条件，评估可行性
        """
        analysis = {
            'estimated_count': 0,
            'risk_level': 'low',  # low, medium, high, critical
            'conflicts': [],
            'field_coverage': {},
            'suggestions': []
        }
        
        # 使用知识库评估
        estimated = self.kb.estimate_result_count(filters)
        analysis['estimated_count'] = estimated
        
        # 检测冲突
        conflicts = self.kb.detect_conflicting_conditions(filters)
        analysis['conflicts'] = conflicts
        
        # 评估风险等级
        if estimated == 0:
            analysis['risk_level'] = 'critical'
        elif estimated < 10:
            analysis['risk_level'] = 'high'
        elif estimated < 100:
            analysis['risk_level'] = 'medium'
        
        # 如果有严重冲突，提升风险等级
        critical_conflicts = [c for c in conflicts if c.get('severity') == 'critical']
        if critical_conflicts:
            analysis['risk_level'] = 'critical'
        
        # 分析每个概念/字段的覆盖
        for match_type, conditions in filters.items():
            for field, value in conditions.items():
                field_stats = self.kb.get_field_statistics(field)
                if field_stats:
                    exact_match = field_stats.value_distribution.get(str(value), 0)
                    similar = self.kb.find_similar_values(field, str(value), top_k=1)
                    
                    analysis['field_coverage'][field] = {
                        'exact_matches': exact_match,
                        'similar_values': len(similar),
                        'null_percentage': field_stats.null_percentage,
                        'data_quality': 'good' if field_stats.null_percentage < 30 else 'poor'
                    }
        
        return analysis
    
    def _select_initial_strategy(self, analysis: Dict[str, Any]) -> QueryStrategy:
        """根据分析结果选择初始策略"""
        risk_level = analysis['risk_level']
        estimated = analysis['estimated_count']
        
        if risk_level == 'critical':
            # 直接跳到模糊策略
            return QueryStrategy.FUZZY
        elif risk_level == 'high':
            return QueryStrategy.FUZZY
        elif risk_level == 'medium':
            return QueryStrategy.STANDARD
        else:
            return QueryStrategy.EXACT if estimated > 1000 else QueryStrategy.STANDARD
    
    def _apply_strategy(self, 
                       original_filters: Dict[str, Any],
                       strategy: QueryStrategy,
                       analysis: Dict[str, Any]) -> Dict[str, Any]:
        """
        应用策略优化过滤条件
        """
        params = self._strategy_params[strategy]
        optimized = {
            'exact_match': {},
            'partial_match': {},
            'boolean_match': original_filters.get('boolean_match', {}),
            'range_match': original_filters.get('range_match', {})
        }
        
        # 处理每个匹配类型
        for match_type in ['exact_match', 'partial_match']:
            conditions = original_filters.get(match_type, {})
            if not conditions:
                continue
            
            # 按语义类型分组
            semantic_groups = {}
            for field, value in conditions.items():
                field_stats = self.kb.get_field_statistics(field)
                sem_type = field_stats.semantic_type if field_stats else 'generic'
                
                if sem_type not in semantic_groups:
                    semantic_groups[sem_type] = []
                semantic_groups[sem_type].append((field, value))
            
            # 为每个语义类型选择最优字段
            for sem_type, field_values in semantic_groups.items():
                # 按字段质量排序
                sorted_fields = sorted(
                    field_values,
                    key=lambda fv: self._score_field_quality(fv[0]),
                    reverse=True
                )
                
                # 根据策略限制字段数量
                selected = sorted_fields[:params['max_conditions_per_concept']]
                
                for field, value in selected:
                    if strategy == QueryStrategy.EXACT:
                        # 尝试找到精确匹配的值
                        similar = self.kb.find_similar_values(
                            field, str(value), top_k=1, threshold=params['match_threshold']
                        )
                        if similar:
                            optimized['exact_match'][field] = similar[0][0]
                        else:
                            optimized['partial_match'][field] = value
                    elif strategy == QueryStrategy.FUZZY or strategy == QueryStrategy.SEMANTIC:
                        # 使用模糊匹配，并扩展相似值
                        similar = self.kb.find_similar_values(
                            field, str(value), top_k=3, threshold=params['match_threshold']
                        )
                        if similar:
                            # 使用OR匹配多个相似值
                            if len(similar) > 1 and params['allow_or_expansion']:
                                # 构建OR条件
                                or_values = ' OR '.join([f'"{field}" LIKE "%{v}%"' for v, _ in similar])
                                # 这里简化处理，实际应该修改查询构建逻辑
                                optimized['partial_match'][field] = similar[0][0]
                            else:
                                optimized['partial_match'][field] = similar[0][0]
                        else:
                            optimized['partial_match'][field] = value
                    else:
                        # 标准策略
                        optimized['partial_match'][field] = value
        
        return optimized
    
    def _score_field_quality(self, field_name: str) -> float:
        """评分字段质量"""
        stats = self.kb.get_field_statistics(field_name)
        if not stats:
            return 0.0
        
        score = 100.0
        
        # 空值率越低越好
        score -= stats.null_percentage
        
        # 标准化字段加分
        if 'clean' in field_name or 'standardized' in field_name:
            score += 20
        
        # 数据量大的加分
        if stats.total_records > 100000:
            score += 10
        
        return score
    
    def _relax_strategy(self, current: QueryStrategy, attempt: int) -> QueryStrategy:
        """放宽策略"""
        progression = [
            QueryStrategy.EXACT,
            QueryStrategy.STANDARD,
            QueryStrategy.FUZZY,
            QueryStrategy.SEMANTIC
        ]
        
        try:
            current_idx = progression.index(current)
            new_idx = min(current_idx + 1, len(progression) - 1)
            return progression[new_idx]
        except ValueError:
            return QueryStrategy.FUZZY
    
    def _generate_explanation(self, 
                             natural_query: str,
                             result: Dict[str, Any],
                             successful_attempt: Optional[QueryAttempt]) -> str:
        """生成结果解释"""
        parts = []
        
        total = result['total_count']
        parts.append(f"查询 '{natural_query}' 找到 {total:,} 条记录。")
        
        if successful_attempt:
            if successful_attempt.attempt_id > 0:
                parts.append(
                    f"系统尝试了 {successful_attempt.attempt_id + 1} 次查询策略，"
                    f"最终使用 '{successful_attempt.strategy.value}' 策略获得成功。"
                )
            
            # 说明使用了哪些字段
            filters = successful_attempt.filters
            fields_used = []
            for match_type, conditions in filters.items():
                if conditions:
                    fields_used.extend(conditions.keys())
            
            if fields_used:
                parts.append(f"检索字段: {', '.join(fields_used[:5])}")
        
        return ' '.join(parts)
    
    def _generate_refinement_suggestions(self,
                                        original: Dict[str, Any],
                                        optimized: Dict[str, Any]) -> List[str]:
        """生成精化建议"""
        suggestions = []
        
        # 对比原始和优化后的条件
        original_fields = set()
        optimized_fields = set()
        
        for match_type in ['exact_match', 'partial_match']:
            original_fields.update(original.get(match_type, {}).keys())
            optimized_fields.update(optimized.get(match_type, {}).keys())
        
        removed = original_fields - optimized_fields
        if removed:
            suggestions.append(
                f"为提高匹配率，系统移除了过度限制的条件: {', '.join(removed)}"
            )
        
        # 检查是否有值被替换
        for match_type in ['exact_match', 'partial_match']:
            orig = original.get(match_type, {})
            opt = optimized.get(match_type, {})
            
            for field in set(orig.keys()) & set(opt.keys()):
                if orig[field] != opt[field]:
                    suggestions.append(
                        f"字段 '{field}' 的值从 '{orig[field]}' 调整为 '{opt[field]}'"
                    )
        
        return suggestions
    
    def suggest_alternative_queries(self, 
                                   natural_query: str,
                                   failed_filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        当所有策略都失败时，建议替代查询
        """
        alternatives = []
        
        # 分析查询中的概念
        concepts = self._extract_concepts_from_filters(failed_filters)
        
        for concept_type, value in concepts.items():
            # 找到相似的数据库值
            fields = self.kb.get_semantic_fields(concept_type)
            
            for field in fields[:2]:  # 检查前2个字段
                similar = self.kb.find_similar_values(field, value, top_k=5)
                
                for similar_value, score in similar:
                    if score > 0.5 and similar_value.lower() != value.lower():
                        # 构建替代查询
                        alt_query = natural_query.replace(value, similar_value)
                        alternatives.append({
                            'query': alt_query,
                            'reason': f"使用数据库中的标准值 '{similar_value}' 替代 '{value}'",
                            'confidence': score,
                            'suggested_field': field
                        })
        
        # 去重并排序
        seen = set()
        unique_alternatives = []
        for alt in sorted(alternatives, key=lambda x: x['confidence'], reverse=True):
            if alt['query'] not in seen:
                seen.add(alt['query'])
                unique_alternatives.append(alt)
        
        return unique_alternatives[:5]
    
    def _extract_concepts_from_filters(self, filters: Dict[str, Any]) -> Dict[str, str]:
        """从过滤条件中提取概念"""
        concepts = {}
        
        for match_type, conditions in filters.items():
            for field, value in conditions.items():
                stats = self.kb.get_field_statistics(field)
                if stats and stats.semantic_type != 'generic':
                    concepts[stats.semantic_type] = str(value)
        
        return concepts


class SmartQueryBuilder:
    """
    智能查询构建器
    基于Schema知识构建最优SQL
    """
    
    def __init__(self, knowledge_base: SchemaKnowledgeBase):
        self.kb = knowledge_base
        self.logger = logging.getLogger(__name__)
    
    def build_smart_query(self, 
                         concepts: Dict[str, str],
                         strategy: QueryStrategy = QueryStrategy.STANDARD) -> Dict[str, Any]:
        """
        根据概念构建智能查询
        
        Args:
            concepts: {'disease': 'lung cancer', 'tissue': 'brain', ...}
            strategy: 查询策略
        
        Returns:
            优化后的过滤条件
        """
        # 获取查询策略建议
        strategy_suggestion = self.kb.suggest_query_strategy(concepts)
        
        filters = {
            'exact_match': {},
            'partial_match': {},
            'boolean_match': {},
            'range_match': {}
        }
        
        # 为每个概念构建条件
        for concept, field in strategy_suggestion['primary_fields'].items():
            value_info = strategy_suggestion['suggested_values'].get(field, [])
            
            if not value_info:
                continue
            
            # 选择最佳值
            best_match = max(value_info, key=lambda x: x['score'])
            
            if best_match['score'] >= 0.9 and strategy == QueryStrategy.EXACT:
                filters['exact_match'][field] = best_match['value']
            elif best_match['score'] >= 0.5:
                filters['partial_match'][field] = best_match['value']
            else:
                # 低置信度，使用原始值
                filters['partial_match'][field] = concepts[concept]
        
        return {
            'filters': filters,
            'strategy_confidence': strategy_suggestion['confidence'],
            'suggested_values': strategy_suggestion['suggested_values']
        }
