import pandas as pd
import sqlite3
import logging
import threading
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

# 线程本地存储，用于多线程数据库连接
thread_local = threading.local()

class DatabaseManager:
    """数据库管理器 - 升级版"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.db_path = Path(config.get('path', 'data/scrnaseq.db'))
        self.table_name = config.get('table_name', 'std')
        self.logger = logging.getLogger(__name__)
        self.conn = None
        
        # 配置优化参数
        self.enable_wal = config.get('enable_wal', True)
        self.cache_size = config.get('cache_size', 10000)
        
        # 字段类型定义 - 包含标准化字段
        self.field_types = {
            # 研究标识
            'project_id_primary': 'text',
            'project_id_secondary': 'text',
            'project_id_tertiary': 'text',
            'title': 'text',
            'summary': 'text',
            
            # 样本信息
            'sample_id_raw': 'text',
            'sample_id_matrix': 'text',
            'sample_type': 'text',
            'sample_type_standardized': 'text',
            'sample_uid': 'text',
            
            # 数据可用性
            'raw_exist': 'boolean',
            'raw_open': 'boolean',
            'matrix_exist': 'boolean',
            'matrix_open': 'boolean',
            'file_type': 'text',
            'open_status': 'text',
            'open_status_standardized': 'text',
            'data_tier': 'text',
            
            # 疾病和组织
            'disease_general': 'text',
            'disease': 'text',
            'disease_standardized': 'text',
            'disease_category': 'text',
            'tissue_location': 'text',
            'tissue_standardized': 'text',
            
            # 人口统计学
            'ethnicity': 'text',
            'ethnicity_standardized': 'text',
            'age': 'text',
            'age_numeric': 'real',
            'age_original_format': 'text',
            'sex': 'text',
            'sex_standardized': 'text',
            
            # 技术信息
            'sequencing_platform': 'text',
            'platform_standardized': 'text',
            'experiment_design': 'text',
            
            # 出版信息
            'pubmed': 'text',
            'citation_count': 'integer',
            'publication_date': 'date',
            'publication_date_parsed': 'date',
            
            # 数据库信息
            'source_database': 'text',
            'database_standardized': 'text',
            'access_link': 'text',
            'submission_date': 'date',
            'submission_date_parsed': 'date',
            'last_update_date': 'date',
            'last_update_date_parsed': 'date',
            
            # 联系信息
            'contact_name': 'text',
            'contact_email': 'text',
            'contact_institute': 'text',
            
            # 元数据质量
            'metadata_completeness': 'real',
            'metadata_quality_score': 'text',
            'is_duplicate': 'boolean',
            
            # 补充信息
            'supplementary_information': 'text'
        }
    
    def connect(self):
        """连接数据库"""
        try:
            # 启用多线程支持（check_same_thread=False）
            self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            
            # 性能优化设置
            if self.enable_wal:
                self.conn.execute("PRAGMA journal_mode=WAL")
            
            self.conn.execute(f"PRAGMA cache_size={self.cache_size}")
            self.conn.execute("PRAGMA temp_store=MEMORY")
            self.conn.execute("PRAGMA synchronous=NORMAL")
            
            self.logger.info(f"已连接到数据库: {self.db_path}")
            
        except Exception as e:
            self.logger.error(f"数据库连接失败: {e}")
            raise
    
    def close(self):
        """关闭连接"""
        if self.conn:
            self.conn.close()
            self.logger.info("数据库连接已关闭")
    
    def get_schema_info(self) -> Dict[str, List[str]]:
        """获取schema信息"""
        try:
            conn = self._get_connection()
            schema_info = {}
            
            # 分类字段 - 优先使用清洗后的字段
            categorical_fields = [
                # 清洗后的高质量字段（推荐优先使用）
                'disease_clean', 'tissue_clean', 'platform_clean',
                # 数据库和基本信息
                'source_database', 'sample_type', 'sex',
                # 原始字段（备用）
                'disease_general', 'tissue_location', 'sequencing_platform',
                # 其他字段
                'open_status', 'file_type'
            ]
            
            for field in categorical_fields:
                try:
                    query = f'SELECT DISTINCT "{field}" FROM {self.table_name} WHERE "{field}" IS NOT NULL AND "{field}" != "" ORDER BY "{field}"'
                    df = pd.read_sql_query(query, conn)
                    schema_info[field] = df[field].tolist()
                except Exception as e:
                    self.logger.warning(f"获取字段 {field} 失败: {e}")
                    schema_info[field] = []
            
            return schema_info
        except Exception as e:
            self.logger.error(f"获取schema信息失败: {e}")
            return {}
    
    def build_query(self, filters: Dict[str, Any]) -> Tuple[str, List]:
        """
        构建SQL查询
        
        支持的条件类型：
        - exact_match: 精确匹配 (field = value)
        - partial_match: 模糊匹配 (field LIKE '%value%')
        - boolean_match: 布尔匹配 (特殊处理NULL值)
        - range_match: 范围匹配 (field >= min AND field <= max)
        - or_match: 跨字段OR搜索 (field1 LIKE '%value%' OR field2 LIKE '%value%')
        """
        conditions = []
        params = []
        
        # 精确匹配
        if 'exact_match' in filters and filters['exact_match']:
            for field, value in filters['exact_match'].items():
                if value is not None and value != '':
                    conditions.append(f'"{field}" = ?')
                    params.append(value)
        
        # 部分匹配（单一字段）
        if 'partial_match' in filters and filters['partial_match']:
            for field, value in filters['partial_match'].items():
                if value is not None and value != '':
                    # 如果值包含空格，说明是多个搜索词，用OR连接
                    if ' ' in str(value) and len(str(value)) > 10:
                        # 分割搜索词，为每个词创建OR条件
                        terms = [t.strip() for t in str(value).split() if len(t.strip()) > 2]
                        # 限制最多5个词，避免参数过多
                        terms = terms[:5]
                        if len(terms) > 1:
                            or_conditions = [f'"{field}" LIKE ?' for _ in terms]
                            conditions.append(f'({" OR ".join(or_conditions)})')
                            params.extend([f'%{t}%' for t in terms])
                        elif len(terms) == 1:
                            conditions.append(f'"{field}" LIKE ?')
                            params.append(f'%{terms[0]}%')
                        else:
                            # 没有有效词，使用原值
                            conditions.append(f'"{field}" LIKE ?')
                            params.append(f'%{value}%')
                    else:
                        conditions.append(f'"{field}" LIKE ?')
                        params.append(f'%{value}%')
        
        # 布尔匹配
        if 'boolean_match' in filters and filters['boolean_match']:
            for field, value in filters['boolean_match'].items():
                if value is True:
                    # 对于true，匹配1/True/true，**也包含NULL**（因为数据库中很多布尔字段为NULL）
                    conditions.append(f'("{field}" = 1 OR "{field}" = "True" OR "{field}" = "true" OR "{field}" IS NULL)')
                elif value is False:
                    # 对于false，只匹配明确为0/False/false的值
                    conditions.append(f'("{field}" = 0 OR "{field}" = "False" OR "{field}" = "false")')
        
        # 范围匹配
        if 'range_match' in filters and filters['range_match']:
            for field, range_val in filters['range_match'].items():
                if isinstance(range_val, dict):
                    if 'min' in range_val and range_val['min'] is not None:
                        conditions.append(f'"{field}" >= ?')
                        params.append(range_val['min'])
                    if 'max' in range_val and range_val['max'] is not None:
                        conditions.append(f'"{field}" <= ?')
                        params.append(range_val['max'])
        
        # 跨字段OR搜索（新增）
        if 'or_match' in filters and filters['or_match']:
            for concept, or_config in filters['or_match'].items():
                fields = or_config.get('fields', [])
                value = or_config.get('value', '')
                
                if fields and value:
                    or_conditions = [f'"{field}" LIKE ?' for field in fields]
                    conditions.append(f'({" OR ".join(or_conditions)})')
                    params.extend([f'%{value}%'] * len(fields))
                    self.logger.debug(f"跨字段OR搜索: {concept} 在 {fields} 中搜索 '{value}'")
        
        # 构建完整查询
        if conditions:
            where_clause = ' AND '.join(conditions)
            query = f'SELECT * FROM {self.table_name} WHERE {where_clause}'
        else:
            query = f'SELECT * FROM {self.table_name}'
        
        self.logger.debug(f"生成SQL: {query}")
        self.logger.debug(f"参数: {params}")
        
        return query, params
    
    def _get_connection(self):
        """获取当前线程的数据库连接"""
        if not hasattr(thread_local, 'conn') or thread_local.conn is None:
            thread_local.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            # 性能优化
            thread_local.conn.execute(f"PRAGMA cache_size={self.cache_size}")
            thread_local.conn.execute("PRAGMA temp_store=MEMORY")
        return thread_local.conn
    
    def search(self, filters: Dict[str, Any], limit: int = 100, 
              offset: int = 0) -> pd.DataFrame:
        """执行搜索"""
        try:
            conn = self._get_connection()
            query, params = self.build_query(filters)
            
            # 添加排序和限制
            query += ' ORDER BY publication_date DESC, citation_count DESC'
            query += f' LIMIT {limit} OFFSET {offset}'
            
            results = pd.read_sql_query(query, conn, params=params)
            self.logger.info(f"查询返回 {len(results)} 条记录")
            
            return results
            
        except Exception as e:
            self.logger.error(f"查询失败: {e}")
            return pd.DataFrame()
    
    def count_results(self, filters: Dict[str, Any]) -> int:
        """统计结果数量"""
        try:
            conn = self._get_connection()
            query, params = self.build_query(filters)
            count_query = f'SELECT COUNT(*) as count FROM ({query})'
            
            result = pd.read_sql_query(count_query, conn, params=params)
            return int(result['count'].iloc[0])
            
        except Exception as e:
            self.logger.error(f"计数失败: {e}")
            return 0
    
    def get_field_statistics(self, field: str, 
                            filters: Optional[Dict[str, Any]] = None) -> pd.DataFrame:
        """获取字段统计"""
        try:
            conn = self._get_connection()
            if filters:
                base_query, params = self.build_query(filters)
                query = f'SELECT "{field}", COUNT(*) as count FROM ({base_query}) GROUP BY "{field}" ORDER BY count DESC'
            else:
                query = f'SELECT "{field}", COUNT(*) as count FROM {self.table_name} GROUP BY "{field}" ORDER BY count DESC'
                params = []
            
            return pd.read_sql_query(query, conn, params=params)
            
        except Exception as e:
            self.logger.error(f"统计失败: {e}")
            return pd.DataFrame()
    
    def get_all_data(self) -> pd.DataFrame:
        """获取所有数据"""
        try:
            conn = self._get_connection()
            return pd.read_sql_query(f'SELECT * FROM {self.table_name}', conn)
        except Exception as e:
            self.logger.error(f"获取数据失败: {e}")
            return pd.DataFrame()
    
    def add_field(self, field_name: str, field_type: str = 'TEXT'):
        """添加新字段"""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(f'ALTER TABLE {self.table_name} ADD COLUMN "{field_name}" {field_type}')
            conn.commit()
            self.logger.info(f"成功添加字段: {field_name}")
            
            # 更新字段类型定义
            self.field_types[field_name] = field_type.lower()
            
        except Exception as e:
            self.logger.error(f"添加字段失败: {e}")
            raise
    
    def update_field_values(self, field_name: str, updates: Dict[int, Any]):
        """批量更新字段值"""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            for rowid, value in updates.items():
                cursor.execute(
                    f'UPDATE {self.table_name} SET "{field_name}" = ? WHERE rowid = ?',
                    (value, rowid)
                )
            
            conn.commit()
            self.logger.info(f"成功更新 {len(updates)} 条记录的字段 {field_name}")
            
        except Exception as e:
            self.logger.error(f"更新失败: {e}")
            raise