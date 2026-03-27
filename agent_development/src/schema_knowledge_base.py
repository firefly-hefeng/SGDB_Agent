"""
Schema知识库 - 数据感知的智能检索基础
存储和管理数据库的实际数据分布、字段关系、同义词等
"""

import sqlite3
import json
import logging
import numpy as np
from typing import Dict, List, Any, Optional, Tuple, Set
from dataclasses import dataclass, field
from pathlib import Path
from collections import defaultdict
import re
from datetime import datetime


@dataclass
class FieldValueStats:
    """字段值统计信息"""
    value: str
    count: int
    percentage: float
    similar_values: List[str] = field(default_factory=list)


@dataclass
class FieldKnowledge:
    """字段知识"""
    field_name: str
    total_records: int
    unique_count: int
    null_count: int
    null_percentage: float
    top_values: List[FieldValueStats] = field(default_factory=list)
    value_distribution: Dict[str, int] = field(default_factory=dict)
    
    # 语义信息
    semantic_type: str = ""  # 'disease', 'tissue', 'platform', 'text', etc.
    common_synonyms: Dict[str, List[str]] = field(default_factory=dict)
    
    # 查询建议
    suggested_operators: List[str] = field(default_factory=lambda: ['=', 'LIKE'])
    confidence_threshold: float = 0.8


class SchemaKnowledgeBase:
    """
    Schema知识库 - 深度理解数据库内容
    
    核心功能：
    1. 字段值分布感知 - 知道每个字段实际有哪些值
    2. 模糊匹配 - 基于编辑距离、语义相似的值匹配
    3. 查询建议 - 根据数据分布推荐最优查询策略
    4. 冲突检测 - 识别可能导致零结果的查询条件
    """
    
    def __init__(self, db_path: str, cache_dir: str = "data/schema_kb"):
        self.db_path = db_path
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        self.logger = logging.getLogger(__name__)
        
        # 知识缓存
        self._field_knowledge: Dict[str, FieldKnowledge] = {}
        self._value_index: Dict[str, Dict[str, Set[str]]] = defaultdict(dict)
        self._synonym_graph: Dict[str, Set[str]] = defaultdict(set)
        
        # 语义分类
        self._semantic_fields = {
            'disease': ['disease_clean', 'disease_standardized', 'disease', 'disease_general'],
            'tissue': ['tissue_clean', 'tissue_standardized', 'tissue_location'],
            'platform': ['platform_clean', 'platform_standardized', 'sequencing_platform'],
            'database': ['database_standardized', 'source_database'],
            'text': ['title', 'summary'],
            'boolean': ['matrix_open', 'raw_open', 'matrix_exist', 'raw_exist'],
            'date': ['publication_date', 'submission_date'],
            'numeric': ['citation_count', 'age_numeric']
        }
        
        # 初始化
        self._load_or_build_knowledge()
    
    def _load_or_build_knowledge(self):
        """加载或构建知识库"""
        cache_file = self.cache_dir / "field_knowledge.json"
        
        if cache_file.exists():
            try:
                self._load_from_cache(cache_file)
                self.logger.info(f"知识库加载完成，包含 {len(self._field_knowledge)} 个字段")
                return
            except Exception as e:
                self.logger.warning(f"缓存加载失败，重新构建: {e}")
        
        self._build_knowledge()
        self._save_to_cache(cache_file)
    
    def _load_from_cache(self, cache_file: Path):
        """从缓存加载"""
        with open(cache_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        for field_name, field_data in data.items():
            self._field_knowledge[field_name] = FieldKnowledge(
                field_name=field_name,
                **field_data
            )
    
    def _save_to_cache(self, cache_file: Path):
        """保存到缓存"""
        data = {}
        for field_name, knowledge in self._field_knowledge.items():
            data[field_name] = {
                'field_name': knowledge.field_name,
                'total_records': knowledge.total_records,
                'unique_count': knowledge.unique_count,
                'null_count': knowledge.null_count,
                'null_percentage': knowledge.null_percentage,
                'top_values': [
                    {
                        'value': v.value,
                        'count': v.count,
                        'percentage': v.percentage
                    }
                    for v in knowledge.top_values[:50]  # 只存前50
                ],
                'semantic_type': knowledge.semantic_type,
                'suggested_operators': knowledge.suggested_operators,
                'confidence_threshold': knowledge.confidence_threshold
            }
        
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    
    def _build_knowledge(self):
        """构建知识库"""
        self.logger.info("开始构建Schema知识库...")
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 获取所有字段
        cursor.execute("PRAGMA table_info(std)")
        columns = [row[1] for row in cursor.fetchall()]
        
        for field_name in columns:
            try:
                knowledge = self._analyze_field(conn, field_name)
                self._field_knowledge[field_name] = knowledge
                
                # 构建值索引
                self._index_field_values(field_name, knowledge)
                
            except Exception as e:
                self.logger.warning(f"分析字段 {field_name} 失败: {e}")
        
        # 构建同义词图
        self._build_synonym_graph()
        
        conn.close()
        self.logger.info(f"知识库构建完成，分析了 {len(self._field_knowledge)} 个字段")
    
    def _analyze_field(self, conn: sqlite3.Connection, field_name: str) -> FieldKnowledge:
        """分析单个字段"""
        cursor = conn.cursor()
        
        # 基本统计
        cursor.execute(f"""
            SELECT 
                COUNT(*) as total,
                COUNT(DISTINCT "{field_name}") as unique_count,
                COUNT(*) - COUNT("{field_name}") as null_count
            FROM std
        """)
        total, unique, null_count = cursor.fetchone()
        
        null_percentage = (null_count / total * 100) if total > 0 else 0
        
        # 获取Top值
        cursor.execute(f"""
            SELECT "{field_name}", COUNT(*) as cnt
            FROM std
            WHERE "{field_name}" IS NOT NULL AND "{field_name}" != ''
            GROUP BY "{field_name}"
            ORDER BY cnt DESC
            LIMIT 100
        """)
        
        top_values = []
        value_distribution = {}
        for row in cursor.fetchall():
            value, count = row
            if value is not None:
                percentage = (count / total * 100) if total > 0 else 0
                top_values.append(FieldValueStats(
                    value=str(value),
                    count=count,
                    percentage=percentage
                ))
                value_distribution[str(value)] = count
        
        # 确定语义类型
        semantic_type = self._detect_semantic_type(field_name)
        
        # 建议操作符
        suggested_operators = self._suggest_operators(field_name, semantic_type, unique, total)
        
        return FieldKnowledge(
            field_name=field_name,
            total_records=total,
            unique_count=unique,
            null_count=null_count,
            null_percentage=null_percentage,
            top_values=top_values,
            value_distribution=value_distribution,
            semantic_type=semantic_type,
            suggested_operators=suggested_operators
        )
    
    def _detect_semantic_type(self, field_name: str) -> str:
        """检测字段语义类型"""
        field_lower = field_name.lower()
        
        for sem_type, fields in self._semantic_fields.items():
            if any(f.lower() in field_lower for f in fields):
                return sem_type
        
        return 'generic'
    
    def _suggest_operators(self, field_name: str, semantic_type: str, 
                          unique_count: int, total_count: int) -> List[str]:
        """建议查询操作符"""
        cardinality_ratio = unique_count / total_count if total_count > 0 else 1
        
        operators = []
        
        if semantic_type == 'boolean':
            operators = ['=', 'IS']
        elif semantic_type == 'numeric':
            operators = ['=', '>', '<', 'BETWEEN']
        elif semantic_type == 'date':
            operators = ['=', '>', '<', 'BETWEEN']
        elif cardinality_ratio < 0.01:  # 低基数，适合精确匹配
            operators = ['=', 'IN', 'LIKE']
        elif cardinality_ratio < 0.1:  # 中基数
            operators = ['LIKE', '=', 'IN']
        else:  # 高基数（如title）
            operators = ['LIKE', 'MATCH']  # MATCH for FTS
        
        return operators
    
    def _index_field_values(self, field_name: str, knowledge: FieldKnowledge):
        """构建字段值索引，支持快速模糊匹配"""
        # 为每个值建立小写索引
        for stats in knowledge.top_values:
            value = stats.value
            lower_value = value.lower()
            
            # 分词索引（对于多词值）
            words = re.findall(r'\b\w+\b', lower_value)
            for word in words:
                if word not in self._value_index[field_name]:
                    self._value_index[field_name][word] = set()
                self._value_index[field_name][word].add(value)
    
    def _build_synonym_graph(self):
        """构建同义词图"""
        # 基于数据自动发现同义词
        # 例如：如果两个值经常出现在相似的研究中，可能是同义词
        
        # 预定义的同义词
        synonym_mappings = {
            'brain': {'brain', 'cerebral', 'cortex', 'cerebellum', 'hippocampus', 'frontal lobe'},
            'lung': {'lung', 'pulmonary', 'bronchial'},
            'liver': {'liver', 'hepatic'},
            '10x': {'10x genomics', '10x', 'chromium', '10x chromium'},
            'smart-seq2': {'smart-seq2', 'smartseq2', 'smart-seq'},
            'covid-19': {'covid-19', 'covid19', 'sars-cov-2', 'coronavirus'}
        }
        
        for canonical, variants in synonym_mappings.items():
            self._synonym_graph[canonical] = variants
            for variant in variants:
                self._synonym_graph[variant].add(canonical)
                self._synonym_graph[variant].update(variants - {variant})
    
    # ==================== 查询辅助方法 ====================
    
    def find_similar_values(self, field_name: str, query: str, 
                           top_k: int = 5, threshold: float = 0.6) -> List[Tuple[str, float]]:
        """
        查找与查询相似的字段值
        
        Returns:
            [(value, similarity_score), ...]
        """
        if field_name not in self._field_knowledge:
            return []
        
        knowledge = self._field_knowledge[field_name]
        query_lower = query.lower()
        
        scores = []
        
        for stats in knowledge.top_values:
            value = stats.value
            value_lower = value.lower()
            
            # 计算相似度
            score = self._calculate_similarity(query_lower, value_lower)
            
            # 如果有记录数权重，适当加分
            if stats.count > 1000:
                score += 0.05
            
            if score >= threshold:
                scores.append((value, score))
        
        # 排序并返回Top K
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]
    
    def _calculate_similarity(self, s1: str, s2: str) -> float:
        """计算两个字符串的相似度（结合多种方法）"""
        # 完全匹配
        if s1 == s2:
            return 1.0
        
        # 包含匹配
        if s1 in s2 or s2 in s1:
            return 0.9
        
        # 单词重叠
        words1 = set(s1.split())
        words2 = set(s2.split())
        if words1 and words2:
            jaccard = len(words1 & words2) / len(words1 | words2)
            if jaccard > 0:
                return 0.7 + jaccard * 0.2
        
        # 编辑距离（归一化）
        max_len = max(len(s1), len(s2))
        if max_len == 0:
            return 0.0
        
        distance = self._levenshtein_distance(s1, s2)
        similarity = 1 - (distance / max_len)
        
        return max(0, similarity * 0.6)  # 编辑距离最高0.6分
    
    def _levenshtein_distance(self, s1: str, s2: str) -> int:
        """计算编辑距离"""
        if len(s1) < len(s2):
            return self._levenshtein_distance(s2, s1)
        
        if len(s2) == 0:
            return len(s1)
        
        previous_row = range(len(s2) + 1)
        for i, c1 in enumerate(s1):
            current_row = [i + 1]
            for j, c2 in enumerate(s2):
                insertions = previous_row[j + 1] + 1
                deletions = current_row[j] + 1
                substitutions = previous_row[j] + (c1 != c2)
                current_row.append(min(insertions, deletions, substitutions))
            previous_row = current_row
        
        return previous_row[-1]
    
    def get_field_statistics(self, field_name: str) -> Optional[FieldKnowledge]:
        """获取字段统计信息"""
        return self._field_knowledge.get(field_name)
    
    def get_semantic_fields(self, semantic_type: str) -> List[str]:
        """获取指定语义类型的所有字段"""
        fields = []
        for field_name, knowledge in self._field_knowledge.items():
            if knowledge.semantic_type == semantic_type:
                fields.append(field_name)
        return fields
    
    def estimate_result_count(self, filters: Dict[str, Any]) -> int:
        """
        估算查询可能返回的结果数量
        用于预测零结果风险
        """
        estimates = []
        
        for match_type, conditions in filters.items():
            if not conditions:
                continue
            
            for field, value in conditions.items():
                if field not in self._field_knowledge:
                    continue
                
                knowledge = self._field_knowledge[field]
                
                if match_type == 'exact_match':
                    count = knowledge.value_distribution.get(str(value), 0)
                elif match_type == 'partial_match':
                    # 估算模糊匹配结果
                    count = sum(
                        stats.count for stats in knowledge.top_values
                        if str(value).lower() in stats.value.lower()
                    )
                else:
                    count = knowledge.total_records - knowledge.null_count
                
                estimates.append((field, count))
        
        if not estimates:
            # 返回总记录数
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM std")
            total = cursor.fetchone()[0]
            conn.close()
            return total
        
        # 保守估计：取最小值（假设AND条件）
        return min(count for _, count in estimates)
    
    def detect_conflicting_conditions(self, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        检测可能导致零结果的冲突条件
        
        Returns:
            [{
                'fields': [field1, field2],
                'reason': '说明',
                'suggestion': '建议'
            }]
        """
        conflicts = []
        
        # 检查1：同一语义类型的多个字段被同时约束
        semantic_fields_used = defaultdict(list)
        for match_type, conditions in filters.items():
            for field in conditions.keys():
                if field in self._field_knowledge:
                    sem_type = self._field_knowledge[field].semantic_type
                    semantic_fields_used[sem_type].append(field)
        
        for sem_type, fields in semantic_fields_used.items():
            if len(fields) > 1 and sem_type in ['disease', 'tissue', 'platform']:
                conflicts.append({
                    'fields': fields,
                    'reason': f'同一{sem_type}类型的多个字段被同时约束，可能导致过度限制',
                    'suggestion': f'建议只使用最标准化的字段: {fields[0]}',
                    'severity': 'warning'
                })
        
        # 检查2：估算结果数为0
        estimated = self.estimate_result_count(filters)
        if estimated == 0:
            conflicts.append({
                'fields': list(filters.get('exact_match', {}).keys()) + 
                         list(filters.get('partial_match', {}).keys())),
                'reason': '当前条件组合在数据库中无匹配记录',
                'suggestion': '尝试放宽条件或使用模糊匹配',
                'severity': 'critical'
            })
        
        return conflicts
    
    def suggest_query_strategy(self, query_concepts: Dict[str, str]) -> Dict[str, Any]:
        """
        根据查询概念建议最优查询策略
        
        Args:
            query_concepts: {'disease': 'lung cancer', 'tissue': 'brain', ...}
        
        Returns:
            {
                'primary_field': 'xxx',
                'secondary_fields': ['yyy', 'zzz'],
                'suggested_values': {'disease_clean': ['Lung Cancer', ...]},
                'operator': 'LIKE',
                'confidence': 0.9
            }
        """
        strategy = {
            'primary_fields': {},
            'secondary_fields': [],
            'suggested_values': {},
            'operators': {},
            'confidence': 1.0
        }
        
        for concept, value in query_concepts.items():
            # 找到该语义类型的最佳字段
            fields = self._semantic_fields.get(concept, [])
            
            if not fields:
                continue
            
            # 优先使用有数据的标准化字段
            best_field = None
            for field in fields:
                if field in self._field_knowledge:
                    knowledge = self._field_knowledge[field]
                    if knowledge.null_percentage < 50:  # 非空值超过50%
                        best_field = field
                        break
            
            if not best_field:
                best_field = fields[0]
            
            strategy['primary_fields'][concept] = best_field
            
            # 查找相似值
            similar_values = self.find_similar_values(best_field, value, top_k=3)
            if similar_values:
                strategy['suggested_values'][best_field] = [
                    {'value': v, 'score': s, 'count': self._field_knowledge[best_field].value_distribution.get(v, 0)}
                    for v, s in similar_values
                ]
                strategy['confidence'] *= max(s for _, s in similar_values)
            else:
                # 没有找到相似值，降低置信度
                strategy['suggested_values'][best_field] = [{'value': value, 'score': 0.5, 'count': 0}]
                strategy['confidence'] *= 0.5
            
            # 建议操作符
            knowledge = self._field_knowledge.get(best_field)
            if knowledge:
                strategy['operators'][best_field] = knowledge.suggested_operators[0]
        
        return strategy
    
    def get_enriched_schema_description(self) -> str:
        """生成增强的Schema描述，包含实际数据示例"""
        lines = ["# 数据库Schema（数据感知版本）\n"]
        
        for sem_type, fields in self._semantic_fields.items():
            lines.append(f"\n## {sem_type.upper()} 字段")
            
            for field in fields:
                if field not in self._field_knowledge:
                    continue
                
                knowledge = self._field_knowledge[field]
                lines.append(f"\n### {field}")
                lines.append(f"- 记录数: {knowledge.total_records - knowledge.null_count:,} / {knowledge.total_records:,}")
                lines.append(f"- 唯一值: {knowledge.unique_count:,}")
                lines.append(f"- 建议操作符: {', '.join(knowledge.suggested_operators[:2])}")
                
                if knowledge.top_values[:5]:
                    examples = [f"'{v.value}'({v.count:,})" for v in knowledge.top_values[:5]]
                    lines.append(f"- 常见值: {', '.join(examples)}")
        
        return '\n'.join(lines)
    
    def refresh(self):
        """刷新知识库"""
        self.logger.info("刷新知识库...")
        self._field_knowledge.clear()
        self._value_index.clear()
        self._build_knowledge()
