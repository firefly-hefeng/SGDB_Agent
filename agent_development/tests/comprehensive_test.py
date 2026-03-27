#!/usr/bin/env python3
"""
单细胞数据库检索系统 - 综合测试脚本
测试功能上限、边界条件和性能
"""

import sys
import time
import json
import sqlite3
import pandas as pd
from pathlib import Path
from datetime import datetime

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# 注意: 避免导入需要yaml的模块
# from src.config_manager import ConfigManager
# from src.db_manager import DatabaseManager

# 测试配置
DB_PATH = project_root / "data" / "scrnaseq.db"
RESULTS_DIR = project_root / "tests" / "test_results"
RESULTS_DIR.mkdir(exist_ok=True)

# 测试日志
TEST_LOG = []

def log_test(test_name, status, details=None, execution_time=None):
    """记录测试结果"""
    entry = {
        'timestamp': datetime.now().isoformat(),
        'test_name': test_name,
        'status': status,
        'details': details,
        'execution_time': execution_time
    }
    TEST_LOG.append(entry)
    status_icon = "✅" if status == "PASS" else "❌" if status == "FAIL" else "⚠️"
    time_str = f" ({execution_time:.2f}s)" if execution_time else ""
    print(f"{status_icon} {test_name}{time_str}")
    if details and status != "PASS":
        print(f"   Details: {details}")

def save_test_results():
    """保存测试结果到文件"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    results_file = RESULTS_DIR / f"test_results_{timestamp}.json"
    
    with open(results_file, 'w', encoding='utf-8') as f:
        json.dump(TEST_LOG, f, ensure_ascii=False, indent=2)
    
    print(f"\n📄 测试结果已保存到: {results_file}")
    return results_file

class DatabaseTester:
    """数据库测试器"""
    
    def __init__(self):
        self.conn = sqlite3.connect(DB_PATH)
        self.cursor = self.conn.cursor()
        self.total_records = self._get_total_records()
        
    def _get_total_records(self):
        """获取总记录数"""
        self.cursor.execute("SELECT COUNT(*) FROM std")
        return self.cursor.fetchone()[0]
    
    def close(self):
        """关闭连接"""
        self.conn.close()
    
    def test_basic_connectivity(self):
        """测试1: 基本连接"""
        print("\n" + "="*60)
        print("测试1: 数据库基本连接")
        print("="*60)
        
        try:
            self.cursor.execute("SELECT 1")
            log_test("数据库连接", "PASS")
            return True
        except Exception as e:
            log_test("数据库连接", "FAIL", str(e))
            return False
    
    def test_schema_integrity(self):
        """测试2: Schema完整性"""
        print("\n" + "="*60)
        print("测试2: Schema完整性检查")
        print("="*60)
        
        self.cursor.execute("PRAGMA table_info(std)")
        columns = {row[1]: row[2] for row in self.cursor.fetchall()}
        
        # 检查关键字段
        required_fields = {
            'project_id_primary': 'TEXT',
            'disease_standardized': 'TEXT',
            'platform_standardized': 'TEXT',
            'matrix_open': 'REAL',
        }
        
        all_pass = True
        for field, expected_type in required_fields.items():
            if field in columns:
                log_test(f"字段存在: {field}", "PASS")
            else:
                log_test(f"字段存在: {field}", "FAIL", f"期望类型: {expected_type}")
                all_pass = False
        
        print(f"\n总字段数: {len(columns)}")
        return all_pass
    
    def test_data_quality(self):
        """测试3: 数据质量检查"""
        print("\n" + "="*60)
        print("测试3: 数据质量检查")
        print("="*60)
        
        checks = [
            ("NULL值检查: disease_standardized", 
             "SELECT COUNT(*) FROM std WHERE disease_standardized IS NULL"),
            ("空字符串检查: platform_standardized", 
             "SELECT COUNT(*) FROM std WHERE platform_standardized = ''"),
            ("重复样本检查", 
             "SELECT COUNT(*) FROM std WHERE is_duplicate = 1"),
            ("高质量元数据", 
             "SELECT COUNT(*) FROM std WHERE metadata_quality_score = 'High'"),
        ]
        
        results = {}
        for check_name, query in checks:
            start = time.time()
            self.cursor.execute(query)
            count = self.cursor.fetchone()[0]
            elapsed = time.time() - start
            
            percentage = (count / self.total_records * 100) if self.total_records > 0 else 0
            results[check_name] = {'count': count, 'percentage': percentage}
            log_test(check_name, "PASS", f"{count:,} 条 ({percentage:.2f}%)", elapsed)
        
        return results
    
    def test_standardized_fields(self):
        """测试4: 标准化字段覆盖度"""
        print("\n" + "="*60)
        print("测试4: 标准化字段覆盖度")
        print("="*60)
        
        standardized_fields = [
            'sex_standardized', 'disease_standardized', 'platform_standardized',
            'sample_type_standardized', 'tissue_standardized', 'database_standardized',
            'open_status_standardized'
        ]
        
        coverage_results = {}
        for field in standardized_fields:
            # 计算非Unknown/NULL的覆盖率
            query = f'''
                SELECT 
                    COUNT(CASE WHEN "{field}" IS NOT NULL 
                               AND "{field}" != '' 
                               AND "{field}" != 'Unknown' THEN 1 END) as valid,
                    COUNT(*) as total
                FROM std
            '''
            self.cursor.execute(query)
            valid, total = self.cursor.fetchone()
            coverage = (valid / total * 100) if total > 0 else 0
            coverage_results[field] = coverage
            
            status = "PASS" if coverage > 50 else "WARN" if coverage > 20 else "FAIL"
            log_test(f"{field} 覆盖率", status, f"{valid:,}/{total:,} ({coverage:.1f}%)")
        
        return coverage_results
    
    def test_query_performance(self):
        """测试5: 查询性能测试"""
        print("\n" + "="*60)
        print("测试5: 查询性能测试")
        print("="*60)
        
        test_queries = [
            ("简单精确查询", 
             'SELECT * FROM std WHERE database_standardized = "GEO" LIMIT 100'),
            ("多条件查询", 
             '''SELECT * FROM std 
                WHERE disease_standardized = "COVID-19" 
                AND matrix_open = 1 
                LIMIT 100'''),
            ("模糊查询", 
             'SELECT * FROM std WHERE title LIKE "%cancer%" LIMIT 100'),
            ("聚合查询", 
             'SELECT platform_standardized, COUNT(*) FROM std GROUP BY platform_standardized'),
            ("排序查询", 
             'SELECT * FROM std ORDER BY citation_count DESC LIMIT 100'),
            ("联合查询", 
             '''SELECT * FROM std 
                WHERE disease_category = "Cancer" 
                AND sex_standardized = "Female"
                AND platform_standardized LIKE "%10x%"
                LIMIT 100'''),
        ]
        
        performance_results = {}
        for test_name, query in test_queries:
            times = []
            for _ in range(3):  # 执行3次取平均
                start = time.time()
                self.cursor.execute(query)
                self.cursor.fetchall()
                times.append(time.time() - start)
            
            avg_time = sum(times) / len(times)
            performance_results[test_name] = avg_time
            
            status = "PASS" if avg_time < 1.0 else "WARN" if avg_time < 5.0 else "FAIL"
            log_test(f"性能: {test_name}", status, f"平均: {avg_time:.3f}s")
        
        return performance_results
    
    def test_field_uniqueness(self):
        """测试6: 字段唯一值统计"""
        print("\n" + "="*60)
        print("测试6: 字段唯一值统计")
        print("="*60)
        
        fields_to_check = [
            'disease_standardized', 'platform_standardized', 
            'database_standardized', 'sample_type_standardized'
        ]
        
        uniqueness_results = {}
        for field in fields_to_check:
            query = f'SELECT COUNT(DISTINCT "{field}") FROM std'
            self.cursor.execute(query)
            unique_count = self.cursor.fetchone()[0]
            uniqueness_results[field] = unique_count
            log_test(f"{field} 唯一值", "PASS", f"{unique_count:,} 个")
        
        return uniqueness_results
    
    def test_edge_cases(self):
        """测试7: 边界情况"""
        print("\n" + "="*60)
        print("测试7: 边界情况测试")
        print("="*60)
        
        edge_cases = [
            ("超大LIMIT", "SELECT * FROM std LIMIT 100000"),
            ("特殊字符", "SELECT * FROM std WHERE title LIKE '%/%' LIMIT 10"),
            ("空结果查询", "SELECT * FROM std WHERE disease_standardized = 'XYZ_NONEXISTENT'"),
            ("NULL处理", "SELECT * FROM std WHERE sex_standardized IS NULL LIMIT 10"),
            ("范围查询", "SELECT * FROM std WHERE age_numeric BETWEEN 20 AND 30 LIMIT 100"),
        ]
        
        for test_name, query in edge_cases:
            try:
                start = time.time()
                self.cursor.execute(query)
                result = self.cursor.fetchall()
                elapsed = time.time() - start
                log_test(f"边界: {test_name}", "PASS", f"返回 {len(result)} 条", elapsed)
            except Exception as e:
                log_test(f"边界: {test_name}", "FAIL", str(e))
    
    def test_index_usage(self):
        """测试8: 索引使用情况"""
        print("\n" + "="*60)
        print("测试8: 索引检查")
        print("="*60)
        
        self.cursor.execute("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='std'")
        indexes = [row[0] for row in self.cursor.fetchall()]
        
        print(f"\n共有 {len(indexes)} 个索引:")
        for idx in indexes:
            print(f"  • {idx}")
        
        # 检查关键索引是否存在
        expected_indexes = [
            'idx_disease_standardized', 'idx_platform_standardized',
            'idx_sex_standardized', 'idx_database_standardized'
        ]
        
        for idx in expected_indexes:
            if idx in indexes:
                log_test(f"索引存在: {idx}", "PASS")
            else:
                log_test(f"索引存在: {idx}", "WARN", "建议添加")
        
        return indexes
    
    def generate_summary_report(self):
        """生成测试总结报告"""
        print("\n" + "="*60)
        print("测试总结报告")
        print("="*60)
        
        pass_count = sum(1 for t in TEST_LOG if t['status'] == 'PASS')
        warn_count = sum(1 for t in TEST_LOG if t['status'] == 'WARN')
        fail_count = sum(1 for t in TEST_LOG if t['status'] == 'FAIL')
        
        print(f"\n总计: {len(TEST_LOG)} 项测试")
        print(f"  ✅ 通过: {pass_count}")
        print(f"  ⚠️  警告: {warn_count}")
        print(f"  ❌ 失败: {fail_count}")
        
        # 数据分布统计
        print("\n" + "-"*60)
        print("数据分布统计:")
        print("-"*60)
        
        queries = [
            ("数据来源分布", 'database_standardized'),
            ("疾病分类分布", 'disease_category'),
            ("性别分布", 'sex_standardized'),
            ("数据开放状态", 'open_status_standardized'),
        ]
        
        for label, field in queries:
            print(f"\n{label}:")
            self.cursor.execute(f'''
                SELECT "{field}", COUNT(*) as cnt 
                FROM std 
                WHERE "{field}" IS NOT NULL AND "{field}" != '' AND "{field}" != 'Unknown'
                GROUP BY "{field}" 
                ORDER BY cnt DESC 
                LIMIT 5
            ''')
            for row in self.cursor.fetchall():
                value, count = row
                percentage = count / self.total_records * 100
                print(f"  {value}: {count:,} ({percentage:.2f}%)")

def main():
    """主测试函数"""
    print("="*60)
    print("单细胞数据库检索系统 - 综合测试")
    print(f"数据库路径: {DB_PATH}")
    print(f"测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)
    
    tester = DatabaseTester()
    print(f"\n数据库总记录数: {tester.total_records:,}")
    
    try:
        # 执行所有测试
        tester.test_basic_connectivity()
        tester.test_schema_integrity()
        tester.test_data_quality()
        tester.test_standardized_fields()
        tester.test_query_performance()
        tester.test_field_uniqueness()
        tester.test_edge_cases()
        tester.test_index_usage()
        
        # 生成总结报告
        tester.generate_summary_report()
        
    finally:
        tester.close()
    
    # 保存测试结果
    results_file = save_test_results()
    
    print("\n" + "="*60)
    print("测试完成!")
    print("="*60)

if __name__ == "__main__":
    main()
