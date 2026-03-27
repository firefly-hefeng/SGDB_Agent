"""
增强版系统单元测试
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import unittest
from src.schema_knowledge_base import SchemaKnowledgeBase, FieldKnowledge
from src.adaptive_query_engine import AdaptiveQueryEngine, QueryStrategy
from src.db_manager import DatabaseManager


class TestSchemaKnowledgeBase(unittest.TestCase):
    """测试Schema知识库"""
    
    @classmethod
    def setUpClass(cls):
        cls.kb = SchemaKnowledgeBase("data/scrnaseq.db")
    
    def test_field_statistics(self):
        """测试字段统计"""
        stats = self.kb.get_field_statistics("disease_clean")
        self.assertIsNotNone(stats)
        self.assertGreater(stats.total_records, 0)
        self.assertIsNotNone(stats.semantic_type)
    
    def test_find_similar_values(self):
        """测试相似值查找"""
        similar = self.kb.find_similar_values("tissue_clean", "brain", top_k=5)
        self.assertIsInstance(similar, list)
        
        if similar:
            # 应该找到 "Brain"
            values = [v for v, _ in similar]
            self.assertIn("Brain", values)
    
    def test_semantic_fields(self):
        """测试语义字段获取"""
        disease_fields = self.kb.get_semantic_fields("disease")
        self.assertIn("disease_clean", disease_fields)
        
        tissue_fields = self.kb.get_semantic_fields("tissue")
        self.assertIn("tissue_clean", tissue_fields)
    
    def test_estimate_result_count(self):
        """测试结果数估算"""
        filters = {
            'exact_match': {'disease_clean': 'COVID-19'},
            'partial_match': {},
            'boolean_match': {},
            'range_match': {}
        }
        
        estimate = self.kb.estimate_result_count(filters)
        # COVID-19 应该有约7万条
        self.assertGreater(estimate, 70000)
    
    def test_detect_conflicts(self):
        """测试冲突检测"""
        # 过度约束的例子
        filters = {
            'exact_match': {},
            'partial_match': {
                'tissue_clean': 'Brain',
                'tissue_location': 'Brain',  # 冗余
                'tissue_standardized': 'Brain'  # 冗余
            }
        }
        
        conflicts = self.kb.detect_conflicting_conditions(filters)
        # 应该检测到tissue类型的多个字段
        self.assertTrue(any('tissue' in str(c.get('fields', [])).lower() 
                           for c in conflicts))


class TestAdaptiveQueryEngine(unittest.TestCase):
    """测试自适应查询引擎"""
    
    @classmethod
    def setUpClass(cls):
        config = {'path': 'data/scrnaseq.db', 'table_name': 'std'}
        cls.db_manager = DatabaseManager(config)
        cls.db_manager.connect()
        
        cls.kb = SchemaKnowledgeBase("data/scrnaseq.db")
        cls.engine = AdaptiveQueryEngine(cls.db_manager, cls.kb)
    
    @classmethod
    def tearDownClass(cls):
        cls.db_manager.close()
    
    def test_analyze_filters(self):
        """测试过滤条件分析"""
        filters = {
            'exact_match': {'disease_clean': 'COVID-19'},
            'partial_match': {},
            'boolean_match': {},
            'range_match': {}
        }
        
        analysis = self.engine._analyze_filters(filters)
        self.assertIn('risk_level', analysis)
        self.assertIn('estimated_count', analysis)
    
    def test_select_initial_strategy(self):
        """测试策略选择"""
        # 低风险分析
        low_risk = {'risk_level': 'low', 'estimated_count': 10000}
        strategy = self.engine._select_initial_strategy(low_risk)
        self.assertEqual(strategy, QueryStrategy.EXACT)
        
        # 高风险分析
        high_risk = {'risk_level': 'high', 'estimated_count': 5}
        strategy = self.engine._select_initial_strategy(high_risk)
        self.assertEqual(strategy, QueryStrategy.FUZZY)
    
    def test_apply_strategy(self):
        """测试策略应用"""
        original = {
            'exact_match': {},
            'partial_match': {
                'tissue_clean': 'Brain',
                'tissue_location': 'Brain'
            }
        }
        
        analysis = {'risk_level': 'high', 'estimated_count': 0}
        
        # EXACT策略应该只保留一个字段
        optimized = self.engine._apply_strategy(
            original, QueryStrategy.EXACT, analysis
        )
        
        tissue_fields = [f for f in optimized.get('partial_match', {}).keys()
                        if 'tissue' in f]
        self.assertEqual(len(tissue_fields), 1)
    
    def test_relax_strategy(self):
        """测试策略放宽"""
        self.assertEqual(
            self.engine._relax_strategy(QueryStrategy.EXACT, 1),
            QueryStrategy.STANDARD
        )
        self.assertEqual(
            self.engine._relax_strategy(QueryStrategy.STANDARD, 1),
            QueryStrategy.FUZZY
        )
        # 不能更宽松了
        self.assertEqual(
            self.engine._relax_strategy(QueryStrategy.SEMANTIC, 1),
            QueryStrategy.SEMANTIC
        )


class TestIntegration(unittest.TestCase):
    """集成测试"""
    
    @classmethod
    def setUpClass(cls):
        from src.config_manager import ConfigManager
        from src.enhanced_query_engine import EnhancedQueryEngine
        
        cls.config = ConfigManager("config/config.yaml")
        cls.engine = EnhancedQueryEngine(cls.config)
        cls.engine.initialize()
    
    @classmethod
    def tearDownClass(cls):
        cls.engine.cleanup()
    
    def test_end_to_end_query(self):
        """测试端到端查询"""
        result = self.engine.execute_query(
            "COVID-19",
            adaptive=True
        )
        
        self.assertIn('results', result)
        self.assertIn('total_count', result)
        self.assertIn('filters', result)
        
        # COVID-19应该有大量结果
        self.assertGreater(result['total_count'], 70000)
    
    def test_field_insights(self):
        """测试字段洞察"""
        insights = self.engine.get_field_insights("disease_clean")
        
        self.assertIn('field_name', insights)
        self.assertIn('data_quality', insights)
        self.assertIn('value_distribution', insights)
        
        self.assertEqual(insights['field_name'], 'disease_clean')
    
    def test_find_similar_values(self):
        """测试相似值查找API"""
        similar = self.engine.find_similar_values(
            "tissue_clean", "brain", top_k=5
        )
        
        self.assertIsInstance(similar, list)
        if similar:
            self.assertIn('value', similar[0])
            self.assertIn('similarity', similar[0])
            self.assertIn('count', similar[0])
    
    def test_smart_search(self):
        """测试智能概念搜索"""
        result = self.engine.smart_search({
            "disease": "covid-19"
        }, limit=10)
        
        self.assertIn('results', result)
        self.assertIn('total_count', result)
        self.assertIn('strategy_confidence', result)


def run_tests():
    """运行测试"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # 添加测试类
    suite.addTests(loader.loadTestsFromTestCase(TestSchemaKnowledgeBase))
    suite.addTests(loader.loadTestsFromTestCase(TestAdaptiveQueryEngine))
    suite.addTests(loader.loadTestsFromTestCase(TestIntegration))
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return result.wasSuccessful()


if __name__ == '__main__':
    success = run_tests()
    sys.exit(0 if success else 1)
