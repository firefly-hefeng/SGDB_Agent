"""
增强版CLI - 数据感知的交互界面
"""

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
from src.enhanced_query_engine import EnhancedQueryEngine


class EnhancedCLI:
    """增强版命令行界面"""
    
    def __init__(self, config_path: str = "config/config.yaml"):
        self.config = ConfigManager(config_path)
        self.setup_logging()
        
        # 初始化增强版查询引擎
        self.query_engine = EnhancedQueryEngine(self.config)
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
               adaptive: bool = True, analyze: bool = False):
        """执行搜索（增强版）"""
        self.logger.info(f"开始处理查询: {query}")
        
        print(f"\n🔍 正在分析查询: {query}")
        print("=" * 80)
        
        # 显示会话上下文
        context = self.query_engine.get_session_context(self.current_session_id)
        if context['recent_queries']:
            print(f"\n📜 对话历史: {' → '.join(context['recent_queries'][-3:])}")
        
        # 如果请求可行性分析
        if analyze:
            print("\n📊 查询可行性分析:")
            feasibility = self.query_engine.analyze_query_feasibility(query)
            self._display_feasibility(feasibility)
            
            # 问用户是否继续
            confirm = input("\n是否继续执行查询? (y/n): ").strip().lower()
            if confirm != 'y':
                return
        
        # 执行查询
        result = self.query_engine.execute_query(
            query, 
            session_id=self.current_session_id,
            limit=limit,
            adaptive=adaptive
        )
        
        # 显示自适应查询信息
        if result.get('adaptive_info'):
            self._display_adaptive_info(result['adaptive_info'])
        
        # 显示过滤条件
        if result.get('filters'):
            self._display_filters(result['filters'])
        
        # 显示结果
        print(f"\n✅ 找到 {result['total_count']:,} 条匹配记录", end='')
        if result.get('returned_count'):
            print(f"，显示前 {result['returned_count']} 条")
        print(f"⏱️  查询耗时: {result['execution_time']:.2f} 秒")
        
        if result.get('explanation'):
            print(f"\n💡 {result['explanation']}")
        
        # 显示结果详情
        if not result['results'].empty:
            self.display_results(result['results'])
        
        # 显示建议
        if result.get('suggestions'):
            print("\n📋 查询优化建议:")
            for i, suggestion in enumerate(result['suggestions'], 1):
                print(f"  {i}. {suggestion}")
        
        if result.get('alternative_queries'):
            print("\n🔀 替代查询建议:")
            for i, alt in enumerate(result['alternative_queries'][:5], 1):
                print(f"  {i}. {alt['query']}")
                print(f"     原因: {alt['reason']}")
        
        # 导出结果
        if export and 'results' in result and not result['results'].empty:
            if self.query_engine.export_results(result['results'], export):
                print(f"\n✅ 结果已导出到: {export}")
            else:
                print(f"\n❌ 导出失败")
        
        return result
    
    def _display_feasibility(self, feasibility: Dict[str, Any]):
        """显示可行性分析"""
        info = feasibility['feasibility']
        
        risk_emoji = {
            'low': '✅',
            'medium': '⚡',
            'high': '⚠️',
            'critical': '🚨'
        }.get(info['risk_level'], '❓')
        
        print(f"\n  风险等级: {risk_emoji} {info['risk_level'].upper()}")
        print(f"  预估结果: {info['estimated_results']:,} 条记录")
        
        if info['conflicts']:
            print(f"\n  潜在问题:")
            for conflict in info['conflicts']:
                print(f"    • {conflict['reason']}")
                print(f"      建议: {conflict['suggestion']}")
        
        if feasibility.get('suggestions'):
            print(f"\n  优化建议:")
            for suggestion in feasibility['suggestions']:
                print(f"    • {suggestion}")
    
    def _display_adaptive_info(self, adaptive_info: Dict[str, Any]):
        """显示自适应查询信息"""
        if adaptive_info.get('attempts', 1) > 1:
            print(f"\n🔄 自适应查询已启用")
            print(f"   尝试了 {adaptive_info['attempts']} 种策略")
            print(f"   最终策略: {adaptive_info.get('strategy', 'unknown')}")
        
        if adaptive_info.get('query_analysis'):
            analysis = adaptive_info['query_analysis']
            if analysis.get('risk_level') != 'low':
                print(f"   原始风险等级: {analysis['risk_level']}")
    
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
            print("  (无特定过滤条件)")
    
    def display_results(self, results: pd.DataFrame):
        """显示查询结果"""
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
    
    def show_field_insights(self, field_name: str):
        """显示字段洞察"""
        insights = self.query_engine.get_field_insights(field_name)
        
        if 'error' in insights:
            print(f"\n❌ {insights['error']}")
            return
        
        print(f"\n📊 字段洞察: {field_name}")
        print("=" * 80)
        
        print(f"\n语义类型: {insights['semantic_type']}")
        
        dq = insights['data_quality']
        print(f"\n数据质量:")
        print(f"  总记录数: {dq['total_records']:,}")
        print(f"  唯一值数: {dq['unique_values']:,}")
        print(f"  空值比例: {dq['null_percentage']:.1f}%")
        
        print(f"\n建议操作符: {', '.join(insights['suggested_operators'])}")
        
        print(f"\n值分布（前20）:")
        print("-" * 70)
        for item in insights['value_distribution']:
            bar_length = int(item['percentage'] / 5)
            bar = '█' * bar_length
            print(f"  {item['value'][:40]:<40} {item['count']:>8,} ({item['percentage']:>5.1f}%) {bar}")
    
    def find_similar(self, field_name: str, query: str, top_k: int = 10):
        """查找相似值"""
        print(f"\n🔍 在字段 '{field_name}' 中查找 '{query}' 的相似值")
        print("=" * 80)
        
        similar = self.query_engine.find_similar_values(field_name, query, top_k)
        
        if not similar:
            print("\n未找到相似值")
            return
        
        print(f"\n找到 {len(similar)} 个相似值:")
        print("-" * 70)
        print(f"{'排名':<6} {'值':<40} {'相似度':<10} {'记录数':<10}")
        print("-" * 70)
        
        for i, item in enumerate(similar, 1):
            value = item['value'][:38] + '..' if len(item['value']) > 40 else item['value']
            print(f"{i:<6} {value:<40} {item['similarity']:<10.2f} {item['count']:<10,}")
    
    def smart_concept_search(self, **concepts):
        """基于概念的智能搜索"""
        print(f"\n🧠 智能概念搜索: {concepts}")
        print("=" * 80)
        
        result = self.query_engine.smart_search(concepts, limit=20)
        
        print(f"\n查询策略置信度: {result['strategy_confidence']:.2f}")
        
        if result.get('suggested_values'):
            print("\n建议使用的值:")
            for field, values in result['suggested_values'].items():
                print(f"  {field}:")
                for v in values:
                    print(f"    - '{v['value']}' (匹配度: {v['score']:.2f}, 记录数: {v['count']:,})")
        
        print(f"\n找到 {result['total_count']:,} 条记录")
        
        if not result['results'].empty:
            self.display_results(result['results'])
    
    def interactive_mode(self):
        """交互式模式（增强版）"""
        print("\n" + "=" * 80)
        print(" 🧬 单细胞RNA-seq数据库智能检索系统 v3.0 (增强版)")
        print("=" * 80)
        
        print("\n✨ 新特性：")
        print("  • 数据感知检索 - 基于数据库实际内容智能匹配")
        print("  • 自适应查询 - 自动调整策略避免零结果")
        print("  • 字段洞察 - 深入了解每个字段的数据分布")
        print("  • 相似值查找 - 发现数据库中的相关术语")
        print("  • 查询可行性分析 - 执行前预测查询效果")
        
        print("\n💡 示例查询：")
        print("  - 查找肺癌相关的10x Genomics数据")
        print("  - 脑组织10x数据")
        print("  - COVID-19血液样本")
        
        print("\n🔧 命令：")
        print("  search <查询>          - 搜索数据")
        print("  analyze <查询>         - 分析查询可行性")
        print("  insights <字段>        - 查看字段洞察")
        print("  similar <字段> <值>    - 查找相似值")
        print("  concept <概念...>      - 智能概念搜索")
        print("  adaptive <查询>        - 强制使用自适应查询")
        print("  export <路径>          - 导出最近结果")
        print("  context                - 查看当前上下文")
        print("  new                    - 开始新会话")
        print("  fields                 - 查看所有字段")
        print("  refresh                - 刷新知识库")
        print("  help                   - 查看帮助")
        print("  quit/exit              - 退出")
        
        print("=" * 80)
        print(f"\n当前会话: {self.current_session_id[:8]}")
        print(f"Schema知识库已加载 {len(self.query_engine.schema_kb._field_knowledge)} 个字段")
        
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
                
                elif command == 'analyze':
                    if args:
                        self.search(args, analyze=True)
                    else:
                        print("请提供查询内容")
                
                elif command == 'adaptive':
                    if args:
                        self.search(args, adaptive=True)
                    else:
                        print("请提供查询内容")
                
                elif command == 'insights':
                    if args:
                        self.show_field_insights(args)
                    else:
                        print("请指定字段名")
                
                elif command == 'similar':
                    # 解析: similar <field> <value>
                    parts = args.split(maxsplit=1)
                    if len(parts) == 2:
                        self.find_similar(parts[0], parts[1])
                    else:
                        print("格式: similar <字段名> <查询值>")
                
                elif command == 'concept':
                    # 解析: concept disease=lung tissue=blood
                    concepts = {}
                    for pair in args.split():
                        if '=' in pair:
                            k, v = pair.split('=', 1)
                            concepts[k] = v
                    if concepts:
                        self.smart_concept_search(**concepts)
                    else:
                        print("格式: concept disease=肺癌 tissue=血液")
                
                elif command == 'refresh':
                    print("\n🔄 正在刷新知识库...")
                    self.query_engine.refresh_knowledge_base()
                    print("✅ 知识库已刷新")
                
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
        print("\n📋 可用字段列表:")
        print("=" * 80)
        
        # 按语义类型分组
        semantic_groups = {
            'disease': '疾病相关',
            'tissue': '组织相关',
            'platform': '平台相关',
            'database': '数据库来源',
            'text': '文本字段',
            'boolean': '布尔字段',
            'date': '日期字段',
            'numeric': '数值字段',
            'generic': '其他字段'
        }
        
        for sem_type, title in semantic_groups.items():
            fields = self.query_engine.schema_kb.get_semantic_fields(sem_type)
            if fields:
                print(f"\n{title}:")
                for field in fields:
                    stats = self.query_engine.schema_kb.get_field_statistics(field)
                    if stats:
                        null_info = f"空值{stats.null_percentage:.0f}%"
                        print(f"  • {field:<35} ({null_info}, {stats.unique_count:,}唯一值)")
                    else:
                        print(f"  • {field}")
        
        print("\n" + "=" * 80)
        print("提示: 使用 'insights <字段名>' 查看详细信息")
    
    def show_help(self):
        """显示帮助"""
        help_text = """
╔════════════════════════════════════════════════════════════════════════════╗
║                      增强版帮助文档 v3.0                                   ║
╚════════════════════════════════════════════════════════════════════════════╝

【核心特性】

1. 数据感知检索
   系统深度理解数据库内容，基于实际数据分布进行智能匹配。
   
2. 自适应查询
   当检测到可能返回零结果时，系统自动调整策略，逐步放宽条件。

3. 字段洞察 (insights)
   查看任意字段的数据分布、质量指标和常见值。

4. 相似值查找 (similar)
   查找与查询词相似的数据库值，帮助发现正确的术语。

【查询示例】

1. 简单查询:
   search 查找肺癌相关数据
   search 脑组织10x数据

2. 可行性分析:
   analyze 脑组织10x数据
   （先分析查询可行性，再决定是否执行）

3. 字段洞察:
   insights disease_clean
   insights platform_clean

4. 相似值查找:
   similar tissue_clean brain
   similar disease_clean covid

5. 智能概念搜索:
   concept disease=肺癌 platform=10x
   concept tissue=brain disease=cancer

【命令列表】

  search <查询>              - 执行搜索查询
  analyze <查询>             - 分析查询可行性
  adaptive <查询>            - 强制使用自适应查询模式
  insights <字段>            - 查看字段洞察
  similar <字段> <值>        - 查找相似值
  concept <键=值...>         - 智能概念搜索
  export <路径>              - 导出当前结果
  context                    - 查看会话上下文
  new                        - 开始新会话
  fields                     - 列出所有字段
  refresh                    - 刷新知识库
  help                       - 显示此帮助
  quit/exit                  - 退出程序

【解决零结果问题】

如果查询返回零结果，系统会：
1. 自动尝试更宽松的查询策略
2. 建议使用数据库中实际存在的相似值
3. 推荐移除可能导致过度限制的字段

╚════════════════════════════════════════════════════════════════════════════╝
"""
        print(help_text)
    
    def cleanup(self):
        """清理资源"""
        if self.query_engine:
            self.query_engine.cleanup()


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description='单细胞RNA-seq数据库智能检索系统 v3.0 (增强版)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例用法:
  # 交互式模式
  python -m src.enhanced_cli
  
  # 直接查询
  python -m src.enhanced_cli -q "查找肺癌相关的10x Genomics数据"
  
  # 查询并分析可行性
  python -m src.enhanced_cli -q "脑组织10x数据" --analyze
  
  # 查询并导出
  python -m src.enhanced_cli -q "COVID-19血液样本数据" -o results.xlsx
        """
    )
    
    parser.add_argument('-q', '--query', type=str, help='查询语句')
    parser.add_argument('-l', '--limit', type=int, default=20, help='返回结果数量（默认20）')
    parser.add_argument('-o', '--output', type=str, help='导出结果文件路径')
    parser.add_argument('-c', '--config', type=str, default='config/config.yaml', help='配置文件路径')
    parser.add_argument('--analyze', action='store_true', help='分析查询可行性')
    parser.add_argument('--no-adaptive', action='store_true', help='禁用自适应查询')
    
    args = parser.parse_args()
    
    cli = None
    try:
        cli = EnhancedCLI(config_path=args.config)
        
        if args.query:
            # 命令行模式
            cli.search(
                args.query, 
                limit=args.limit, 
                export=args.output,
                adaptive=not args.no_adaptive,
                analyze=args.analyze
            )
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
