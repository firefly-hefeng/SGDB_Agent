#!/usr/bin/env python3
"""
AI检索功能测试 - 测试查询解析和边界情况
"""

import sys
import json
import sqlite3
import pandas as pd
from pathlib import Path
from datetime import datetime

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# 直接使用SQL测试各种查询场景
DB_PATH = project_root / "data" / "scrnaseq.db"
RESULTS_DIR = project_root / "tests" / "test_results"
RESULTS_DIR.mkdir(exist_ok=True)

class QueryTester:
    """查询测试器"""
    
    def __init__(self):
        self.conn = sqlite3.connect(DB_PATH)
        self.conn.row_factory = sqlite3.Row
        self.cursor = self.conn.cursor()
        self.test_results = []
        
    def close(self):
        self.conn.close()
    
    def log_result(self, category, test_name, query, result_count, execution_time, notes=""):
        """记录测试结果"""
        result = {
            'timestamp': datetime.now().isoformat(),
            'category': category,
            'test_name': test_name,
            'query': query,
            'result_count': result_count,
            'execution_time': execution_time,
            'notes': notes
        }
        self.test_results.append(result)
        status = "✅" if result_count > 0 else "⚠️"
        print(f"{status} {test_name}: {result_count:,} 条 ({execution_time:.3f}s)")
        if notes:
            print(f"   备注: {notes}")
    
    def test_standardized_field_queries(self):
        """测试标准化字段查询"""
        print("\n" + "="*70)
        print("测试: 标准化字段精确查询")
        print("="*70)
        
        test_cases = [
            ("GEO数据库", 
             'database_standardized = "GEO"', 
             "标准化数据库字段"),
            ("女性样本", 
             'sex_standardized = "Female"', 
             "标准化性别字段"),
            ("癌症分类", 
             'disease_category = "Cancer"', 
             "疾病分类字段"),
            ("开放数据", 
             'open_status_standardized = "Open" AND matrix_open = 1', 
             "开放状态标准化"),
            ("10x平台", 
             'platform_standardized LIKE "%10x%" OR platform_standardized LIKE "%Chromium%"', 
             "平台标准化查询"),
        ]
        
        for name, condition, note in test_cases:
            query = f'SELECT COUNT(*) FROM std WHERE {condition}'
            start = datetime.now()
            self.cursor.execute(query)
            count = self.cursor.fetchone()[0]
            elapsed = (datetime.now() - start).total_seconds()
            self.log_result("标准化字段", name, query, count, elapsed, note)
    
    def test_complex_combinations(self):
        """测试复杂组合查询"""
        print("\n" + "="*70)
        print("测试: 复杂组合查询")
        print("="*70)
        
        complex_queries = [
            ("癌症+女性+开放", 
             '''disease_category = "Cancer" 
                AND sex_standardized = "Female" 
                AND matrix_open = 1'''),
            ("COVID-19+血液+近期发表", 
             '''disease_standardized LIKE "%COVID%" 
                AND tissue_standardized LIKE "%Blood%" 
                AND publication_date > "2020-01-01"'''),
            ("高质量+高引用", 
             '''metadata_quality_score = "High" 
                AND citation_count > 10'''),
            ("特定平台+正常组织", 
             '''platform_standardized = "10x Genomics Chromium" 
                AND disease_standardized = "Normal"'''),
        ]
        
        for name, condition in complex_queries:
            query = f'SELECT * FROM std WHERE {condition} LIMIT 100'
            start = datetime.now()
            self.cursor.execute(query)
            rows = self.cursor.fetchall()
            elapsed = (datetime.now() - start).total_seconds()
            self.log_result("复杂组合", name, query, len(rows), elapsed)
    
    def test_fuzzy_and_partial(self):
        """测试模糊和部分匹配"""
        print("\n" + "="*70)
        print("测试: 模糊和部分匹配")
        print("="*70)
        
        fuzzy_tests = [
            ("标题含cancer", 'title LIKE "%cancer%"'),
            ("标题含lung", 'title LIKE "%lung%"'),
            ("疾病含carcinoma", 'disease_standardized LIKE "%carcinoma%"'),
            ("组织含brain", 'tissue_standardized LIKE "%brain%"'),
            ("摘要含single cell", 'summary LIKE "%single cell%"'),
        ]
        
        for name, condition in fuzzy_tests:
            query = f'SELECT COUNT(*) FROM std WHERE {condition}'
            start = datetime.now()
            self.cursor.execute(query)
            count = self.cursor.fetchone()[0]
            elapsed = (datetime.now() - start).total_seconds()
            note = "较慢" if elapsed > 1.0 else "正常"
            self.log_result("模糊匹配", name, query, count, elapsed, note)
    
    def test_range_queries(self):
        """测试范围查询"""
        print("\n" + "="*70)
        print("测试: 范围查询")
        print("="*70)
        
        range_tests = [
            ("引用>100", 'citation_count > 100'),
            ("引用10-50", 'citation_count BETWEEN 10 AND 50'),
            ("2020年后发表", 'publication_date > "2020-01-01"'),
            ("2020-2023年", 'publication_date BETWEEN "2020-01-01" AND "2023-12-31"'),
            ("年龄20-40", 'age_numeric BETWEEN 20 AND 40'),
            ("完整度>0.8", 'metadata_completeness > 0.8'),
        ]
        
        for name, condition in range_tests:
            query = f'SELECT COUNT(*) FROM std WHERE {condition}'
            start = datetime.now()
            self.cursor.execute(query)
            count = self.cursor.fetchone()[0]
            elapsed = (datetime.now() - start).total_seconds()
            self.log_result("范围查询", name, query, count, elapsed)
    
    def test_boolean_filters(self):
        """测试布尔过滤"""
        print("\n" + "="*70)
        print("测试: 布尔过滤")
        print("="*70)
        
        bool_tests = [
            ("矩阵开放", 'matrix_open = 1'),
            ("原始数据开放", 'raw_open = 1'),
            ("两者都开放", 'matrix_open = 1 AND raw_open = 1'),
            ("非重复样本", 'is_duplicate = 0 OR is_duplicate IS NULL'),
            ("高质量元数据", 'metadata_quality_score = "High"'),
        ]
        
        for name, condition in bool_tests:
            query = f'SELECT COUNT(*) FROM std WHERE {condition}'
            start = datetime.now()
            self.cursor.execute(query)
            count = self.cursor.fetchone()[0]
            elapsed = (datetime.now() - start).total_seconds()
            self.log_result("布尔过滤", name, query, count, elapsed)
    
    def test_aggregation_queries(self):
        """测试聚合查询"""
        print("\n" + "="*70)
        print("测试: 聚合查询")
        print("="*70)
        
        agg_queries = [
            ("数据库分布", 
             'SELECT database_standardized, COUNT(*) as cnt FROM std GROUP BY database_standardized ORDER BY cnt DESC'),
            ("平台TOP10", 
             'SELECT platform_standardized, COUNT(*) as cnt FROM std WHERE platform_standardized != "Unknown" GROUP BY platform_standardized ORDER BY cnt DESC LIMIT 10'),
            ("疾病分类统计", 
             'SELECT disease_category, COUNT(*) as cnt FROM std GROUP BY disease_category ORDER BY cnt DESC'),
            ("每年发表量", 
             'SELECT substr(publication_date, 1, 4) as year, COUNT(*) as cnt FROM std WHERE publication_date != "" GROUP BY year ORDER BY year DESC LIMIT 10'),
            ("平均引用数(按数据库)", 
             'SELECT database_standardized, AVG(citation_count) as avg_citations FROM std GROUP BY database_standardized'),
        ]
        
        for name, query in agg_queries:
            start = datetime.now()
            self.cursor.execute(query)
            rows = self.cursor.fetchall()
            elapsed = (datetime.now() - start).total_seconds()
            self.log_result("聚合查询", name, query, len(rows), elapsed)
    
    def test_sample_data_preview(self):
        """测试样例数据预览"""
        print("\n" + "="*70)
        print("测试: 样例数据预览")
        print("="*70)
        
        # 获取一些代表性的样本
        preview_queries = [
            ("最新发表(高引用)", 
             'SELECT title, disease_standardized, platform_standardized, citation_count, publication_date FROM std WHERE citation_count > 50 ORDER BY publication_date DESC LIMIT 3'),
            ("开放数据样例", 
             'SELECT title, database_standardized, disease_category, access_link FROM std WHERE matrix_open = 1 AND metadata_quality_score = "High" LIMIT 3'),
        ]
        
        for name, query in preview_queries:
            start = datetime.now()
            df = pd.read_sql_query(query, self.conn)
            elapsed = (datetime.now() - start).total_seconds()
            print(f"\n📋 {name}:")
            print(df.to_string(index=False))
            self.log_result("数据预览", name, query, len(df), elapsed)
    
    def test_potential_issues(self):
        """测试潜在问题"""
        print("\n" + "="*70)
        print("测试: 潜在问题发现")
        print("="*70)
        
        issue_tests = [
            ("日期格式异常", 
             'SELECT COUNT(*) FROM std WHERE publication_date != "" AND publication_date NOT LIKE "____-__-__"'),
            ("引用数为负", 
             'SELECT COUNT(*) FROM std WHERE citation_count < 0'),
            ("空access_link", 
             'SELECT COUNT(*) FROM std WHERE access_link IS NULL OR access_link = ""'),
            ("重复sample_uid", 
             'SELECT COUNT(*) FROM (SELECT sample_uid, COUNT(*) as cnt FROM std GROUP BY sample_uid HAVING cnt > 1)'),
            ("性别标准化不一致", 
             'SELECT COUNT(*) FROM std WHERE (sex = "male" AND sex_standardized = "Female") OR (sex = "female" AND sex_standardized = "Male")'),
        ]
        
        for name, query in issue_tests:
            start = datetime.now()
            self.cursor.execute(query)
            count = self.cursor.fetchone()[0]
            elapsed = (datetime.now() - start).total_seconds()
            note = "⚠️ 发现问题" if count > 0 else "✓ 正常"
            self.log_result("问题检测", name, query, count, elapsed, note)
    
    def test_query_limits(self):
        """测试查询限制"""
        print("\n" + "="*70)
        print("测试: 查询限制边界")
        print("="*70)
        
        limit_tests = [
            ("LIMIT 10", "SELECT * FROM std LIMIT 10", 10),
            ("LIMIT 1000", "SELECT * FROM std LIMIT 1000", 1000),
            ("LIMIT 10000", "SELECT * FROM std LIMIT 10000", 10000),
            ("OFFSET大值", "SELECT * FROM std LIMIT 10 OFFSET 1000000", 10),
        ]
        
        for name, query, expected_max in limit_tests:
            start = datetime.now()
            self.cursor.execute(query)
            rows = self.cursor.fetchall()
            elapsed = (datetime.now() - start).total_seconds()
            note = f"返回{len(rows)}条，期望最多{expected_max}条"
            self.log_result("查询限制", name, query, len(rows), elapsed, note)
    
    def save_results(self):
        """保存测试结果"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        results_file = RESULTS_DIR / f"ai_retrieval_test_{timestamp}.json"
        
        with open(results_file, 'w', encoding='utf-8') as f:
            json.dump(self.test_results, f, ensure_ascii=False, indent=2)
        
        print(f"\n📄 详细测试结果已保存: {results_file}")
        return results_file
    
    def generate_recommendations(self):
        """生成改进建议"""
        print("\n" + "="*70)
        print("改进建议汇总")
        print("="*70)
        
        # 分析测试结果生成建议
        recommendations = []
        
        # 检查模糊查询性能
        fuzzy_results = [r for r in self.test_results if r['category'] == '模糊匹配']
        slow_fuzzy = [r for r in fuzzy_results if r['execution_time'] > 1.0]
        if slow_fuzzy:
            recommendations.append({
                'priority': 'HIGH',
                'issue': '模糊查询性能较慢',
                'details': f"{len(slow_fuzzy)}个模糊查询超过1秒",
                'suggestion': '考虑添加FTS5全文搜索索引，或预先计算常用关键词的搜索结果'
            })
        
        # 检查覆盖率
        low_coverage_fields = ['sex_standardized', 'sample_type_standardized']
        recommendations.append({
            'priority': 'MEDIUM',
            'issue': '标准化字段覆盖率低',
            'details': f"{', '.join(low_coverage_fields)} 覆盖率低于20%",
            'suggestion': '使用AI批量推断填充缺失值，或使用规则引擎进行标准化'
        })
        
        # 打印建议
        for i, rec in enumerate(recommendations, 1):
            priority_icon = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}.get(rec['priority'], "⚪")
            print(f"\n{i}. {priority_icon} [{rec['priority']}] {rec['issue']}")
            print(f"   问题: {rec['details']}")
            print(f"   建议: {rec['suggestion']}")
        
        return recommendations

def main():
    print("="*70)
    print("AI检索功能测试")
    print(f"数据库: {DB_PATH}")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*70)
    
    tester = QueryTester()
    
    try:
        tester.test_standardized_field_queries()
        tester.test_complex_combinations()
        tester.test_fuzzy_and_partial()
        tester.test_range_queries()
        tester.test_boolean_filters()
        tester.test_aggregation_queries()
        tester.test_sample_data_preview()
        tester.test_potential_issues()
        tester.test_query_limits()
        
        recommendations = tester.generate_recommendations()
        
    finally:
        tester.save_results()
        tester.close()
    
    print("\n" + "="*70)
    print("测试完成!")
    print("="*70)

if __name__ == "__main__":
    main()
