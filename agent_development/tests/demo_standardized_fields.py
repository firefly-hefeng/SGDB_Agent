#!/usr/bin/env python3
"""
标准化字段演示脚本
展示新旧字段查询效果的对比
"""

import sqlite3
import pandas as pd
from pathlib import Path
from datetime import datetime

DB_PATH = Path(__file__).parent.parent / "data" / "scrnaseq.db"

def run_query(query, params=()):
    """执行SQL查询"""
    conn = sqlite3.connect(DB_PATH)
    try:
        df = pd.read_sql_query(query, conn, params=params)
        return df
    finally:
        conn.close()

def demo_disease_standardization():
    """演示疾病标准化字段的优势"""
    print("\n" + "="*70)
    print("演示1: 疾病标准化字段查询对比")
    print("="*70)
    
    # 原始字段查询 - 需要多个条件
    print("\n📍 使用原始字段查询 'Lung Cancer':")
    print("-" * 50)
    query1 = '''
        SELECT COUNT(*) as count 
        FROM std 
        WHERE disease LIKE '%lung%' 
           OR disease LIKE '%Lung%'
           OR disease_general LIKE '%Cancer%'
    '''
    result1 = run_query(query1)
    print(f"  结果: {result1['count'].iloc[0]:,} 条")
    print(f"  问题: 可能包含非肺癌的肺部疾病")
    
    # 标准化字段查询 - 精确匹配
    print("\n📍 使用标准化字段查询 'Lung Cancer':")
    print("-" * 50)
    query2 = '''
        SELECT COUNT(*) as count 
        FROM std 
        WHERE disease_standardized = 'Lung Cancer'
    '''
    result2 = run_query(query2)
    print(f"  结果: {result2['count'].iloc[0]:,} 条")
    print(f"  优势: 精确匹配，无歧义")
    
    # 展示疾病分类的使用
    print("\n📍 使用疾病分类查询所有癌症:")
    print("-" * 50)
    query3 = '''
        SELECT disease_standardized, COUNT(*) as count 
        FROM std 
        WHERE disease_category = 'Cancer'
        GROUP BY disease_standardized
        ORDER BY count DESC
        LIMIT 10
    '''
    result3 = run_query(query3)
    print(result3.to_string(index=False))

def demo_platform_standardization():
    """演示平台标准化字段的优势"""
    print("\n" + "="*70)
    print("演示2: 测序平台标准化字段查询对比")
    print("="*70)
    
    # 原始字段的各种写法
    print("\n📍 原始字段查询 10x 平台 (需要多个模式):")
    print("-" * 50)
    query1 = '''
        SELECT sequencing_platform, COUNT(*) as count 
        FROM std 
        WHERE sequencing_platform LIKE '%10x%' 
           OR sequencing_platform LIKE '%Chromium%'
           OR sequencing_platform LIKE '%Genomics%'
        GROUP BY sequencing_platform
        ORDER BY count DESC
        LIMIT 5
    '''
    result1 = run_query(query1)
    print(result1.to_string(index=False))
    print(f"  注意: 写法不统一，需要模糊匹配")
    
    # 标准化字段的统一写法
    print("\n📍 标准化字段查询 10x 平台:")
    print("-" * 50)
    query2 = '''
        SELECT platform_standardized, COUNT(*) as count 
        FROM std 
        WHERE platform_standardized LIKE '%10x%'
        GROUP BY platform_standardized
        ORDER BY count DESC
        LIMIT 5
    '''
    result2 = run_query(query2)
    print(result2.to_string(index=False))
    print(f"  优势: 统一命名，查询更简单")

def demo_sex_standardization():
    """演示性别标准化字段的优势"""
    print("\n" + "="*70)
    print("演示3: 性别标准化字段查询对比")
    print("="*70)
    
    print("\n📍 原始字段的性别分布:")
    print("-" * 50)
    query1 = '''
        SELECT sex, COUNT(*) as count 
        FROM std 
        WHERE sex IS NOT NULL AND sex != ''
        GROUP BY sex
        ORDER BY count DESC
        LIMIT 10
    '''
    result1 = run_query(query1)
    print(result1.to_string(index=False))
    print("  问题: 格式不统一 (Male/male/F/M 等)")
    
    print("\n📍 标准化字段的性别分布:")
    print("-" * 50)
    query2 = '''
        SELECT sex_standardized, COUNT(*) as count 
        FROM std 
        WHERE sex_standardized IS NOT NULL 
          AND sex_standardized != ''
          AND sex_standardized != 'Unknown'
        GROUP BY sex_standardized
        ORDER BY count DESC
    '''
    result2 = run_query(query2)
    print(result2.to_string(index=False))
    print("  优势: 统一为 Male/Female/Mixed/Other")

def demo_complex_query():
    """演示复杂查询使用标准化字段"""
    print("\n" + "="*70)
    print("演示4: 复杂组合查询 (使用标准化字段)")
    print("="*70)
    
    print("\n📍 查询: 2020年后发表的、女性、开放获取的癌症数据")
    print("-" * 50)
    query = '''
        SELECT 
            project_id_primary,
            disease_standardized,
            platform_standardized,
            citation_count,
            publication_date
        FROM std 
        WHERE disease_category = 'Cancer'
          AND sex_standardized = 'Female'
          AND matrix_open = 1
          AND publication_date > '2020-01-01'
        ORDER BY citation_count DESC
        LIMIT 10
    '''
    result = run_query(query)
    print(result.to_string(index=False))
    print(f"\n  返回 {len(result)} 条高质量记录")

def demo_data_quality_filter():
    """演示使用元数据质量字段"""
    print("\n" + "="*70)
    print("演示5: 使用元数据质量评分过滤")
    print("="*70)
    
    print("\n📍 不同质量等级的数据分布:")
    print("-" * 50)
    query = '''
        SELECT 
            metadata_quality_score,
            COUNT(*) as count,
            ROUND(AVG(metadata_completeness) * 100, 2) as avg_completeness
        FROM std 
        WHERE metadata_quality_score IS NOT NULL
        GROUP BY metadata_quality_score
        ORDER BY count DESC
    '''
    result = run_query(query)
    print(result.to_string(index=False))
    
    print("\n📍 高质量元数据样本 (High + 完整度>90%):")
    print("-" * 50)
    query2 = '''
        SELECT 
            project_id_primary,
            database_standardized,
            disease_standardized,
            metadata_completeness,
            access_link
        FROM std 
        WHERE metadata_quality_score = 'High'
          AND metadata_completeness > 0.9
          AND access_link IS NOT NULL
        LIMIT 5
    '''
    result2 = run_query(query2)
    print(result2.to_string(index=False))

def show_coverage_summary():
    """显示标准化字段覆盖情况"""
    print("\n" + "="*70)
    print("标准化字段覆盖率汇总")
    print("="*70)
    
    fields = [
        ('sex_standardized', '性别标准化'),
        ('disease_standardized', '疾病标准化'),
        ('disease_category', '疾病分类'),
        ('platform_standardized', '平台标准化'),
        ('sample_type_standardized', '样本类型标准化'),
        ('tissue_standardized', '组织标准化'),
        ('database_standardized', '数据库标准化'),
        ('open_status_standardized', '开放状态标准化'),
        ('ethnicity_standardized', '种族标准化'),
    ]
    
    print("\n{:<25} {:<15} {:<15} {:<10}".format(
        "字段名", "有效记录数", "总记录数", "覆盖率"))
    print("-" * 70)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM std")
    total = cursor.fetchone()[0]
    
    for field, name in fields:
        cursor.execute(f'''
            SELECT COUNT(*) FROM std 
            WHERE "{field}" IS NOT NULL 
              AND "{field}" != '' 
              AND "{field}" != 'Unknown'
        ''')
        valid = cursor.fetchone()[0]
        coverage = valid / total * 100
        
        status = "✅" if coverage > 50 else "⚠️" if coverage > 20 else "❌"
        print("{:<25} {:>15,} {:>15,} {:>9.1f}% {}".format(
            name, valid, total, coverage, status))
    
    conn.close()

def main():
    print("="*70)
    print("单细胞数据库 - 标准化字段演示")
    print(f"数据库: {DB_PATH}")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*70)
    
    demo_disease_standardization()
    demo_platform_standardization()
    demo_sex_standardization()
    demo_complex_query()
    demo_data_quality_filter()
    show_coverage_summary()
    
    print("\n" + "="*70)
    print("演示完成!")
    print("="*70)
    print("\n💡 总结:")
    print("   • 标准化字段提供更一致的查询体验")
    print("   • disease_standardized 和 database_standardized 覆盖率最高")
    print("   • sex_standardized 和 sample_type_standardized 需要提升覆盖率")
    print("   • metadata_quality_score 可用于筛选高质量数据")

if __name__ == "__main__":
    main()
