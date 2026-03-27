"""
数据下载功能演示脚本
演示如何使用SCDB-Agent的下载功能
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import pandas as pd
from src.config_manager import ConfigManager
from src.query_engine import QueryEngine


def demo_download_workflow():
    """演示完整的数据下载工作流程"""
    
    print("=" * 80)
    print("🧬 SCDB-Agent 数据下载功能演示")
    print("=" * 80)
    
    # 1. 初始化
    print("\n[1/5] 初始化查询引擎...")
    config = ConfigManager('config/config.yaml')
    engine = QueryEngine(config)
    engine.initialize()
    print("✅ 引擎初始化完成")
    
    # 2. 执行查询
    print("\n[2/5] 执行查询...")
    query = "肺癌相关的10x Genomics单细胞数据"
    print(f"查询: {query}")
    
    result = engine.execute_query(query, limit=5)  # 限制5条用于演示
    records = result['results']
    
    if records.empty:
        print("❌ 没有找到匹配的数据")
        engine.cleanup()
        return
    
    print(f"✅ 找到 {len(records)} 条记录")
    
    # 3. 预览下载信息
    print("\n[3/5] 获取下载预览...")
    preview = engine.get_download_preview(records, max_preview=3)
    
    print(f"\n预览信息:")
    print(f"  总记录数: {preview['total_records']}")
    
    if preview['database_distribution']:
        print(f"  数据库分布:")
        for db, count in preview['database_distribution'].items():
            print(f"    - {db}: {count} 条")
    
    print(f"\n预览记录:")
    for i, rec in enumerate(preview['preview_records'], 1):
        print(f"  [{i}] {rec['project_id']} ({rec['database']})")
        print(f"      标题: {rec['title'][:50]}...")
    
    # 4. 创建下载任务
    print("\n[4/5] 创建下载任务...")
    tasks = engine.create_download_tasks(
        records,
        file_types=['matrix'],
        output_dir='demo_downloads'
    )
    
    print(f"✅ 创建了 {len(tasks)} 个下载任务")
    
    # 显示任务详情
    print("\n任务详情:")
    for task in tasks[:3]:  # 只显示前3个
        print(f"  • {task.project_id} ({task.database})")
        print(f"    文件类型: {task.file_type}.{task.file_format}")
        print(f"    目标路径: {task.target_path}")
    
    # 5. 生成下载脚本
    print("\n[5/5] 生成批量下载脚本...")
    script_path = engine.generate_download_script(
        records,
        output_path='demo_downloads/download_demo.sh'
    )
    
    print(f"✅ 脚本已生成: {script_path}")
    
    # 导出下载列表
    list_path = engine.data_downloader.export_download_list(
        tasks,
        'demo_downloads/download_list.csv'
    )
    print(f"✅ 下载列表已导出: {list_path}")
    
    # 显示脚本内容预览
    print("\n脚本内容预览:")
    print("-" * 60)
    script_content = Path(script_path).read_text().split('\n')[:20]
    for line in script_content:
        print(line)
    print("-" * 60)
    
    # 清理
    engine.cleanup()
    
    print("\n" + "=" * 80)
    print("✅ 演示完成！")
    print("=" * 80)
    print("\n你可以:")
    print(f"  1. 查看生成的下载脚本: cat {script_path}")
    print(f"  2. 执行下载: bash {script_path}")
    print(f"  3. 查看下载列表: cat {list_path}")
    print("\n注意: 演示模式仅创建了任务和脚本，并未实际下载数据。")


def demo_programmatic_download():
    """演示程序化使用下载功能"""
    
    print("\n" + "=" * 80)
    print("📝 程序化下载演示")
    print("=" * 80)
    
    # 初始化
    config = ConfigManager('config/config.yaml')
    engine = QueryEngine(config)
    engine.initialize()
    
    # 创建模拟数据（实际使用时来自查询结果）
    mock_records = pd.DataFrame([
        {
            'sample_uid': 'DEMO001',
            'project_id_primary': 'GSE12345',
            'database_standardized': 'GEO',
            'title': 'Demo Dataset 1',
            'access_link': 'https://example.com/data1.h5ad',
            'file_type': 'h5ad'
        },
        {
            'sample_uid': 'DEMO002',
            'project_id_primary': 'SCP67890',
            'database_standardized': 'CellxGene',
            'title': 'Demo Dataset 2',
            'access_link': 'https://example.com/data2.h5ad',
            'file_type': 'h5ad'
        }
    ])
    
    print("\n模拟查询结果:")
    print(mock_records[['sample_uid', 'project_id_primary', 'database_standardized']])
    
    # 创建任务
    tasks = engine.create_download_tasks(
        mock_records,
        file_types=['matrix'],
        output_dir='demo_downloads'
    )
    
    print(f"\n创建了 {len(tasks)} 个下载任务:")
    for task in tasks:
        print(f"  - {task.task_id}: {task.project_id} ({task.database})")
    
    # 获取下载器
    print("\n获取适合的下载器:")
    for task in tasks:
        downloader = engine.data_downloader._get_downloader(task.database)
        print(f"  - {task.database}: {downloader.__class__.__name__}")
    
    engine.cleanup()
    print("\n✅ 程序化演示完成")


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='数据下载功能演示')
    parser.add_argument('--workflow', action='store_true', help='运行完整工作流程演示')
    parser.add_argument('--programmatic', action='store_true', help='运行程序化演示')
    parser.add_argument('--all', action='store_true', help='运行所有演示')
    
    args = parser.parse_args()
    
    if not any([args.workflow, args.programmatic, args.all]):
        # 默认运行所有
        args.all = True
    
    try:
        if args.workflow or args.all:
            demo_download_workflow()
        
        if args.programmatic or args.all:
            demo_programmatic_download()
            
    except Exception as e:
        print(f"\n❌ 演示失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
