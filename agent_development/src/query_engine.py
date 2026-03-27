import pandas as pd
import logging
import uuid
from typing import Dict, List, Any, Optional, Callable
from datetime import datetime
from pathlib import Path

from .config_manager import ConfigManager
from .db_manager import DatabaseManager
from .ai_retriever import AIRetriever
from .memory_system import MemorySystem
from .query_planner import QueryPlanner
from .field_expander import FieldExpander
from .data_downloader import DataDownloader, DownloadTask

class QueryEngine:
    """
    核心查询引擎 - 整合所有组件
    """
    def __init__(self, config: ConfigManager):
        self.config = config
        self.logger = logging.getLogger(__name__)
        
        # 初始化组件
        self.db_manager = DatabaseManager(config.get('database'))
        
        ai_config = config.get('ai')
        self.ai_retriever = AIRetriever(ai_config)
        
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
        
        # 数据下载器
        download_config = config.get('download', {})
        self.data_downloader = DataDownloader(download_config)
        
        # 缓存
        self._schema_cache = None
        self._data_cache = None
    
    def initialize(self):
        """初始化引擎"""
        self.logger.info("正在初始化查询引擎...")
        
        # 连接数据库
        self.db_manager.connect()
        
        # 初始化记忆系统
        self.memory_system.initialize()
        
        # 加载schema
        self._load_schema()
        
        # 设置AI的schema信息
        self.ai_retriever.set_database_schema(self._schema_cache)
        
        self.logger.info("查询引擎初始化完成")
    
    def _load_schema(self):
        """加载数据库schema"""
        if self._schema_cache is None:
            self.logger.info("正在加载数据库schema...")
            self._schema_cache = self.db_manager.get_schema_info()
            self.logger.info(f"Schema加载完成，包含 {len(self._schema_cache)} 个分类字段")
    
    def execute_query(self,
                     natural_query: str,
                     session_id: Optional[str] = None,
                     limit: int = 20,
                     offset: int = 0,
                     use_ai: bool = True) -> Dict[str, Any]:
        """
        执行查询
        
        Args:
            natural_query: 自然语言查询
            session_id: 会话ID（用于多轮对话）
            limit: 返回结果数
            offset: 偏移量
            use_ai: 是否使用AI
        
        Returns:
            查询结果
        """
        start_time = datetime.now()
        
        # 生成或获取会话ID
        if not session_id:
            session_id = str(uuid.uuid4())
        
        self.logger.info(f"执行查询: {natural_query} (会话: {session_id})")
        
        try:
            # 1. 查询规划
            query_plan = self.query_planner.plan_query(
                natural_query,
                session_id,
                self._schema_cache
            )
            
            # 2. 根据计划类型执行
            if query_plan['intent']['type'] == 'refinement':
                result = self._execute_refinement_query(
                    natural_query, session_id, query_plan, limit, offset
                )
            elif query_plan['intent']['type'] == 'aggregation':
                result = self._execute_aggregation_query(
                    natural_query, session_id, query_plan
                )
            else:
                result = self._execute_standard_query(
                    natural_query, session_id, limit, offset, use_ai
                )
            
            # 3. 更新工作记忆
            self.memory_system.working_memory.add_conversation_turn(
                session_id, natural_query, result
            )
            
            if result.get('filters'):
                self.memory_system.working_memory.add_query_to_chain(
                    session_id, natural_query, result['filters']
                )
            
            # 4. 设置当前结果
            self.memory_system.working_memory.set_current_results(
                session_id, result.get('results')
            )
            
            # 5. 检查是否需要字段扩展
            if result['total_count'] > 1000 and use_ai:
                result['field_expansion_suggestion'] = self._suggest_field_expansion(
                    natural_query, result
                )
            
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
    
    def _execute_standard_query(self,
                               query: str,
                               session_id: str,
                               limit: int,
                               offset: int,
                               use_ai: bool) -> Dict[str, Any]:
        """执行标准查询"""
        # AI解析查询
        if use_ai:
            parsed = self.ai_retriever.parse_natural_query(query, self._schema_cache)
            filters = parsed.get('filters', {})
            intent = parsed.get('intent', query)
            keywords = parsed.get('keywords', [])
            
            # 增强过滤条件
            full_data = self._get_full_data()
            filters = self.ai_retriever.enhance_filters(filters, full_data)
        else:
            filters = self._simple_parse(query)
            intent = query
            keywords = query.split()
        
        # 执行查询
        total_count = self.db_manager.count_results(filters)
        results = self.db_manager.search(filters, limit=limit, offset=offset)
        
        # 如果返回0条，尝试放宽条件（去掉可选的布尔过滤如matrix_open）
        if total_count == 0 and 'boolean_match' in filters and filters['boolean_match']:
            self.logger.info("严格查询返回0条，尝试放宽条件...")
            relaxed_filters = filters.copy()
            # 保留关键的布尔条件，只去掉开放数据相关
            if 'matrix_open' in relaxed_filters.get('boolean_match', {}):
                del relaxed_filters['boolean_match']['matrix_open']
            if 'raw_open' in relaxed_filters.get('boolean_match', {}):
                del relaxed_filters['boolean_match']['raw_open']
            
            if relaxed_filters != filters:
                total_count = self.db_manager.count_results(relaxed_filters)
                results = self.db_manager.search(relaxed_filters, limit=limit, offset=offset)
                if total_count > 0:
                    self.logger.info(f"放宽条件后找到 {total_count} 条记录")
                    filters = relaxed_filters  # 使用放宽后的条件
        
        # 生成解释和建议
        explanation = ""
        suggestions = []
        
        if use_ai and not results.empty:
            explanation = self.ai_retriever.explain_results(query, results, total_count)
            suggestions = self.ai_retriever.suggest_queries(query, results)
        
        return {
            'query': query,
            'results': results,
            'total_count': total_count,
            'returned_count': len(results),
            'filters': filters,
            'intent': intent,
            'keywords': keywords,
            'explanation': explanation,
            'suggestions': suggestions,
            'timestamp': datetime.now().isoformat()
        }
    
    def _execute_refinement_query(self,
                                 query: str,
                                 session_id: str,
                                 query_plan: Dict,
                                 limit: int,
                                 offset: int) -> Dict[str, Any]:
        """执行精化查询"""
        # 获取基础过滤条件
        base_filters = query_plan.get('base_filters', {})
        
        # 解析新的精化条件
        parsed = self.ai_retriever.parse_natural_query(query, self._schema_cache)
        new_filters = parsed.get('filters', {})
        
        # 合并过滤条件
        merged_filters = self._merge_filters(base_filters, new_filters)
        
        # 执行查询
        total_count = self.db_manager.count_results(merged_filters)
        results = self.db_manager.search(merged_filters, limit=limit, offset=offset)
        
        return {
            'query': query,
            'query_type': 'refinement',
            'results': results,
            'total_count': total_count,
            'returned_count': len(results),
            'filters': merged_filters,
            'base_filters': base_filters,
            'intent': parsed.get('intent', query),
            'explanation': self.ai_retriever.explain_results(query, results, total_count),
            'timestamp': datetime.now().isoformat()
        }
    
    def _execute_aggregation_query(self,
                                  query: str,
                                  session_id: str,
                                  query_plan: Dict) -> Dict[str, Any]:
        """执行聚合查询"""
        # 识别聚合字段
        aggregation_field = self._identify_aggregation_field(query)
        
        # 获取统计信息
        stats = self.db_manager.get_field_statistics(aggregation_field)
        
        return {
            'query': query,
            'query_type': 'aggregation',
            'aggregation_field': aggregation_field,
            'statistics': stats,
            'total_count': len(stats),
            'timestamp': datetime.now().isoformat()
        }
    
    def _merge_filters(self, base: Dict, new: Dict) -> Dict:
        """合并过滤条件"""
        merged = {
            'exact_match': {**base.get('exact_match', {}), **new.get('exact_match', {})},
            'partial_match': {**base.get('partial_match', {}), **new.get('partial_match', {})},
            'boolean_match': {**base.get('boolean_match', {}), **new.get('boolean_match', {})},
            'range_match': {**base.get('range_match', {}), **new.get('range_match', {})}
        }
        return merged
    
    def _identify_aggregation_field(self, query: str) -> str:
        """识别聚合字段"""
        query_lower = query.lower()
        
        field_keywords = {
            'disease': ['疾病', 'disease'],
            'tissue_location': ['组织', 'tissue'],
            'sequencing_platform': ['平台', 'platform', '测序'],
            'source_database': ['数据库', 'database', '来源']
        }
        
        for field, keywords in field_keywords.items():
            if any(kw in query_lower for kw in keywords):
                return field
        
        return 'disease'  # 默认
    
    def _suggest_field_expansion(self, query: str, result: Dict) -> Dict[str, Any]:
        """建议字段扩展"""
        return {
            'suggested': True,
            'reason': f'查询返回了{result["total_count"]}条记录，建议创建新的筛选字段以精确定位',
            'example_field': {
                'field_name': 'custom_filter_' + datetime.now().strftime('%Y%m%d'),
                'definition': f'根据查询"{query}"定义的自定义筛选条件'
            }
        }
    
    def expand_field_for_query(self,
                              field_definition: Dict[str, Any],
                              query_filters: Dict[str, Any]) -> Dict[str, Any]:
        """
        为特定查询扩展字段
        
        Args:
            field_definition: 字段定义
            query_filters: 查询过滤条件
        
        Returns:
            扩展结果
        """
        # 获取目标记录
        target_records = self.db_manager.search(query_filters, limit=10000)
        
        if target_records.empty:
            return {
                'status': 'failed',
                'error': '没有找到匹配的记录'
            }
        
        # 执行字段扩展
        expansion_result = self.field_expander.expand_field(
            field_definition,
            target_records,
            validate_sampling=True
        )
        
        # 如果成功且使用频率高，考虑推广到全库
        if expansion_result['status'] == 'completed':
            if self.field_expander.should_promote_field(field_definition['field_name']):
                self.logger.info(f"字段 {field_definition['field_name']} 达到推广阈值")
                # 这里可以触发全库扩展的后台任务
        
        return expansion_result
    
    def _simple_parse(self, query: str) -> Dict[str, Any]:
        """简单解析（不使用AI）"""
        filters = {
            'exact_match': {},
            'partial_match': {},
            'boolean_match': {},
            'range_match': {}
        }
        
        query_lower = query.lower()
        
        # 关键词匹配
        if 'open' in query_lower or '开放' in query_lower:
            filters['boolean_match']['matrix_open'] = True
        
        if '10x' in query_lower:
            filters['partial_match']['sequencing_platform'] = '10x'
        
        if 'cancer' in query_lower or '癌' in query_lower:
            filters['partial_match']['disease_general'] = 'Cancer'
        
        # 默认在title中搜索
        filters['partial_match']['title'] = query
        
        return filters
    
    def _get_full_data(self) -> pd.DataFrame:
        """获取完整数据（带缓存）"""
        if self._data_cache is None:
            self.logger.info("正在加载完整数据...")
            self._data_cache = self.db_manager.get_all_data()
            self.logger.info(f"数据加载完成，共 {len(self._data_cache)} 条记录")
        return self._data_cache
    
    def get_statistics(self, field: str, filters: Optional[Dict] = None, 
                      top_n: int = 20) -> pd.DataFrame:
        """获取统计信息"""
        try:
            stats = self.db_manager.get_field_statistics(field, filters)
            return stats.head(top_n)
        except Exception as e:
            self.logger.error(f"统计失败: {e}")
            return pd.DataFrame()
    
    def export_results(self, results: pd.DataFrame, filepath: str, 
                      format: str = 'auto') -> bool:
        """导出结果"""
        try:
            from pathlib import Path
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
    
    def get_session_context(self, session_id: str) -> Dict[str, Any]:
        """获取会话上下文"""
        return self.memory_system.working_memory.get_context(session_id)
    
    def clear_session(self, session_id: str):
        """清空会话"""
        self.memory_system.working_memory.clear_session(session_id)
    
    def cleanup(self):
        """清理资源"""
        if self.db_manager:
            self.db_manager.close()
        if self.memory_system:
            self.memory_system.cleanup()
        if self.data_downloader:
            self.data_downloader.shutdown()
        self.logger.info("查询引擎资源已清理")
    
    # ==================== 数据下载功能 ====================
    
    def create_download_tasks(self, 
                              records: pd.DataFrame,
                              file_types: List[str] = None,
                              output_dir: Optional[str] = None) -> List[DownloadTask]:
        """
        根据查询结果创建下载任务
        
        Args:
            records: 查询结果DataFrame
            file_types: 要下载的文件类型 ['matrix', 'raw', 'metadata']
            output_dir: 输出目录
        
        Returns:
            下载任务列表
        """
        return self.data_downloader.create_download_tasks(records, file_types, output_dir)
    
    def start_download(self, 
                       tasks: List[DownloadTask],
                       progress_callback: Optional[Callable] = None) -> Dict[str, Any]:
        """
        开始批量下载
        
        Args:
            tasks: 下载任务列表
            progress_callback: 进度回调函数 (task_id, progress, speed)
        
        Returns:
            下载统计信息
        """
        def completion_callback(task_id: str, success: bool):
            status = "成功" if success else "失败"
            self.logger.info(f"下载任务 {task_id[:8]}... {status}")
        
        return self.data_downloader.start_download(
            tasks, 
            progress_callback=progress_callback,
            completion_callback=completion_callback
        )
    
    def download_data(self,
                      records: pd.DataFrame,
                      file_types: List[str] = None,
                      output_dir: Optional[str] = None,
                      progress_callback: Optional[Callable] = None,
                      generate_script: bool = False) -> Dict[str, Any]:
        """
        一键下载数据（创建任务并执行）
        
        Args:
            records: 查询结果DataFrame
            file_types: 要下载的文件类型
            output_dir: 输出目录
            progress_callback: 进度回调
            generate_script: 是否同时生成下载脚本
        
        Returns:
            下载结果统计
        """
        # 创建下载任务
        tasks = self.create_download_tasks(records, file_types, output_dir)
        
        if not tasks:
            return {
                'status': 'no_tasks',
                'message': '没有可下载的数据',
                'tasks': [],
                'script_path': None,
                'list_path': None
            }
        
        result = {
            'status': 'started',
            'total_tasks': len(tasks),
            'tasks': [t.to_dict() for t in tasks],
            'script_path': None,
            'list_path': None
        }
        
        # 生成下载脚本（如果请求）
        if generate_script:
            script_path = self.data_downloader.generate_download_script(tasks)
            result['script_path'] = str(script_path)
        
        # 导出下载列表
        list_path = self.data_downloader.export_download_list(tasks)
        result['list_path'] = str(list_path)
        
        # 执行下载
        stats = self.start_download(tasks, progress_callback)
        result['stats'] = stats
        result['status'] = 'completed' if stats['failed'] == 0 else 'partial'
        
        return result
    
    def get_download_status(self, task_id: str = None) -> Any:
        """
        获取下载状态
        
        Args:
            task_id: 任务ID，None则返回所有任务
        
        Returns:
            任务状态或任务列表
        """
        if task_id:
            task = self.data_downloader.get_task_status(task_id)
            return task.to_dict() if task else None
        else:
            tasks = self.data_downloader.get_all_tasks()
            return [t.to_dict() for t in tasks]
    
    def get_download_preview(self, records: pd.DataFrame, 
                             max_preview: int = 5) -> Dict[str, Any]:
        """
        获取下载预览信息（不下砸，仅显示信息）
        
        Args:
            records: 查询结果
            max_preview: 预览记录数
        
        Returns:
            预览信息
        """
        preview_records = records.head(max_preview)
        
        preview = {
            'total_records': len(records),
            'preview_records': [],
            'database_distribution': records['database_standardized'].value_counts().to_dict() 
                if 'database_standardized' in records.columns else {},
            'file_type_distribution': records['file_type'].value_counts().to_dict()
                if 'file_type' in records.columns else {}
        }
        
        for _, record in preview_records.iterrows():
            preview['preview_records'].append({
                'sample_uid': record.get('sample_uid'),
                'project_id': record.get('project_id_primary'),
                'database': record.get('database_standardized'),
                'title': record.get('title', '')[:80] + '...' if len(str(record.get('title', ''))) > 80 else record.get('title', ''),
                'access_link': record.get('access_link'),
                'file_type': record.get('file_type')
            })
        
        return preview
    
    def generate_download_script(self, records: pd.DataFrame,
                                  file_types: List[str] = None,
                                  output_path: Optional[str] = None) -> Path:
        """
        生成批量下载脚本
        
        Args:
            records: 查询结果
            file_types: 文件类型
            output_path: 输出路径
        
        Returns:
            脚本文件路径
        """
        tasks = self.create_download_tasks(records, file_types)
        return self.data_downloader.generate_download_script(tasks, output_path)