"""
增强版查询系统演示
展示数据感知和自适应查询功能
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.config_manager import ConfigManager
from src.enhanced_query_engine import EnhancedQueryEngine


def demo_schema_knowledge():
    """演示Schema知识库功能"""
    print("=" * 80)
    print("演示1: Schema知识库 - 了解数据库内容")
    print("=" * 80)
    
    config = ConfigManager("config/config.yaml")
    engine = EnhancedQueryEngine(config)
    engine.initialize()
    
    # 查看字段洞察
    print("\n📊 查看 disease_clean 字段的数据分布:")
    insights = engine.get_field_insights("disease_clean")
    print(f"  语义类型: {insights['semantic_type']}")
    print(f"  总记录数: {insights['data_quality']['total_records']:,}")
    print(f"  唯一值数: {insights['data_quality']['unique_values']:,}")
    print(f"  空值比例: {insights['data_quality']['null_percentage']:.1f}%")
    print(f"\n  常见疾病（前5）:")
    for item in insights['value_distribution'][:5]:
        print(f"    • {item['value']}: {item['count']:,} 条 ({item['percentage']:.1f}%)")
    
    # 查找相似值
    print("\n🔍 查找与 'brain' 相似的 tissue_clean 值:")
    similar = engine.find_similar_values("tissue_clean", "brain", top_k=5)
    for item in similar:
        print(f"    • '{item['value']}' (相似度: {item['similarity']:.2f}, {item['count']:,}条)")
    
    engine.cleanup()


def demo_adaptive_query():
    """演示自适应查询功能"""
    print("\n" + "=" * 80)
    print("演示2: 自适应查询 - 防止零结果")
    print("=" * 80)
    
    config = ConfigManager("config/config.yaml")
    engine = EnhancedQueryEngine(config)
    engine.initialize()
    
    # 测试可能返回零结果的查询
    test_queries = [
        "脑组织10x数据",  # 原始问题案例
        "肺癌免疫治疗",   # 中文疾病名
        "covid19 brain 10x",  # 混合语言
    ]
    
    for query in test_queries:
        print(f"\n📝 查询: {query}")
        print("-" * 60)
        
        # 先分析可行性
        feasibility = engine.analyze_query_feasibility(query)
        print(f"  风险等级: {feasibility['feasibility']['risk_level']}")
        print(f"  预估结果: {feasibility['feasibility']['estimated_results']:,} 条")
        
        if feasibility.get('suggestions'):
            print("  建议:")
            for suggestion in feasibility['suggestions']:
                print(f"    • {suggestion}")
        
        # 执行自适应查询
        result = engine.execute_query(query, adaptive=True)
        
        if result.get('adaptive_info'):
            info = result['adaptive_info']
            if info.get('attempts', 1) > 1:
                print(f"  🔄 自适应策略生效！尝试了 {info['attempts']} 种策略")
                print(f"     最终策略: {info['strategy']}")
        
        print(f"  ✅ 最终结果: {result['total_count']:,} 条记录")
        
        if result.get('suggestions'):
            print("  💡 优化建议:")
            for suggestion in result['suggestions'][:2]:
                print(f"    • {suggestion}")
    
    engine.cleanup()


def demo_smart_concept_search():
    """演示智能概念搜索"""
    print("\n" + "=" * 80)
    print("演示3: 智能概念搜索")
    print("=" * 80)
    
    config = ConfigManager("config/config.yaml")
    engine = EnhancedQueryEngine(config)
    engine.initialize()
    
    # 基于概念搜索
    concepts_list = [
        {"disease": "lung cancer", "platform": "10x"},
        {"tissue": "brain", "disease": "glioma"},
        {"disease": "covid-19", "tissue": "blood"},
    ]
    
    for concepts in concepts_list:
        print(f"\n🧠 概念搜索: {concepts}")
        print("-" * 60)
        
        result = engine.smart_search(concepts, limit=5)
        
        print(f"  策略置信度: {result['strategy_confidence']:.2f}")
        print(f"  找到记录: {result['total_count']:,} 条")
        
        if result.get('suggested_values'):
            print("  建议使用的值:")
            for field, values in result['suggested_values'].items():
                best = values[0] if values else None
                if best:
                    print(f"    • {field}: '{best['value']}' (匹配度{best['score']:.2f})")
    
    engine.cleanup()


def demo_query_comparison():
    """对比普通查询和增强查询"""
    print("\n" + "=" * 80)
    print("演示4: 对比普通查询 vs 增强查询")
    print("=" * 80)
    
    config = ConfigManager("config/config.yaml")
    engine = EnhancedQueryEngine(config)
    engine.initialize()
    
    query = "脑组织10x数据"  # 你的原始问题
    
    print(f"\n📝 测试查询: {query}")
    print("-" * 60)
    
    # 方式1：分析可行性
    print("\n1️⃣ 可行性分析:")
    feasibility = engine.analyze_query_feasibility(query)
    risk = feasibility['feasibility']['risk_level']
    emoji = {'low': '✅', 'medium': '⚡', 'high': '⚠️', 'critical': '🚨'}.get(risk, '❓')
    print(f"   风险等级: {emoji} {risk}")
    print(f"   预估结果: {feasibility['feasibility']['estimated_results']:,} 条")
    
    if feasibility['feasibility'].get('conflicts'):
        print("   潜在冲突:")
        for conflict in feasibility['feasibility']['conflicts']:
            print(f"     • {conflict['reason']}")
    
    # 方式2：标准查询（不使用自适应）
    print("\n2️⃣ 标准查询（禁用自适应）:")
    result_std = engine.execute_query(query, adaptive=False)
    print(f"   结果: {result_std['total_count']:,} 条")
    
    # 方式3：增强查询（使用自适应）
    print("\n3️⃣ 增强查询（启用自适应）:")
    result_enhanced = engine.execute_query(query, adaptive=True)
    print(f"   结果: {result_enhanced['total_count']:,} 条")
    
    if result_enhanced.get('adaptive_info'):
        info = result_enhanced['adaptive_info']
        print(f"   自适应策略: {info.get('strategy')}")
        print(f"   尝试次数: {info.get('attempts')}")
    
    print("\n" + "=" * 60)
    if result_std['total_count'] == 0 and result_enhanced['total_count'] > 0:
        print("✅ 增强查询成功解决了零结果问题！")
    elif result_std['total_count'] == result_enhanced['total_count']:
        print("✅ 两种查询方式结果一致")
    else:
        print(f"⚠️ 结果差异: 标准查询 {result_std['total_count']} 条，增强查询 {result_enhanced['total_count']} 条")
    
    engine.cleanup()


def demo_interactive_exploration():
    """交互式探索"""
    print("\n" + "=" * 80)
    print("演示5: 交互式探索 - 发现数据规律")
    print("=" * 80)
    
    config = ConfigManager("config/config.yaml")
    engine = EnhancedQueryEngine(config)
    engine.initialize()
    
    # 探索不同字段
    fields_to_explore = [
        "disease_clean",
        "tissue_clean",
        "platform_clean",
        "database_standardized"
    ]
    
    print("\n📊 数据概览:")
    for field in fields_to_explore:
        insights = engine.get_field_insights(field)
        dq = insights['data_quality']
        top_values = insights['value_distribution'][:3]
        top_str = ', '.join([f"{v['value']}({v['count']:,})" for v in top_values])
        
        print(f"\n  {field}:")
        print(f"    记录: {dq['total_records'] - dq['null_percentage']:.0f}%填充, "
              f"{dq['unique_values']:,}唯一值")
        print(f"    热门: {top_str}")
    
    # 探索相似值
    print("\n\n🔍 相似值探索:")
    
    queries = [
        ("disease_clean", "lung"),
        ("disease_clean", "brain tumor"),
        ("tissue_clean", "blood"),
        ("platform_clean", "10x"),
    ]
    
    for field, query in queries:
        similar = engine.find_similar_values(field, query, top_k=3)
        print(f"\n  '{query}' in {field}:")
        for item in similar:
            print(f"    → '{item['value']}' (相似度{item['similarity']:.2f}, {item['count']:,}条)")
    
    engine.cleanup()


def main():
    """主函数"""
    print("\n" + "=" * 80)
    print(" 单细胞RNA-seq数据库智能检索系统 v3.0")
    print(" 增强版功能演示")
    print("=" * 80)
    
    demos = [
        ("Schema知识库", demo_schema_knowledge),
        ("自适应查询", demo_adaptive_query),
        ("智能概念搜索", demo_smart_concept_search),
        ("查询对比", demo_query_comparison),
        ("交互式探索", demo_interactive_exploration),
    ]
    
    print("\n可用演示:")
    for i, (name, _) in enumerate(demos, 1):
        print(f"  {i}. {name}")
    print("  0. 运行全部")
    
    try:
        choice = input("\n请选择要运行的演示 (0-5): ").strip()
        choice = int(choice) if choice else 0
    except:
        choice = 0
    
    if choice == 0:
        for name, func in demos:
            try:
                func()
            except Exception as e:
                print(f"\n❌ {name} 演示出错: {e}")
    elif 1 <= choice <= len(demos):
        try:
            demos[choice - 1][1]()
        except Exception as e:
            print(f"\n❌ 演示出错: {e}")
    else:
        print("无效选择")
    
    print("\n" + "=" * 80)
    print("演示完成！")
    print("提示: 使用 'python run_enhanced.py' 启动交互式界面")
    print("=" * 80)


if __name__ == '__main__':
    main()
