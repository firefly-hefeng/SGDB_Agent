import pandas as pd
import os
import sys
import argparse
import logging
import uuid
from pathlib import Path
from typing import Optional, Dict, List, Any

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.config_manager import ConfigManager
from src.query_engine import QueryEngine

class CLI:
    """命令行界面 - 升级版"""
    
    def __init__(self, config_path: str = "config/config.yaml"):
        self.config = ConfigManager(config_path)
        self.setup_logging()
        
        # 初始化查询引擎
        self.query_engine = QueryEngine(self.config)
        self.query_engine.initialize()
        
        self.logger = logging.getLogger(__name__)
        
        # 当前会话ID
        self.current_session_id = str(uuid.uuid4())
    
    def setup_logging(self):
        """配置日志"""
        log_config = self.config.get('logging', {})
        log_level = getattr(logging, log_config.get('level', 'INFO'))
        log_file = log_config.get('file', 'logs/scdb_agent.log')
        log_format = log_config.get('format', '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        
        logging.basicConfig(
            level=log_level,
            format=log_format,
            handlers=[
                logging.FileHandler(log_file, encoding='utf-8'),
                logging.StreamHandler()
            ]
        )
    
    def search(self, query: str, limit: int = 20, export: Optional[str] = None,
              new_session: bool = False):
        """执行搜索"""
        if new_session:
            self.current_session_id = str(uuid.uuid4())
            print(f"\n🔄 开始新会话: {self.current_session_id[:8]}")
        
        self.logger.info(f"开始处理查询: {query}")
        
        print(f"\n🔍 正在分析查询: {query}")
        print("=" * 80)
        
        # 显示会话上下文
        context = self.query_engine.get_session_context(self.current_session_id)
        if context['recent_queries']:
            print(f"\n📜 对话历史: {' → '.join(context['recent_queries'])}")
        
        # 执行查询
        result = self.query_engine.execute_query(
            query, 
            session_id=self.current_session_id,
            limit=limit
        )
        
        # 显示查询信息
        print(f"\n📋 查询意图: {result.get('intent', query)}")
        
        if result.get('query_type'):
            print(f"🔖 查询类型: {result['query_type']}")
        
        if result.get('keywords'):
            print(f"🔑 关键词: {', '.join(result['keywords'])}")
        
        # 显示过滤条件
        if result.get('filters'):
            self._display_filters(result['filters'])
        
        # 显示统计信息
        if result.get('query_type') == 'aggregation':
            self._display_statistics(result)
        else:
            # 显示查询结果
            print(f"\n✅ 找到 {result['total_count']} 条匹配记录，显示前 {result['returned_count']} 条")
            print(f"⏱️  查询耗时: {result['execution_time']:.2f} 秒")
            
            self.display_results(result['results'], result.get('explanation', ''))
        
        # 显示字段扩展建议
        if result.get('field_expansion_suggestion'):
            self._display_field_expansion_suggestion(result['field_expansion_suggestion'])
        
        # 显示相关查询建议
        if result.get('suggestions'):
            print("\n💭 相关查询建议:")
            for i, suggestion in enumerate(result['suggestions'], 1):
                print(f"  {i}. {suggestion}")
        
        # 导出结果
        if export and 'results' in result and not result['results'].empty:
            if self.query_engine.export_results(result['results'], export):
                print(f"\n✅ 结果已导出到: {export}")
            else:
                print(f"\n❌ 导出失败")
        
        return result
    
    def _display_filters(self, filters: Dict[str, Any]):
        """显示过滤条件"""
        print("\n🎯 应用的过滤条件:")
        
        has_filters = False
        for match_type, conditions in filters.items():
            if conditions:
                has_filters = True
                type_name = {
                    'exact_match': '精确匹配',
                    'partial_match': '模糊匹配',
                    'boolean_match': '布尔匹配',
                    'range_match': '范围匹配'
                }.get(match_type, match_type)
                
                print(f"\n  {type_name}:")
                for field, value in conditions.items():
                    if isinstance(value, dict):
                        print(f"    - {field}: {value}")
                    else:
                        print(f"    - {field}: {value}")
        
        if not has_filters:
            print("  (无特定过滤条件，返回所有记录)")
    
    def _display_statistics(self, result: Dict[str, Any]):
        """显示统计信息"""
        print(f"\n📊 字段 '{result['aggregation_field']}' 的统计信息:")
        
        stats = result.get('statistics')
        if stats is None or stats.empty:
            print("  ❌ 未找到该字段或字段为空")
            return
        
        print("\n" + "─" * 70)
        for idx, row in stats.iterrows():
            field_name = result['aggregation_field']
            value = row[field_name] if pd.notna(row[field_name]) else '(空)'
            count = row['count']
            
            # 计算百分比
            total = stats['count'].sum()
            percentage = (count / total * 100) if total > 0 else 0
            
            # 可视化条形图
            bar_length = int(count / stats['count'].max() * 40)
            bar = '█' * bar_length
            
            print(f"  {value:.<30} {count:>6} ({percentage:>5.1f}%) {bar}")
        
        print("─" * 70)
        print(f"  总计: {len(stats)} 个不同的值, {stats['count'].sum()} 条记录")
    
    def _display_field_expansion_suggestion(self, suggestion: Dict[str, Any]):
        """显示字段扩展建议"""
        print("\n" + "=" * 80)
        print("💡 字段扩展建议")
        print("=" * 80)
        print(f"\n{suggestion['reason']}\n")
        print("你可以使用 'expand' 命令创建新的筛选字段来精确定位数据。")
        print("\n示例命令: expand \"is_immunotherapy_relevant\" \"与免疫治疗相关的数据\"")
        print("=" * 80)
    
    def display_results(self, results: pd.DataFrame, explanation: str = ""):
        """显示查询结果"""
        if results.empty:
            print("\n❌ 未找到匹配的数据集")
            return
        
        print("\n" + "=" * 80)
        print("📊 结果摘要")
        print("=" * 80)
        if explanation:
            print(explanation)
        
        print("\n" + "=" * 80)
        print("📄 详细结果")
        print("=" * 80)
        
        # 选择显示字段（优先使用标准化字段）
        display_fields = [
            'title', 'disease_standardized', 'disease_category', 'tissue_standardized', 
            'sample_type_standardized', 'platform_standardized', 'database_standardized', 
            'matrix_open', 'citation_count', 'publication_date', 'sample_uid'
        ]
        
        available_fields = [f for f in display_fields if f in results.columns]
        
        for idx, row in results.iterrows():
            print(f"\n[{idx + 1}] " + "─" * 75)
            for field in available_fields:
                value = row[field]
                if pd.notna(value) and value != '':
                    field_display = field.replace('_', ' ').title()
                    
                    # 截断过长内容
                    if isinstance(value, str) and len(value) > 100:
                        value = value[:97] + "..."
                    
                    # 布尔值显示
                    if isinstance(value, (bool, int)) and field in ['matrix_open', 'raw_open']:
                        value = '✅ 是' if value else '❌ 否'
                    
                    print(f"  {field_display:.<30} {value}")
        
        print("\n" + "=" * 80)
    
    def expand_field(self, field_name: str, definition: str, 
                    criteria: Optional[str] = None):
        """扩展字段"""
        print(f"\n🔧 开始字段扩展: {field_name}")
        print("=" * 80)
        
        # 获取当前会话的查询结果
        context = self.query_engine.get_session_context(self.current_session_id)
        
        if not context.get('has_current_results'):
            print("❌ 没有可用的查询结果。请先执行查询。")
            return
        
        # 构建字段定义
        field_definition = {
            'field_name': field_name,
            'field_type': 'BOOLEAN',  # 默认布尔型
            'definition': definition,
            'judgment_criteria': criteria or definition
        }
        
        print(f"\n字段名称: {field_name}")
        print(f"字段定义: {definition}")
        print(f"判断标准: {field_definition['judgment_criteria']}")
        
        # 确认
        confirm = input("\n是否继续？(y/n): ").strip().lower()
        if confirm != 'y':
            print("已取消")
            return
        
        # 获取当前查询的过滤条件
        session = self.query_engine.memory_system.working_memory.get_session(
            self.current_session_id
        )
        
        last_query = session['query_chain'][-1] if session['query_chain'] else None
        filters = last_query['filters'] if last_query else {}
        
        print("\n⏳ 正在扩展字段...")
        print("  步骤1: 采样验证...")
        
        # 执行字段扩展
        result = self.query_engine.expand_field_for_query(
            field_definition,
            filters
        )
        
        if result['status'] == 'completed':
            print(f"\n✅ 字段扩展完成！")
            print(f"  处理记录数: {result['records_processed']}")
            print(f"  准确率: {result.get('accuracy_rate', 0):.2%}")
            print(f"  耗时: {result['execution_time']:.2f} 秒")
            
            if result.get('manual_review_items'):
                print(f"\n⚠️  有 {len(result['manual_review_items'])} 条记录需要人工审核")
            
            # 重新执行查询以查看效果
            print("\n正在使用新字段重新查询...")
            filters['boolean_match'][field_name] = True
            
            new_results = self.query_engine.db_manager.search(filters, limit=20)
            print(f"\n使用新字段后，找到 {len(new_results)} 条匹配记录")
            
        else:
            print(f"\n❌ 字段扩展失败: {result.get('error', '未知错误')}")
            if result.get('errors'):
                for error in result['errors']:
                    print(f"  - {error}")
    
    def show_statistics(self, field: str, filters: Optional[Dict] = None):
        """显示字段统计"""
        print(f"\n📊 字段 '{field}' 的统计信息:")
        stats = self.query_engine.get_statistics(field, filters)
        
        if stats.empty:
            print("  ❌ 未找到该字段或字段为空")
            return
        
        print("\n" + "─" * 70)
        for idx, row in stats.iterrows():
            value = row[field] if pd.notna(row[field]) else '(空)'
            count = row['count']
            
            # 百分比
            total = stats['count'].sum()
            percentage = (count / total * 100) if total > 0 else 0
            
            bar_length = int(count / stats['count'].max() * 40)
            bar = '█' * bar_length
            
            print(f"  {value:.<30} {count:>6} ({percentage:>5.1f}%) {bar}")
        
        print("─" * 70)
        print(f"  总计: {len(stats)} 个不同的值")
    
    def interactive_mode(self):
        """交互式模式"""
        print("\n" + "=" * 80)
        print(" 🧬 单细胞RNA-seq数据库智能检索系统 v2.0")
        print("=" * 80)
        
        print("\n✨ 新特性：")
        print("  • 智能多轮对话 - 支持连续精化查询")
        print("  • 动态字段扩展 - AI驱动的自定义筛选")
        print("  • 三层记忆系统 - 更智能的上下文理解")
        
        print("\n💡 示例查询：")
        print("  - 查找肺癌相关的10x Genomics数据")
        print("  - 只要人类的（连续查询）")
        print("  - 限制在免疫细胞（进一步精化）")
        print("  - 统计疾病分布（聚合查询）")
        
        print("\n🔧 命令：")
        print("  search <查询>        - 搜索数据")
        print("  stats <字段>         - 查看字段统计")
        print("  expand <字段> <定义> - 扩展新字段")
        print("  export <路径>        - 导出最近结果")
        print("  download             - 下载当前结果的数据文件")
        print("  download-preview     - 预览可下载的数据")
        print("  download-script      - 生成下载脚本")
        print("  context              - 查看当前上下文")
        print("  new                  - 开始新会话")
        print("  fields               - 查看所有字段")
        print("  help                 - 查看帮助")
        print("  quit/exit            - 退出")
        
        print("=" * 80)
        print(f"\n当前会话: {self.current_session_id[:8]}")
        
        while True:
            try:
                user_input = input("\n🔍 > ").strip()
                
                if not user_input:
                    continue
                
                # 解析命令
                parts = user_input.split(maxsplit=1)
                command = parts[0].lower()
                args = parts[1] if len(parts) > 1 else ""
                
                if command in ['quit', 'exit', 'q']:
                    print("\n再见！👋")
                    break
                
                elif command == 'help':
                    self.show_help()
                
                elif command == 'fields':
                    self.show_fields()
                
                elif command == 'new':
                    self.current_session_id = str(uuid.uuid4())
                    self.query_engine.clear_session(self.current_session_id)
                    print(f"\n🔄 已开始新会话: {self.current_session_id[:8]}")
                
                elif command == 'context':
                    self.show_context()
                
                elif command == 'search':
                    if args:
                        self.search(args)
                    else:
                        print("请提供查询内容")
                
                elif command == 'stats':
                    if args:
                        self.show_statistics(args)
                    else:
                        print("请指定字段名")
                
                elif command == 'expand':
                    # 解析字段名和定义
                    if '"' in args:
                        import re
                        matches = re.findall(r'"([^"]+)"', args)
                        if len(matches) >= 2:
                            self.expand_field(matches[0], matches[1])
                        else:
                            print("格式: expand \"字段名\" \"定义\"")
                    else:
                        print("格式: expand \"字段名\" \"定义\"")
                
                elif command == 'export':
                    session = self.query_engine.memory_system.working_memory.get_session(
                        self.current_session_id
                    )
                    
                    if session and session.get('current_results') is not None:
                        filepath = args or f"results/export_{self.current_session_id[:8]}.csv"
                        if self.query_engine.export_results(session['current_results'], filepath):
                            print(f"✅ 结果已导出到: {filepath}")
                        else:
                            print("❌ 导出失败")
                    else:
                        print("❌ 没有可导出的结果")
                
                elif command == 'download':
                    self.handle_download(args)
                
                elif command == 'download-preview':
                    self.handle_download_preview()
                
                elif command == 'download-script':
                    self.handle_download_script(args)
                
                else:
                    # 默认作为搜索查询
                    self.search(user_input)
                
            except KeyboardInterrupt:
                print("\n\n再见！👋")
                break
            except Exception as e:
                print(f"\n❌ 发生错误: {e}")
                self.logger.error(f"交互模式错误: {e}", exc_info=True)
    
    def show_context(self):
        """显示当前上下文"""
        context = self.query_engine.get_session_context(self.current_session_id)
        
        print("\n" + "=" * 80)
        print("📋 当前会话上下文")
        print("=" * 80)
        
        print(f"\n会话ID: {self.current_session_id}")
        
        if context['recent_queries']:
            print(f"\n最近查询:")
            for i, query in enumerate(context['recent_queries'], 1):
                print(f"  {i}. {query}")
        else:
            print("\n最近查询: (无)")
        
        print(f"\n对话摘要: {context['conversation_summary']}")
        
        print(f"\n当前结果: {'有' if context['has_current_results'] else '无'}")
        
        if context['user_selections']:
            print(f"\n用户选择: {len(context['user_selections'])} 项")
        
        print("=" * 80)
    
    def show_fields(self):
        """显示所有可用字段"""
        fields = self.query_engine.db_manager.field_types.keys()
        
        print("\n📋 可用字段列表:")
        print("=" * 80)
        
        field_categories = {
            '研究标识': ['project_id_primary', 'project_id_secondary', 'project_id_tertiary', 'title', 'summary', 'sample_uid'],
            '样本信息': ['sample_id_raw', 'sample_id_matrix', 'sample_type', 'sample_type_standardized'],
            '数据可用性': ['raw_exist', 'raw_open', 'matrix_exist', 'matrix_open', 'file_type', 
                         'open_status', 'open_status_standardized', 'data_tier'],
            '疾病和组织(标准化)': ['disease_standardized', 'disease_category', 'tissue_standardized'],
            '疾病和组织(原始)': ['disease_general', 'disease', 'tissue_location'],
            '人口统计(标准化)': ['ethnicity_standardized', 'age_numeric', 'sex_standardized'],
            '人口统计(原始)': ['ethnicity', 'age', 'age_original_format', 'sex'],
            '技术信息(标准化)': ['platform_standardized'],
            '技术信息(原始)': ['sequencing_platform', 'experiment_design'],
            '出版信息': ['pubmed', 'citation_count', 'publication_date', 'publication_date_parsed'],
            '数据库信息(标准化)': ['database_standardized'],
            '数据库信息(原始)': ['source_database', 'access_link', 'submission_date', 'submission_date_parsed', 
                             'last_update_date', 'last_update_date_parsed'],
            '联系信息': ['contact_name', 'contact_email', 'contact_institute'],
            '元数据质量': ['metadata_completeness', 'metadata_quality_score', 'is_duplicate'],
            '补充信息': ['supplementary_information']
        }
        
        for category, field_list in field_categories.items():
            print(f"\n{category}:")
            for field in field_list:
                if field in fields:
                    print(f"  • {field}")
        
        print("\n" + "=" * 80)
    
    def show_help(self):
        """显示帮助"""
        help_text = """
╔════════════════════════════════════════════════════════════════════════════╗
║                           帮助文档 v2.0                                     ║
╚════════════════════════════════════════════════════════════════════════════╝

【查询示例】

1. 简单查询:
   search 查找肺癌相关数据
   search COVID-19的单细胞测序研究

2. 连续精化:
   search 查找癌症数据
   只要肺癌的
   限制在10x平台
   还要开放下载的

3. 统计分析:
   stats disease_general
   stats sequencing_platform

4. 字段扩展:
   expand "is_immunotherapy_relevant" "与免疫治疗相关的研究"

【命令列表】

  search <查询>        - 执行搜索查询
  stats <字段>         - 查看字段统计分布
  expand <字段> <定义> - 创建新的筛选字段
  export <路径>        - 导出当前结果
  download             - 下载当前结果的数据文件
  download-preview     - 预览可下载的数据
  download-script      - 生成批量下载脚本
  context              - 查看会话上下文
  new                  - 开始新会话
  fields               - 列出所有可用字段
  help                 - 显示此帮助
  quit/exit            - 退出程序

【高级特性】

• 多轮对话: 系统会记住你的查询历史，支持"只要"、"再"等连续查询
• 智能理解: AI会理解你的意图，自动匹配最合适的字段
• 动态扩展: 当现有字段不够用时，可以创建新字段来精确筛选

╚════════════════════════════════════════════════════════════════════════════╝
"""
        print(help_text)
    
    def cleanup(self):
        """清理资源"""
        if self.query_engine:
            self.query_engine.cleanup()
    
    # ==================== 数据下载命令 ====================
    
    def handle_download_preview(self):
        """处理下载预览命令"""
        session = self.query_engine.memory_system.working_memory.get_session(
            self.current_session_id
        )
        
        if not session or session.get('current_results') is None:
            print("❌ 没有可用的查询结果。请先执行查询。")
            return
        
        results = session['current_results']
        preview = self.query_engine.get_download_preview(results)
        
        print("\n" + "=" * 80)
        print("📦 数据下载预览")
        print("=" * 80)
        
        print(f"\n总计记录数: {preview['total_records']}")
        
        # 数据库分布
        if preview['database_distribution']:
            print("\n数据库分布:")
            for db, count in preview['database_distribution'].items():
                print(f"  • {db}: {count} 条")
        
        # 文件类型分布
        if preview['file_type_distribution']:
            print("\n文件类型分布:")
            for ft, count in preview['file_type_distribution'].items():
                print(f"  • {ft}: {count} 条")
        
        # 预览记录
        print(f"\n前 {len(preview['preview_records'])} 条记录预览:")
        print("-" * 80)
        
        for i, record in enumerate(preview['preview_records'], 1):
            print(f"\n[{i}] {record['project_id']} ({record['database']})")
            print(f"    标题: {record['title']}")
            print(f"    文件类型: {record['file_type']}")
            if record['access_link']:
                print(f"    访问链接: {record['access_link'][:60]}...")
        
        print("\n" + "=" * 80)
        print(f"提示: 使用 'download' 命令开始下载")
        print("      使用 'download-script' 命令生成批量下载脚本")
        print("=" * 80)
    
    def handle_download(self, args: str):
        """处理下载命令"""
        session = self.query_engine.memory_system.working_memory.get_session(
            self.current_session_id
        )
        
        if not session or session.get('current_results') is None:
            print("❌ 没有可用的查询结果。请先执行查询。")
            return
        
        results = session['current_results']
        
        # 限制下载数量
        max_download = 10
        if len(results) > max_download:
            print(f"⚠️  当前结果包含 {len(results)} 条记录，出于安全和效率考虑，")
            print(f"   将只下载前 {max_download} 条的数据。")
            print(f"   如需下载更多，请使用 'download-script' 生成批量脚本。")
            results = results.head(max_download)
        
        # 解析参数
        file_types = ['matrix']  # 默认下载表达矩阵
        output_dir = None
        generate_script = False
        
        if args:
            parts = args.split()
            if '--raw' in parts:
                file_types.append('raw')
            if '--metadata' in parts:
                file_types.append('metadata')
            if '--script' in parts:
                generate_script = True
            if '--output' in parts:
                idx = parts.index('--output')
                if idx + 1 < len(parts):
                    output_dir = parts[idx + 1]
        
        print("\n" + "=" * 80)
        print("⬇️  开始数据下载")
        print("=" * 80)
        print(f"文件类型: {', '.join(file_types)}")
        print(f"记录数量: {len(results)}")
        print(f"输出目录: {output_dir or 'data/downloads'}")
        if generate_script:
            print("同时生成: 下载脚本")
        print("")
        
        # 确认下载
        confirm = input("确认开始下载? (y/n): ").strip().lower()
        if confirm != 'y':
            print("已取消下载")
            return
        
        # 进度回调
        def progress_callback(task_id: str, progress: float, speed: float):
            speed_mb = speed / (1024 * 1024)
            print(f"\r  [{task_id[:8]}] {progress:.1f}% @ {speed_mb:.2f} MB/s", end='', flush=True)
        
        try:
            # 执行下载
            result = self.query_engine.download_data(
                results,
                file_types=file_types,
                output_dir=output_dir,
                progress_callback=progress_callback,
                generate_script=generate_script
            )
            
            print("\n\n" + "=" * 80)
            print("✅ 下载完成")
            print("=" * 80)
            
            if result['stats']:
                stats = result['stats']
                print(f"\n总任务数: {stats['total']}")
                print(f"成功: {stats['completed']}")
                print(f"失败: {stats['failed']}")
            
            if result['list_path']:
                print(f"\n下载列表: {result['list_path']}")
            
            if result['script_path']:
                print(f"下载脚本: {result['script_path']}")
                print("\n你可以使用以下命令执行批量下载:")
                print(f"  bash {result['script_path']}")
            
            print("=" * 80)
            
        except Exception as e:
            print(f"\n\n❌ 下载失败: {e}")
            self.logger.error(f"下载错误: {e}", exc_info=True)
    
    def handle_download_script(self, args: str):
        """处理下载脚本生成命令"""
        session = self.query_engine.memory_system.working_memory.get_session(
            self.current_session_id
        )
        
        if not session or session.get('current_results') is None:
            print("❌ 没有可用的查询结果。请先执行查询。")
            return
        
        results = session['current_results']
        
        # 解析输出路径
        output_path = args.strip() if args else None
        
        print("\n" + "=" * 80)
        print("📝 生成批量下载脚本")
        print("=" * 80)
        print(f"记录数量: {len(results)}")
        
        try:
            script_path = self.query_engine.generate_download_script(
                results,
                output_path=output_path
            )
            
            print(f"\n✅ 脚本已生成: {script_path}")
            print(f"\n使用方法:")
            print(f"  1. 查看脚本内容: cat {script_path}")
            print(f"  2. 执行下载: bash {script_path}")
            print(f"  3. 后台执行: nohup bash {script_path} > download.log 2>&1 &")
            
            print("\n提示:")
            print("  • 脚本支持断点续传（使用wget -c）")
            print("  • 建议先在测试环境验证脚本")
            print("  • 大量数据下载建议使用后台运行")
            
            print("=" * 80)
            
        except Exception as e:
            print(f"\n❌ 脚本生成失败: {e}")
            self.logger.error(f"脚本生成错误: {e}", exc_info=True)


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description='单细胞RNA-seq数据库智能检索系统 v2.0',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例用法:
  # 交互式模式
  python run.py
  
  # 直接查询
  python run.py -q "查找肺癌相关的10x Genomics数据"
  
  # 查询并导出
  python run.py -q "COVID-19血液样本数据" -o results.xlsx
  
  # 新会话查询
  python run.py -q "脑组织单细胞数据" --new-session
        """
    )
    
    parser.add_argument('-q', '--query', type=str, help='查询语句')
    parser.add_argument('-l', '--limit', type=int, default=20, help='返回结果数量（默认20）')
    parser.add_argument('-o', '--output', type=str, help='导出结果文件路径')
    parser.add_argument('-c', '--config', type=str, default='config/config.yaml', help='配置文件路径')
    parser.add_argument('--new-session', action='store_true', help='开始新会话')
    
    args = parser.parse_args()
    
    cli = None
    try:
        cli = CLI(config_path=args.config)
        
        if args.query:
            # 命令行模式
            cli.search(args.query, limit=args.limit, export=args.output, 
                      new_session=args.new_session)
        else:
            # 交互式模式
            cli.interactive_mode()
            
    except Exception as e:
        print(f"\n❌ 程序错误: {e}")
        logging.error(f"程序错误: {e}", exc_info=True)
        sys.exit(1)
    finally:
        if cli:
            cli.cleanup()


if __name__ == '__main__':
    main()