#!/usr/bin/env python3
"""
数据库质量分析脚本
分析std表的数据质量，生成统计报告
"""

import sqlite3
import pandas as pd
from pathlib import Path
from collections import Counter
import json

def analyze_database(db_path='data/scrnaseq.db', table='std'):
    """分析数据库质量"""
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    print("=" * 80)
    print("📊 数据库质量分析报告")
    print("=" * 80)
    
    # 1. 基本统计
    total = cursor.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
    print(f"\n📈 总记录数: {total:,}")
    
    # 2. 获取所有字段
    cursor.execute(f'PRAGMA table_info({table})')
    columns = cursor.fetchall()
    
    print(f"\n📋 字段总数: {len(columns)}")
    print("\n" + "=" * 80)
    print("📊 字段数据质量统计")
    print("=" * 80)
    
    field_stats = []
    
    for col in columns:
        col_name = col[1]
        col_type = col[2]
        
        # 统计非空值
        non_null = cursor.execute(
            f'SELECT COUNT(*) FROM {table} WHERE "{col_name}" IS NOT NULL'
        ).fetchone()[0]
        
        # 统计非空且非空字符串
        non_empty = cursor.execute(
            f'SELECT COUNT(*) FROM {table} WHERE "{col_name}" IS NOT NULL AND "{col_name}" != ""'
        ).fetchone()[0]
        
        # 统计唯一值
        unique = cursor.execute(
            f'SELECT COUNT(DISTINCT "{col_name}") FROM {table}'
        ).fetchone()[0]
        
        completeness = (non_empty / total * 100) if total > 0 else 0
        
        field_stats.append({
            'field': col_name,
            'type': col_type,
            'non_null': non_null,
            'non_empty': non_empty,
            'unique': unique,
            'completeness': completeness,
            'quality': 'High' if completeness > 80 else 'Medium' if completeness > 50 else 'Low'
        })
    
    # 打印统计表
    print(f"\n{'字段名':<30} {'类型':<10} {'非空数':<10} {'完整度':<10} {'质量':<8}")
    print("-" * 80)
    
    for stat in field_stats:
        print(f"{stat['field']:<30} {stat['type']:<10} {stat['non_empty']:<10,} "
              f"{stat['completeness']:<9.1f}% {stat['quality']:<8}")
    
    # 3. 重点字段详细分析
    print("\n" + "=" * 80)
    print("🔍 重点字段详细分析")
    print("=" * 80)
    
    # 疾病字段分析
    print("\n【疾病相关字段】")
    for field in ['disease_general', 'disease', 'disease_standardized', 'disease_category']:
        stats = next((s for s in field_stats if s['field'] == field), None)
        if stats:
            print(f"\n{field}:")
            print(f"  完整度: {stats['completeness']:.1f}%")
            print(f"  唯一值: {stats['unique']}")
            
            if stats['non_empty'] > 0:
                # 显示前10个值
                values = cursor.execute(
                    f'SELECT "{field}", COUNT(*) as cnt FROM {table} '
                    f'WHERE "{field}" IS NOT NULL AND "{field}" != "" '
                    f'GROUP BY "{field}" ORDER BY cnt DESC LIMIT 10'
                ).fetchall()
                print(f"  常见值:")
                for val, cnt in values:
                    val_str = str(val)[:40] if val else '(null)'
                    print(f"    - {val_str:<40} ({cnt:,})")
    
    # 组织字段分析
    print("\n【组织相关字段】")
    for field in ['tissue_location', 'tissue_standardized']:
        stats = next((s for s in field_stats if s['field'] == field), None)
        if stats:
            print(f"\n{field}:")
            print(f"  完整度: {stats['completeness']:.1f}%")
            if stats['non_empty'] > 0:
                values = cursor.execute(
                    f'SELECT "{field}", COUNT(*) as cnt FROM {table} '
                    f'WHERE "{field}" IS NOT NULL AND "{field}" != "" '
                    f'GROUP BY "{field}" ORDER BY cnt DESC LIMIT 5'
                ).fetchall()
                print(f"  常见值:")
                for val, cnt in values:
                    val_str = str(val)[:35] if val else '(null)'
                    print(f"    - {val_str} ({cnt:,})")
    
    # 平台字段分析
    print("\n【平台相关字段】")
    for field in ['sequencing_platform', 'platform_standardized']:
        stats = next((s for s in field_stats if s['field'] == field), None)
        if stats:
            print(f"\n{field}:")
            print(f"  完整度: {stats['completeness']:.1f}%")
            if stats['non_empty'] > 0:
                values = cursor.execute(
                    f'SELECT "{field}", COUNT(*) as cnt FROM {table} '
                    f'WHERE "{field}" IS NOT NULL AND "{field}" != "" '
                    f'GROUP BY "{field}" ORDER BY cnt DESC LIMIT 5'
                ).fetchall()
                print(f"  常见值:")
                for val, cnt in values:
                    val_str = str(val)[:35] if val else '(null)'
                    print(f"    - {val_str} ({cnt:,})")
    
    # 数据库来源分析
    print("\n【数据库来源】")
    values = cursor.execute(
        f'SELECT source_database, COUNT(*) as cnt FROM {table} '
        f'WHERE source_database IS NOT NULL AND source_database != "" '
        f'GROUP BY source_database ORDER BY cnt DESC'
    ).fetchall()
    for val, cnt in values:
        print(f"  - {val}: {cnt:,} ({cnt/total*100:.1f}%)")
    
    # 4. 数据开放情况
    print("\n" + "=" * 80)
    print("📊 数据开放情况")
    print("=" * 80)
    
    open_stats = cursor.execute(
        f'SELECT matrix_open, COUNT(*) FROM {table} GROUP BY matrix_open'
    ).fetchall()
    print("\nmatrix_open (表达矩阵开放):")
    for val, cnt in open_stats:
        status = "开放" if val else "不开放/未知"
        print(f"  - {status}: {cnt:,} ({cnt/total*100:.1f}%)")
    
    # 5. 问题总结
    print("\n" + "=" * 80)
    print("⚠️  发现的问题")
    print("=" * 80)
    
    problems = []
    
    # 检查标准化字段
    for field in ['disease_standardized', 'tissue_standardized', 'platform_standardized']:
        stats = next((s for s in field_stats if s['field'] == field), None)
        if stats and stats['completeness'] < 10:
            problems.append(f"❌ {field}: 完整度仅{stats['completeness']:.1f}%，需要重新生成")
    
    # 检查日期格式问题
    date_like_fields = cursor.execute(
        f"SELECT disease_standardized FROM {table} WHERE disease_standardized LIKE '%/%' LIMIT 5"
    ).fetchall()
    if date_like_fields:
        problems.append(f"❌ disease_standardized 字段包含日期格式数据，内容错误")
    
    if problems:
        for p in problems:
            print(p)
    else:
        print("✅ 未发现明显问题")
    
    # 6. 保存报告
    report_path = 'data/database_quality_report.json'
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump({
            'total_records': total,
            'field_count': len(columns),
            'field_stats': field_stats,
            'problems': problems
        }, f, ensure_ascii=False, indent=2)
    
    print(f"\n📄 详细报告已保存: {report_path}")
    
    conn.close()

if __name__ == '__main__':
    analyze_database()
