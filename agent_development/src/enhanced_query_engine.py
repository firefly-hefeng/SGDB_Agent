"""
增强版查询引擎 - 整合数据感知和自适应查询
"""

import pandas as pd
import logging
import uuid
from typing import Dict, List, Any, Optional
from datetime import datetime
from pathlib import Path

from .config_manager import ConfigManager
from .db_manager import DatabaseManager
from .memory_system import MemorySystem
from .query_planner import QueryPlanner
from .field_expander import FieldExpander
from .data_downloader import DataDownloader

# 新增组件
from .schema_knowledge_base import SchemaKnowledgeBase
from .adaptive_query_engine import AdaptiveQueryEngine, SmartQueryBuilder, QueryStrategy
from .enhanced_ai_retriever import EnhancedAIRetriever


class EnhancedQueryEngine:
    """
    增强版查询引擎 v3.0
    
    新增特性：
    1. Schema知识库 - 深度理解数据库内容
    2. 自适应查询 - 自动调整策略避免零结果
    3. 增强AI解析 - 数据感知的查询理解
    4. 智能查询建议 - 基于数据分布的查询优化
    """
    
    def __init__(self, config: ConfigManager):
        self.config = config
        self.logger = logging.getLogger(__name__)
        
        # 基础组件
        self.db_manager = DatabaseManager(config.get('database'))
        
        # 新增：Schema知识库
        db_path = config.get('database', {}).get('path', 'data/scrnaseq.db')
        self.schema_kb = SchemaKnowledgeBase(db_path)
        
        # 新增：增强版AI检索器
        ai_config = config.get('ai', {})
        self.ai_retriever = EnhancedAIRetriever(ai_config, self.schema_kb)
        
        # 新增：自适应查询引擎
        self.adaptive_engine = AdaptiveQueryEngine(self.db_manager, self.schema_kb)
        
        # 新增：智能查询构建器
        self.smart_builder = SmartQueryBuilder(self.schema_kb)
        
        # 其他组件
        self.memory_system = MemorySystem(config.config)
        
        self.query_planner = QueryPlanner(
            config.config,
            self.ai_retriever,
            self.memory_system
        )
        
        self.field_expander = FieldExpander(
            config.config,
            self.db_manager,
            self.ai_retriever,
            self.memory_system
        )
        
        download_config = config.get('download', {})
        self.data_downloader = DataDownloader(download_config)
        
        # 缓存
        self._schema_cache = None
        self._data_cache = None
    
    def initialize(self):
        """初始化引擎"""
        self.logger.info("正在初始化增强版查询引擎...")
        
        # 连接数据库
        self.db_manager.connect()
        
        # 初始化记忆系统
        self.memory_system.initialize()
        
        # 加载schema（使用知识库的增强版本）
        self._load_schema()
        
        # 设置AI的schema信息
        self.ai_retriever.set_database_schema(self._schema_cache)
        
        self.logger.info("增强版查询引擎初始化完成")
        self.logger.info(f"Schema知识库已加载，包含 {len(self.schema_kb._field_knowledge)} 个字段")
    
    def _load_schema(self):
        """加载增强的Schema信息"""
        if self._schema_cache is None:
            self.logger.info("正在加载增强Schema...")
            
            # 使用知识库生成数据感知的Schema描述
            schema_desc = self.schema_kb.get_enriched_schema_description()
            
            # 同时获取传统schema用于兼容
            traditional_schema = self.db_manager.get_schema_info()
            
            self._schema_cache = {
                'description': schema_desc,
                'traditional': traditional_schema,
                'field_stats': {
                    field: {
                        'total': k.total_records,
                        'unique': k.unique_count,
                        'null_pct': k.null_percentage,
                        'semantic_type': k.semantic_type,
                        'top_values': [v.value for v in k.top_values[:10]]
                    }
                    for field, k in self.schema_kb._field_knowledge.items()
                }
            }
            
            self.logger.info(f"Schema加载完成")
    
    def execute_query(self,
                     natural_query: str,
                     session_id: Optional[str] = None,
                     limit: int = 20,
                     offset: int = 0,
                     use_ai: bool = True,
                     adaptive: bool = True) -> Dict[str, Any]:
        """
        执行查询（增强版）
        
        Args:
            natural_query: 自然语言查询
            session_id: 会话ID
            limit: 返回结果数
            offset: 偏移量
            use_ai: 是否使用AI
            adaptive: 是否使用自适应查询（防止零结果）
        
        Returns:
            查询结果
        """
        start_time = datetime.now()
        
        if not session_id:
            session_id = str(uuid.uuid4())
        
        self.logger.info(f"执行增强查询: {natural_query} (会话: {session_id})")
        
        try:
            # 1. 查询规划
            query_plan = self.query_planner.plan_query(
                natural_query,
                session_id,
                self._schema_cache['traditional']
            )
            
            # 2. 使用增强版AI解析查询
            if use_ai:
                parsed = self.ai_retriever.parse_natural_query_with_knowledge(
                    natural_query,
                    self.schema_kb,
                    self._schema_cache['traditional']
                )
            else:
                parsed = self._simple_parse(natural_query)
            
            filters = parsed.get('filters', {})
            
            # 3. 如果启用自适应查询，使用自适应引擎
            if adaptive and parsed.get('estimated_results', 0) < 10:
                self.logger.info("检测到潜在零结果风险，启用自适应查询")
                
                adaptive_result = self.adaptive_engine.execute_adaptive_query(
                    natural_query,
                    filters,
                    session_context=self.memory_system.working_memory.get_context(session_id)
                )
                
                result = {
                    'query': natural_query,
                    'results': adaptive_result.get('results', pd.DataFrame()),
                    'total_count': adaptive_result.get('total_count', 0),
                    'returned_count': len(adaptive_result.get('results', pd.DataFrame())),
                    'filters': adaptive_result.get('filters', filters),
                    'adaptive_info': {
                        'strategy': adaptive_result.get('strategy'),
                        'attempts': adaptive_result.get('attempts'),
                        'query_analysis': adaptive_result.get('query_analysis')
                    },
                    'explanation': adaptive_result.get('explanation', ''),
                    'suggestions': adaptive_result.get('suggestions', [])
                }
            else:
                # 标准查询流程
                result = self._execute_standard(natural_query, filters, limit, offset)
            
            # 4. 更新记忆系统
            self._update_memory(session_id, natural_query, result)
            
            # 5. 添加查询建议
            if result['total_count'] == 0:
                result['alternative_queries'] = self.ai_retriever.suggest_query_refinement(
                    natural_query, result['filters']
                )
            elif result['total_count'] < 10:
                result['broader_suggestions'] = self._suggest_broader_query(result['filters'])
            
            result['session_id'] = session_id
            result['execution_time'] = (datetime.now() - start_time).total_seconds()
            
            return result
            
        except Exception as e:
            self.logger.error(f"查询执行失败: {e}", exc_info=True)
            return {
                'query': natural_query,
                'session_id': session_id,
                'results': pd.DataFrame(),
                'total_count': 0,
                'error': str(e),
                'execution_time': (datetime.now() - start_time).total_seconds()
            }
    
    def _execute_standard(self, 
                         query: str,
                         filters: Dict[str, Any],
                         limit: int,
                         offset: int) -> Dict[str, Any]:
        """执行标准查询"""
        # 执行查询
        total_count = self.db_manager.count_results(filters)
        results = self.db_manager.search(filters, limit=limit, offset=offset)
        
        # 生成解释
        explanation = ""
        if not results.empty:
            explanation = self.ai_retriever.explain_query_strategy(
                query, filters, total_count
            )
        
        return {
            'query': query,
            'results': results,
            'total_count': total_count,
            'returned_count': len(results),
            'filters': filters,
            'explanation': explanation,
            'timestamp': datetime.now().isoformat()
        }
    
    def _update_memory(self, session_id: str, query: str, result: Dict[str, Any]):
        """更新记忆系统"""
        self.memory_system.working_memory.add_conversation_turn(
            session_id, query, result
        )
        
        if result.get('filters'):
            self.memory_system.working_memory.add_query_to_chain(
                session_id, query, result['filters']
            )
        
        self.memory_system.working_memory.set_current_results(
            session_id, result.get('results')
        )
    
    def _suggest_broader_query(self, current_filters: Dict[str, Any]) -> List[str]:
        """建议更宽泛的查询"""
        suggestions = []
        
        # 建议1：移除一个条件
        for match_type, conditions in current_filters.items():
            if len(conditions) > 1:
                for field in list(conditions.keys())[1:]:
                    suggestions.append(f"尝试移除 '{field}' 条件以获取更多结果")
        
        # 建议2：使用相似值
        for match_type, conditions in current_filters.items():
            for field, value in conditions.items():
                similar = self.schema_kb.find_similar_values(field, str(value), top_k=3)
                if similar and similar[0][1] < 0.9:  # 不是很精确的匹配
                    alt_values = ', '.join([v for v, _ in similar[:2]])
                    suggestions.append(f"字段 '{field}' 可尝试相关值: {alt_values}")
        
        return suggestions[:3]
    
    def smart_search(self,
                    concepts: Dict[str, str],
                    limit: int = 20) -> Dict[str, Any]:
        """
        智能搜索 - 直接基于概念搜索
        
        Args:
            concepts: {'disease': 'lung cancer', 'tissue': 'brain', ...}
            limit: 返回数量
        """
        self.logger.info(f"执行智能搜索: {concepts}")
        
        # 使用智能查询构建器
        query_build = self.smart_builder.build_smart_query(concepts)
        filters = query_build['filters']
        
        # 执行查询
        total_count = self.db_manager.count_results(filters)
        results = self.db_manager.search(filters, limit=limit)
        
        return {
            'concepts': concepts,
            'filters': filters,
            'results': results,
            'total_count': total_count,
            'strategy_confidence': query_build['strategy_confidence'],
            'suggested_values': query_build['suggested_values']
        }
    
    def get_field_insights(self, field_name: str) -> Dict[str, Any]:
        """
        获取字段洞察
        """
        stats = self.schema_kb.get_field_statistics(field_name)
        if not stats:
            return {'error': f'字段 {field_name} 不存在'}
        
        return {
            'field_name': field_name,
            'semantic_type': stats.semantic_type,
            'data_quality': {
                'total_records': stats.total_records,
                'null_percentage': stats.null_percentage,
                'unique_values': stats.unique_count
            },
            'value_distribution': [
                {'value': v.value, 'count': v.count, 'percentage': v.percentage}
                for v in stats.top_values[:20]
            ],
            'suggested_operators': stats.suggested_operators
        }
    
    def find_similar_values(self, 
                           field_name: str, 
                           query: str, 
                           top_k: int = 10) -> List[Dict[str, Any]]:
        """查找相似值"""
        similar = self.schema_kb.find_similar_values(field_name, query, top_k=top_k)
        
        return [
            {
                'value': value,
                'similarity': score,
                'count': self.schema_kb._field_knowledge[field_name].value_distribution.get(value, 0)
            }
            for value, score in similar
        ]
    
    def analyze_query_feasibility(self, natural_query: str) -> Dict[str, Any]:
        """
        分析查询可行性
        """
        # 先用AI解析
        parsed = self.ai_retriever.parse_natural_query_with_knowledge(
            natural_query, self.schema_kb
        )
        
        filters = parsed.get('filters', {})
        
        # 分析可行性
        analysis = self.adaptive_engine._analyze_filters(filters)
        
        return {
            'query': natural_query,
            'parsed_filters': filters,
            'feasibility': {
                'risk_level': analysis['risk_level'],
                'estimated_results': analysis['estimated_count'],
                'conflicts': analysis['conflicts']
            },
            'suggestions': self._generate_feasibility_suggestions(analysis)
        }
    
    def _generate_feasibility_suggestions(self, analysis: Dict[str, Any]) -> List[str]:
        """生成可行性建议"""
        suggestions = []
        
        if analysis['risk_level'] == 'critical':
            suggestions.append("⚠️ 当前查询可能返回零结果，建议使用自适应查询模式")
        elif analysis['risk_level'] == 'high':
            suggestions.append("⚡ 查询条件较严格，可能只返回少量结果")
        
        for conflict in analysis['conflicts']:
            suggestions.append(f"• {conflict['suggestion']}")
        
        return suggestions
    
    def _simple_parse(self, query: str) -> Dict[str, Any]:
        """简单解析（不使用AI）"""
        filters = {
            'exact_match': {},
            'partial_match': {},
            'boolean_match': {},
            'range_match': {}
        }
        
        query_lower = query.lower()
        
        # 使用知识库进行简单映射
        if '脑' in query or 'brain' in query_lower:
            # 查找最佳组织字段
            tissue_fields = self.schema_kb.get_semantic_fields('tissue')
            if tissue_fields:
                # 查找Brain的相似值
                similar = self.schema_kb.find_similar_values(tissue_fields[0], 'brain', top_k=1)
                if similar:
                    filters['partial_match'][tissue_fields[0]] = similar[0][0]
                else:
                    filters['partial_match'][tissue_fields[0]] = 'brain'
        
        if '10x' in query_lower:
            platform_fields = self.schema_kb.get_semantic_fields('platform')
            if platform_fields:
                similar = self.schema_kb.find_similar_values(platform_fields[0], '10x', top_k=1)
                if similar:
                    filters['partial_match'][platform_fields[0]] = similar[0][0]
                else:
                    filters['partial_match'][platform_fields[0]] = '10x'
        
        return {
            'filters': filters,
            'intent': query,
            'keywords': query.split(),
            'confidence': 0.5
        }
    
    def refresh_knowledge_base(self):
        """刷新知识库"""
        self.logger.info("刷新Schema知识库...")
        self.schema_kb.refresh()
        self._schema_cache = None
        self._load_schema()
        self.logger.info("知识库刷新完成")
    
    # ==================== 保留原有方法 ====================
    
    def get_session_context(self, session_id: str) -> Dict[str, Any]:
        """获取会话上下文"""
        return self.memory_system.working_memory.get_context(session_id)
    
    def clear_session(self, session_id: str):
        """清空会话"""
        self.memory_system.working_memory.clear_session(session_id)
    
    def export_results(self, results: pd.DataFrame, filepath: str, 
                      format: str = 'auto') -> bool:
        """导出结果"""
        try:
            export_path = Path(filepath)
            export_path.parent.mkdir(parents=True, exist_ok=True)
            
            if format == 'auto':
                format = export_path.suffix.lower().lstrip('.')
            
            if format == 'csv':
                results.to_csv(export_path, index=False, encoding='utf-8-sig')
            elif format in ['xlsx', 'xls']:
                results.to_excel(export_path, index=False, engine='openpyxl')
            elif format == 'json':
                results.to_json(export_path, orient='records', indent=2, force_ascii=False)
            else:
                export_path = export_path.with_suffix('.csv')
                results.to_csv(export_path, index=False, encoding='utf-8-sig')
            
            self.logger.info(f"结果已导出到: {export_path}")
            return True
            
        except Exception as e:
            self.logger.error(f"导出失败: {e}")
            return False
    
    def cleanup(self):
        """清理资源"""
        if self.db_manager:
            self.db_manager.close()
        if self.memory_system:
            self.memory_system.cleanup()
        if self.data_downloader:
            self.data_downloader.shutdown()
        self.logger.info("查询引擎资源已清理")
