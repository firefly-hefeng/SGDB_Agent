import logging
from typing import Dict, List, Any, Optional
from datetime import datetime

class QueryPlanner:
    """
    查询规划器 - 负责查询意图识别、分解和优化
    """
    
    def __init__(self, config: Dict[str, Any], ai_retriever, memory_system):
        self.config = config
        self.ai_retriever = ai_retriever
        self.memory_system = memory_system
        self.logger = logging.getLogger(__name__)
    
    def plan_query(self, 
                   user_query: str, 
                   session_id: str,
                   available_fields: Dict[str, List[str]]) -> Dict[str, Any]:
        """
        规划查询执行方案
        
        Args:
            user_query: 用户自然语言查询
            session_id: 会话ID
            available_fields: 可用字段及其值
        
        Returns:
            查询计划
        """
        self.logger.info(f"开始规划查询: {user_query}")
        
        # 1. 获取上下文
        context = self.memory_system.working_memory.get_context(session_id)
        
        # 2. 识别查询意图
        intent = self._identify_intent(user_query, context)
        
        # 3. 根据意图类型规划
        if intent['type'] == 'simple_query':
            plan = self._plan_simple_query(user_query, context, available_fields)
        elif intent['type'] == 'refinement':
            plan = self._plan_refinement_query(user_query, context, available_fields)
        elif intent['type'] == 'aggregation':
            plan = self._plan_aggregation_query(user_query, context, available_fields)
        elif intent['type'] == 'comparison':
            plan = self._plan_comparison_query(user_query, context, available_fields)
        else:
            plan = self._plan_complex_query(user_query, context, available_fields)
        
        plan['intent'] = intent
        plan['session_id'] = session_id
        plan['timestamp'] = datetime.now().isoformat()
        
        self.logger.info(f"查询规划完成: 类型={intent['type']}, 步骤数={len(plan.get('steps', []))}")
        
        return plan
    
    def _identify_intent(self, query: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """识别查询意图"""
        query_lower = query.lower()
        
        # 检查是否是精化查询
        refinement_keywords = ['只要', '限制', '进一步', '再', '还要', '也要', '不要']
        is_refinement = any(kw in query for kw in refinement_keywords) and context['recent_queries']
        
        # 检查是否是统计/聚合查询
        aggregation_keywords = ['统计', '多少', '分布', '数量', '总共', '平均', '最多', '最少']
        is_aggregation = any(kw in query for kw in aggregation_keywords)
        
        # 检查是否是对比查询
        comparison_keywords = ['对比', '比较', '差异', 'vs', '和']
        is_comparison = any(kw in query for kw in comparison_keywords)
        
        if is_refinement:
            intent_type = 'refinement'
        elif is_aggregation:
            intent_type = 'aggregation'
        elif is_comparison:
            intent_type = 'comparison'
        elif len(query.split()) <= 10:
            intent_type = 'simple_query'
        else:
            intent_type = 'complex_query'
        
        return {
            'type': intent_type,
            'description': self._describe_intent(query, intent_type),
            'confidence': 0.9
        }
    
    def _describe_intent(self, query: str, intent_type: str) -> str:
        """描述查询意图"""
        descriptions = {
            'simple_query': f"简单查询: {query}",
            'refinement': f"精化查询: 在上次结果基础上进一步筛选",
            'aggregation': f"聚合查询: 统计分析数据",
            'comparison': f"对比查询: 比较不同条件下的数据",
            'complex_query': f"复杂查询: 多维度组合筛选"
        }
        return descriptions.get(intent_type, query)
    
    def _plan_simple_query(self, query: str, context: Dict, available_fields: Dict) -> Dict[str, Any]:
        """规划简单查询"""
        return {
            'type': 'simple',
            'steps': [
                {
                    'step': 1,
                    'action': 'parse_query',
                    'description': '解析自然语言查询'
                },
                {
                    'step': 2,
                    'action': 'execute_sql',
                    'description': '执行SQL查询'
                },
                {
                    'step': 3,
                    'action': 'return_results',
                    'description': '返回结果'
                }
            ]
        }
    
    def _plan_refinement_query(self, query: str, context: Dict, available_fields: Dict) -> Dict[str, Any]:
        """规划精化查询"""
        return {
            'type': 'refinement',
            'base_filters': context['recent_filters'][-1] if context['recent_filters'] else {},
            'steps': [
                {
                    'step': 1,
                    'action': 'parse_refinement',
                    'description': '解析精化条件'
                },
                {
                    'step': 2,
                    'action': 'merge_filters',
                    'description': '合并现有过滤条件'
                },
                {
                    'step': 3,
                    'action': 'execute_sql',
                    'description': '执行SQL查询'
                },
                {
                    'step': 4,
                    'action': 'return_results',
                    'description': '返回结果'
                }
            ]
        }
    
    def _plan_aggregation_query(self, query: str, context: Dict, available_fields: Dict) -> Dict[str, Any]:
        """规划聚合查询"""
        return {
            'type': 'aggregation',
            'steps': [
                {
                    'step': 1,
                    'action': 'identify_aggregation_field',
                    'description': '识别聚合字段'
                },
                {
                    'step': 2,
                    'action': 'execute_aggregation',
                    'description': '执行聚合统计'
                },
                {
                    'step': 3,
                    'action': 'format_statistics',
                    'description': '格式化统计结果'
                }
            ]
        }
    
    def _plan_comparison_query(self, query: str, context: Dict, available_fields: Dict) -> Dict[str, Any]:
        """规划对比查询"""
        return {
            'type': 'comparison',
            'steps': [
                {
                    'step': 1,
                    'action': 'identify_comparison_dimensions',
                    'description': '识别对比维度'
                },
                {
                    'step': 2,
                    'action': 'execute_parallel_queries',
                    'description': '并行执行多个查询'
                },
                {
                    'step': 3,
                    'action': 'generate_comparison_report',
                    'description': '生成对比报告'
                }
            ]
        }
    
    def _plan_complex_query(self, query: str, context: Dict, available_fields: Dict) -> Dict[str, Any]:
        """规划复杂查询"""
        # 使用AI分解复杂查询
        decomposition = self._decompose_query_with_ai(query, available_fields)
        
        return {
            'type': 'complex',
            'subqueries': decomposition.get('subqueries', []),
            'steps': [
                {
                    'step': 1,
                    'action': 'execute_subqueries',
                    'description': '执行子查询'
                },
                {
                    'step': 2,
                    'action': 'merge_results',
                    'description': '合并子查询结果'
                },
                {
                    'step': 3,
                    'action': 'apply_final_filters',
                    'description': '应用最终过滤'
                }
            ]
        }
    
    def _decompose_query_with_ai(self, query: str, available_fields: Dict) -> Dict[str, Any]:
        """使用AI分解复杂查询"""
        prompt = f"""请将以下复杂查询分解为多个简单的子查询：

查询: {query}

可用字段: {list(available_fields.keys())}

返回JSON格式：
{{
    "subqueries": [
        {{"description": "子查询1描述", "filters": {{}}}},
        {{"description": "子查询2描述", "filters": {{}}}}
    ]
}}
"""
        
        try:
            response = self.ai_retriever.call_llm(prompt, temperature=0.3)
            import json
            decomposition = json.loads(response)
            return decomposition
        except Exception as e:
            self.logger.error(f"查询分解失败: {e}")
            return {'subqueries': []}