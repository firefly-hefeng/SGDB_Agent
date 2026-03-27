import unittest
import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config_manager import ConfigManager
from src.query_engine import QueryEngine

class TestQueryAccuracy(unittest.TestCase):
    """查询准确性测试"""
    
    @classmethod
    def setUpClass(cls):
        """初始化测试环境"""
        cls.config = ConfigManager('config/config.yaml')
        cls.engine = QueryEngine(cls.config)
        cls.engine.initialize()
    
    @classmethod
    def tearDownClass(cls):
        """清理资源"""
        cls.engine.cleanup()
    
    def test_simple_disease_query(self):
        """测试简单疾病查询"""
        query = "查找肺癌相关数据"
        result = self.engine.execute_query(query, limit=10)
        
        # 验证返回了结果
        self.assertGreater(result['total_count'], 0, "应该找到肺癌相关数据")
        
        # 验证过滤条件包含disease相关字段
        filters = result['filters']
        has_disease_filter = (
            'disease' in filters.get('partial_match', {}) or
            'disease_general' in filters.get('exact_match', {})
        )
        self.assertTrue(has_disease_filter, "应该包含疾病过滤条件")
    
    def test_open_data_query(self):
        """测试开放数据查询"""
        query = "查找开放的单细胞数据"
        result = self.engine.execute_query(query, limit=10)
        
        # 验证过滤条件包含开放性字段
        filters = result['filters']
        boolean_match = filters.get('boolean_match', {})
        
        self.assertTrue(
            'matrix_open' in boolean_match or 'raw_open' in boolean_match,
            "应该包含数据开放性过滤条件"
        )
    
    def test_platform_query(self):
        """测试测序平台查询"""
        query = "10x Genomics平台的数据"
        result = self.engine.execute_query(query, limit=10)
        
        # 验证过滤条件包含平台字段
        filters = result['filters']
        partial_match = filters.get('partial_match', {})
        
        self.assertIn('sequencing_platform', partial_match, "应该包含测序平台过滤条件")
        self.assertIn('10x', partial_match['sequencing_platform'].lower(), "平台应该匹配10x")
    
    def test_complex_query(self):
        """测试复杂组合查询"""
        query = "查找2022年以后发表的、开放的、10x平台的肺癌数据"
        result = self.engine.execute_query(query, limit=10)
        
        filters = result['filters']
        
        # 验证包含疾病过滤
        self.assertTrue(
            'disease' in filters.get('partial_match', {}) or
            'disease_general' in filters.get('exact_match', {}),
            "应该包含疾病条件"
        )
        
        # 验证包含开放性过滤
        self.assertTrue(
            'matrix_open' in filters.get('boolean_match', {}),
            "应该包含开放性条件"
        )
        
        # 验证包含平台过滤
        self.assertIn(
            'sequencing_platform',
            filters.get('partial_match', {}),
            "应该包含平台条件"
        )
    
    def test_refinement_query(self):
        """测试连续精化查询"""
        # 第一次查询
        query1 = "查找癌症数据"
        result1 = self.engine.execute_query(query1, session_id='test_session')
        
        # 精化查询
        query2 = "只要肺癌的"
        result2 = self.engine.execute_query(query2, session_id='test_session')
        
        # 验证第二次查询结果更少
        self.assertLessEqual(
            result2['total_count'], 
            result1['total_count'],
            "精化查询应该返回更少的结果"
        )
    
    def test_aggregation_query(self):
        """测试聚合统计查询"""
        query = "统计疾病分布"
        result = self.engine.execute_query(query, limit=10)
        
        # 验证返回了统计信息
        self.assertEqual(result.get('query_type'), 'aggregation', "应该识别为聚合查询")
        self.assertIn('statistics', result, "应该包含统计信息")
        self.assertIsNotNone(result['statistics'], "统计信息不应为空")


class TestQueryPerformance(unittest.TestCase):
    """查询性能测试"""
    
    @classmethod
    def setUpClass(cls):
        cls.config = ConfigManager('config/config.yaml')
        cls.engine = QueryEngine(cls.config)
        cls.engine.initialize()
    
    @classmethod
    def tearDownClass(cls):
        cls.engine.cleanup()
    
    def test_simple_query_latency(self):
        """测试简单查询延迟"""
        query = "查找肺癌数据"
        result = self.engine.execute_query(query, limit=20)
        
        # 验证执行时间在合理范围内
        self.assertLess(result['execution_time'], 5.0, "简单查询应在5秒内完成")
    
    def test_complex_query_latency(self):
        """测试复杂查询延迟"""
        query = "查找2020-2023年发表的、开放的、10x平台的免疫相关疾病数据"
        result = self.engine.execute_query(query, limit=20)
        
        # 验证执行时间
        self.assertLess(result['execution_time'], 10.0, "复杂查询应在10秒内完成")


if __name__ == '__main__':
    # 运行测试
    unittest.main(verbosity=2)