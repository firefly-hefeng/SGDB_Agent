import json
import redis
import sqlite3
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from pathlib import Path
from collections import defaultdict

class MemorySystem:
    """
    三层记忆系统：工作记忆（短期）、情景记忆（中期）、语义记忆（长期）
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.logger = logging.getLogger(__name__)
        
        # 初始化三层记忆
        self.working_memory = WorkingMemory(config.get('memory', {}).get('working', {}))
        self.episodic_memory = EpisodicMemory(config.get('memory', {}).get('episodic', {}))
        self.semantic_memory = SemanticMemory(config.get('memory', {}).get('semantic', {}))
    
    def initialize(self):
        """初始化记忆系统"""
        self.working_memory.initialize()
        self.episodic_memory.initialize()
        self.semantic_memory.initialize()
        self.logger.info("记忆系统初始化完成")
    
    def cleanup(self):
        """清理资源"""
        self.working_memory.cleanup()
        self.episodic_memory.cleanup()
        self.semantic_memory.cleanup()


class WorkingMemory:
    """
    工作记忆（短期）- 管理当前会话状态
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.enabled = config.get('enabled', True)
        self.max_history = config.get('max_history', 10)
        self.session_timeout = config.get('session_timeout', 3600)
        
        # 内存存储当前会话
        self.sessions: Dict[str, Dict] = {}
    
    def initialize(self):
        """初始化"""
        if self.enabled:
            self.logger.info("工作记忆已启用")
    
    def create_session(self, session_id: str) -> Dict[str, Any]:
        """创建新会话"""
        session = {
            'session_id': session_id,
            'created_at': datetime.now(),
            'last_activity': datetime.now(),
            'conversation_history': [],
            'query_chain': [],
            'user_selections': [],
            'current_results': None,
            'context': {}
        }
        self.sessions[session_id] = session
        self.logger.info(f"创建新会话: {session_id}")
        return session
    
    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """获取会话"""
        if session_id not in self.sessions:
            return self.create_session(session_id)
        
        session = self.sessions[session_id]
        
        # 检查会话是否超时
        if (datetime.now() - session['last_activity']).seconds > self.session_timeout:
            self.logger.info(f"会话超时，创建新会话: {session_id}")
            return self.create_session(session_id)
        
        session['last_activity'] = datetime.now()
        return session
    
    def add_conversation_turn(self, session_id: str, user_query: str, 
                            system_response: Dict[str, Any]):
        """添加对话轮次"""
        session = self.get_session(session_id)
        
        turn = {
            'timestamp': datetime.now().isoformat(),
            'user_query': user_query,
            'system_response': system_response
        }
        
        session['conversation_history'].append(turn)
        
        # 限制历史长度
        if len(session['conversation_history']) > self.max_history:
            session['conversation_history'] = session['conversation_history'][-self.max_history:]
        
        self.logger.debug(f"添加对话轮次到会话 {session_id}")
    
    def add_query_to_chain(self, session_id: str, query: str, filters: Dict[str, Any]):
        """添加查询到查询链"""
        session = self.get_session(session_id)
        
        query_item = {
            'timestamp': datetime.now().isoformat(),
            'query': query,
            'filters': filters
        }
        
        session['query_chain'].append(query_item)
        self.logger.debug(f"添加查询到链: {query}")
    
    def add_user_selection(self, session_id: str, selected_items: List[Any]):
        """记录用户选择"""
        session = self.get_session(session_id)
        session['user_selections'].extend(selected_items)
        self.logger.debug(f"记录用户选择: {len(selected_items)} 项")
    
    def set_current_results(self, session_id: str, results: Any):
        """设置当前结果"""
        session = self.get_session(session_id)
        session['current_results'] = results
    
    def get_context(self, session_id: str) -> Dict[str, Any]:
        """获取上下文信息"""
        session = self.get_session(session_id)
        
        # 构建上下文
        context = {
            'recent_queries': [item['query'] for item in session['query_chain'][-3:]],
            'recent_filters': [item['filters'] for item in session['query_chain'][-3:]],
            'conversation_summary': self._summarize_conversation(session),
            'user_selections': session['user_selections'][-10:],
            'has_current_results': session['current_results'] is not None
        }
        
        return context
    
    def _summarize_conversation(self, session: Dict[str, Any]) -> str:
        """总结对话历史"""
        if not session['conversation_history']:
            return "新会话"
        
        queries = [turn['user_query'] for turn in session['conversation_history'][-3:]]
        return f"最近查询: {' → '.join(queries)}"
    
    def clear_session(self, session_id: str):
        """清空会话"""
        if session_id in self.sessions:
            del self.sessions[session_id]
            self.logger.info(f"清空会话: {session_id}")
    
    def cleanup(self):
        """清理过期会话"""
        now = datetime.now()
        expired = []
        
        for session_id, session in self.sessions.items():
            if (now - session['last_activity']).seconds > self.session_timeout:
                expired.append(session_id)
        
        for session_id in expired:
            del self.sessions[session_id]
        
        if expired:
            self.logger.info(f"清理 {len(expired)} 个过期会话")


class EpisodicMemory:
    """
    情景记忆（中期）- 存储用户偏好和查询模式
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.enabled = config.get('enabled', False)
        self.storage = config.get('storage', 'sqlite')
        self.db_path = config.get('db_path', 'data/episodic_memory.db')
        self.conn = None
    
    def initialize(self):
        """初始化存储"""
        if not self.enabled:
            self.logger.info("情景记忆未启用")
            return
        
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        
        # 创建表
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS user_profiles (
                user_id TEXT PRIMARY KEY,
                query_patterns TEXT,
                field_preferences TEXT,
                created_at TIMESTAMP,
                updated_at TIMESTAMP
            )
        ''')
        
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS session_history (
                session_id TEXT PRIMARY KEY,
                user_id TEXT,
                queries TEXT,
                results_count INTEGER,
                satisfaction TEXT,
                created_at TIMESTAMP
            )
        ''')
        
        self.conn.commit()
        self.logger.info("情景记忆初始化完成")
    
    def update_user_profile(self, user_id: str, query_pattern: Dict[str, Any]):
        """更新用户画像"""
        if not self.enabled or not self.conn:
            return
        
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT query_patterns FROM user_profiles WHERE user_id = ?
        ''', (user_id,))
        
        row = cursor.fetchone()
        
        if row:
            patterns = json.loads(row[0])
            # 合并新模式
            for key, value in query_pattern.items():
                patterns[key] = patterns.get(key, 0) + value
            
            cursor.execute('''
                UPDATE user_profiles 
                SET query_patterns = ?, updated_at = ?
                WHERE user_id = ?
            ''', (json.dumps(patterns), datetime.now(), user_id))
        else:
            cursor.execute('''
                INSERT INTO user_profiles (user_id, query_patterns, created_at, updated_at)
                VALUES (?, ?, ?, ?)
            ''', (user_id, json.dumps(query_pattern), datetime.now(), datetime.now()))
        
        self.conn.commit()
    
    def get_user_preferences(self, user_id: str) -> Dict[str, Any]:
        """获取用户偏好"""
        if not self.enabled or not self.conn:
            return {}
        
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT query_patterns, field_preferences FROM user_profiles WHERE user_id = ?
        ''', (user_id,))
        
        row = cursor.fetchone()
        if row:
            return {
                'query_patterns': json.loads(row[0]) if row[0] else {},
                'field_preferences': json.loads(row[1]) if row[1] else {}
            }
        
        return {}
    
    def save_session(self, session_id: str, user_id: str, 
                    session_data: Dict[str, Any]):
        """保存会话记录"""
        if not self.enabled or not self.conn:
            return
        
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO session_history 
            (session_id, user_id, queries, results_count, satisfaction, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            session_id,
            user_id,
            json.dumps(session_data.get('queries', [])),
            session_data.get('results_count', 0),
            session_data.get('satisfaction', 'unknown'),
            datetime.now()
        ))
        
        self.conn.commit()
    
    def cleanup(self):
        """清理资源"""
        if self.conn:
            self.conn.close()


class SemanticMemory:
    """
    语义记忆（长期）- 存储数据库Schema、查询模板、字段扩展历史
    增强版：存储字段的示例值和统计信息
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.enabled = config.get('enabled', True)
        self.db_path = config.get('db_path', 'data/semantic_memory.db')
        self.conn = None
        
        # Schema缓存配置
        self.schema_cache_ttl = config.get('schema_cache_ttl', 3600)  # 1小时
        self._schema_cache = None
        self._schema_cache_time = None
    
    def initialize(self):
        """初始化"""
        if not self.enabled:
            return
        
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        
        # 创建表
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS field_metadata (
                field_name TEXT PRIMARY KEY,
                field_type TEXT,
                definition TEXT,
                judgment_criteria TEXT,
                example_prompt TEXT,
                accuracy_rate REAL,
                usage_count INTEGER DEFAULT 0,
                created_by TEXT,
                created_at TIMESTAMP,
                last_used_at TIMESTAMP
            )
        ''')
        
        # 新增：字段示例值表
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS field_examples (
                field_name TEXT,
                example_value TEXT,
                value_count INTEGER,
                value_percentage REAL,
                last_updated TIMESTAMP,
                PRIMARY KEY (field_name, example_value),
                FOREIGN KEY (field_name) REFERENCES field_metadata(field_name)
            )
        ''')
        
        # 新增：字段统计信息表
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS field_statistics (
                field_name TEXT PRIMARY KEY,
                total_records INTEGER,
                unique_values INTEGER,
                null_count INTEGER,
                null_percentage REAL,
                most_common_value TEXT,
                last_updated TIMESTAMP,
                FOREIGN KEY (field_name) REFERENCES field_metadata(field_name)
            )
        ''')
        
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS query_templates (
                template_id TEXT PRIMARY KEY,
                template_text TEXT,
                filters TEXT,
                success_count INTEGER DEFAULT 0,
                avg_satisfaction REAL,
                created_at TIMESTAMP,
                last_used_at TIMESTAMP
            )
        ''')
        
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS field_expansion_history (
                expansion_id TEXT PRIMARY KEY,
                field_name TEXT,
                target_table TEXT,
                records_processed INTEGER,
                accuracy_rate REAL,
                cost_tokens INTEGER,
                execution_time REAL,
                created_at TIMESTAMP,
                FOREIGN KEY (field_name) REFERENCES field_metadata(field_name)
            )
        ''')
        
        self.conn.commit()
        self.logger.info("语义记忆初始化完成")
    
    def save_field_metadata(self, field_data: Dict[str, Any]):
        """保存字段元数据"""
        if not self.enabled or not self.conn:
            return
        
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO field_metadata
            (field_name, field_type, definition, judgment_criteria, 
             example_prompt, accuracy_rate, created_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            field_data['field_name'],
            field_data.get('field_type', 'TEXT'),
            field_data.get('definition', ''),
            field_data.get('judgment_criteria', ''),
            field_data.get('example_prompt', ''),
            field_data.get('accuracy_rate', 0.0),
            field_data.get('created_by', 'system'),
            datetime.now()
        ))
        
        self.conn.commit()
        self.logger.info(f"保存字段元数据: {field_data['field_name']}")
    
    def save_field_examples(self, field_name: str, examples: List[Dict[str, Any]]):
        """
        保存字段示例值
        
        Args:
            field_name: 字段名
            examples: 示例值列表，每个元素包含 {'value': str, 'count': int, 'percentage': float}
        """
        if not self.enabled or not self.conn:
            return
        
        cursor = self.conn.cursor()
        
        # 删除旧的示例值
        cursor.execute('DELETE FROM field_examples WHERE field_name = ?', (field_name,))
        
        # 插入新的示例值
        now = datetime.now()
        for example in examples:
            cursor.execute('''
                INSERT INTO field_examples
                (field_name, example_value, value_count, value_percentage, last_updated)
                VALUES (?, ?, ?, ?, ?)
            ''', (
                field_name,
                example['value'],
                example['count'],
                example.get('percentage', 0.0),
                now
            ))
        
        self.conn.commit()
        self.logger.debug(f"保存 {len(examples)} 个字段示例: {field_name}")
    
    def save_field_statistics(self, field_name: str, stats: Dict[str, Any]):
        """
        保存字段统计信息
        
        Args:
            field_name: 字段名
            stats: 统计信息，包含 total_records, unique_values, null_count 等
        """
        if not self.enabled or not self.conn:
            return
        
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO field_statistics
            (field_name, total_records, unique_values, null_count, null_percentage,
             most_common_value, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            field_name,
            stats.get('total_records', 0),
            stats.get('unique_values', 0),
            stats.get('null_count', 0),
            stats.get('null_percentage', 0.0),
            stats.get('most_common_value', ''),
            datetime.now()
        ))
        
        self.conn.commit()
        self.logger.debug(f"保存字段统计信息: {field_name}")
    
    def get_field_metadata(self, field_name: str) -> Optional[Dict[str, Any]]:
        """获取字段元数据"""
        if not self.enabled or not self.conn:
            return None
        
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT * FROM field_metadata WHERE field_name = ?
        ''', (field_name,))
        
        row = cursor.fetchone()
        if row:
            columns = [desc[0] for desc in cursor.description]
            return dict(zip(columns, row))
        
        return None
    
    def get_field_examples(self, field_name: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        获取字段示例值
        
        Args:
            field_name: 字段名
            limit: 返回的示例数量
        
        Returns:
            示例值列表
        """
        if not self.enabled or not self.conn:
            return []
        
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT example_value, value_count, value_percentage
            FROM field_examples
            WHERE field_name = ?
            ORDER BY value_count DESC
            LIMIT ?
        ''', (field_name, limit))
        
        rows = cursor.fetchall()
        return [
            {
                'value': row[0],
                'count': row[1],
                'percentage': row[2]
            }
            for row in rows
        ]
    
    def get_field_statistics(self, field_name: str) -> Optional[Dict[str, Any]]:
        """获取字段统计信息"""
        if not self.enabled or not self.conn:
            return None
        
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT * FROM field_statistics WHERE field_name = ?
        ''', (field_name,))
        
        row = cursor.fetchone()
        if row:
            columns = [desc[0] for desc in cursor.description]
            return dict(zip(columns, row))
        
        return None
    
    def get_enhanced_schema(self, field_names: List[str] = None) -> Dict[str, Any]:
        """
        获取增强的Schema信息（包含示例值和统计）
        
        Args:
            field_names: 要获取的字段列表，None表示获取所有字段
        
        Returns:
            增强的Schema字典
        """
        if not self.enabled or not self.conn:
            return {}
        
        # 检查缓存
        if self._schema_cache and self._schema_cache_time:
            age = (datetime.now() - self._schema_cache_time).total_seconds()
            if age < self.schema_cache_ttl:
                self.logger.debug("使用Schema缓存")
                if field_names:
                    return {k: v for k, v in self._schema_cache.items() if k in field_names}
                return self._schema_cache
        
        schema = {}
        cursor = self.conn.cursor()
        
        # 构建查询条件
        if field_names:
            placeholders = ','.join(['?'] * len(field_names))
            where_clause = f'WHERE fm.field_name IN ({placeholders})'
            params = field_names
        else:
            where_clause = ''
            params = []
        
        # 获取字段元数据、示例和统计
        query = f'''
            SELECT 
                fm.field_name,
                fm.field_type,
                fm.definition,
                fs.total_records,
                fs.unique_values,
                fs.null_percentage,
                fs.most_common_value
            FROM field_metadata fm
            LEFT JOIN field_statistics fs ON fm.field_name = fs.field_name
            {where_clause}
        '''
        
        cursor.execute(query, params)
        
        for row in cursor.fetchall():
            field_name = row[0]
            
            # 获取该字段的示例值
            examples = self.get_field_examples(field_name, limit=10)
            
            schema[field_name] = {
                'field_type': row[1] or 'TEXT',
                'definition': row[2] or '',
                'total_records': row[3] or 0,
                'unique_values': row[4] or 0,
                'null_percentage': row[5] or 0.0,
                'most_common_value': row[6] or '',
                'examples': examples
            }
        
        # 更新缓存
        if not field_names:  # 只有获取全部字段时才缓存
            self._schema_cache = schema
            self._schema_cache_time = datetime.now()
        
        return schema
    
    def invalidate_schema_cache(self):
        """使Schema缓存失效"""
        self._schema_cache = None
        self._schema_cache_time = None
        self.logger.debug("Schema缓存已失效")
    
    def increment_field_usage(self, field_name: str):
        """增加字段使用次数"""
        if not self.enabled or not self.conn:
            return
        
        cursor = self.conn.cursor()
        cursor.execute('''
            UPDATE field_metadata 
            SET usage_count = usage_count + 1, last_used_at = ?
            WHERE field_name = ?
        ''', (datetime.now(), field_name))
        
        self.conn.commit()
    
    def save_query_template(self, template_data: Dict[str, Any]):
        """保存成功的查询模板"""
        if not self.enabled or not self.conn:
            return
        
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO query_templates
            (template_id, template_text, filters, created_at)
            VALUES (?, ?, ?, ?)
        ''', (
            template_data['template_id'],
            template_data['template_text'],
            json.dumps(template_data.get('filters', {})),
            datetime.now()
        ))
        
        self.conn.commit()
    
    def get_similar_templates(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """获取相似的查询模板"""
        if not self.enabled or not self.conn:
            return []
        
        # 简单的关键词匹配（实际应用中可以用向量相似度）
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT * FROM query_templates 
            WHERE template_text LIKE ?
            ORDER BY success_count DESC, last_used_at DESC
            LIMIT ?
        ''', (f'%{query}%', limit))
        
        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]
        
        return [dict(zip(columns, row)) for row in rows]
    
    def save_expansion_history(self, expansion_data: Dict[str, Any]):
        """保存字段扩展历史"""
        if not self.enabled or not self.conn:
            return
        
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT INTO field_expansion_history
            (expansion_id, field_name, target_table, records_processed,
             accuracy_rate, cost_tokens, execution_time, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            expansion_data['expansion_id'],
            expansion_data['field_name'],
            expansion_data.get('target_table', 'std'),
            expansion_data.get('records_processed', 0),
            expansion_data.get('accuracy_rate', 0.0),
            expansion_data.get('cost_tokens', 0),
            expansion_data.get('execution_time', 0.0),
            datetime.now()
        ))
        
        self.conn.commit()
    
    def get_expansion_history(self, field_name: str) -> List[Dict[str, Any]]:
        """获取字段扩展历史"""
        if not self.enabled or not self.conn:
            return []
        
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT * FROM field_expansion_history 
            WHERE field_name = ?
            ORDER BY created_at DESC
        ''', (field_name,))
        
        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]
        
        return [dict(zip(columns, row)) for row in rows]
    
    def cleanup(self):
        """清理资源"""
        if self.conn:
            self.conn.close()