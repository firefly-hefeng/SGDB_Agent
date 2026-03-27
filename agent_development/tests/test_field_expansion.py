import unittest
import sys
import pandas as pd
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config_manager import ConfigManager
from src.query_engine import QueryEngine

class TestFieldExpansion(unittest.TestCase):
    """字段扩展功能测试"""
    
    @classmethod
    def setUpClass(cls):
        cls.config = ConfigManager('config/config.yaml')
        cls.engine = QueryEngine(cls.config)
        cls.engine.initialize()
    
    @classmethod
    def tearDownClass(cls):
        cls.engine.cleanup()
    
    def test_field_expansion_basic(self):
        """测试基础字段扩展"""
        # 定义新字段
        field_definition = {
            'field_name': 'test_cancer_related',
            'field_type': 'BOOLEAN',
            'definition': '是否与癌症相关',
            'judgment_criteria': '疾病名称中包含cancer或tumor或carcinoma'
        }
        
        # 准备测试数据
        test_filters = {
            'exact_match': {},
            'partial_match': {},
            'boolean_match': {},
            'range_match': {}
        }
        
        # 执行扩展（限制在小范围测试）
        result = self.engine.expand_field_for_query(
            field_definition,
            test_filters
        )
        
        # 验证扩展结果
        self.assertIn('status', result, "应该返回状态")
        self.assertIn('records_processed', result, "应该返回处理记录数")
        
        # 如果成功，验证更多细节
        if result['status'] == 'completed':
            self.assertGreater(result['records_processed'], 0, "应该处理了一些记录")
            self.assertIn('accuracy_rate', result, "应该包含准确率")
    
    def test_field_metadata_storage(self):
        """测试字段元数据存储"""
        field_name = 'test_field_metadata'
        
        # 保存字段元数据
        self.engine.memory_system.semantic_memory.save_field_metadata({
            'field_name': field_name,
            'field_type': 'TEXT',
            'definition': '测试字段',
            'judgment_criteria': '测试标准',
            'accuracy_rate': 0.95
        })
        
        # 获取字段元数据
        metadata = self.engine.memory_system.semantic_memory.get_field_metadata(field_name)
        
        # 验证
        self.assertIsNotNone(metadata, "应该能够获取元数据")
        self.assertEqual(metadata['field_name'], field_name, "字段名应该匹配")
        self.assertEqual(metadata['accuracy_rate'], 0.95, "准确率应该匹配")
    
    def test_field_usage_tracking(self):
        """测试字段使用追踪"""
        field_name = 'test_usage_tracking'
        
        # 保存字段
        self.engine.memory_system.semantic_memory.save_field_metadata({
            'field_name': field_name,
            'field_type': 'BOOLEAN',
            'definition': '测试使用追踪'
        })
        
        # 增加使用次数
        for _ in range(5):
            self.engine.memory_system.semantic_memory.increment_field_usage(field_name)
        
        # 获取元数据
        metadata = self.engine.memory_system.semantic_memory.get_field_metadata(field_name)
        
        # 验证使用次数
        self.assertEqual(metadata['usage_count'], 5, "使用次数应该为5")


class TestFieldExpansionQuality(unittest.TestCase):
    """字段扩展质量测试"""
    
    @classmethod
    def setUpClass(cls):
        cls.config = ConfigManager('config/config.yaml')
        cls.engine = QueryEngine(cls.config)
        cls.engine.initialize()
    
    @classmethod
    def tearDownClass(cls):
        cls.engine.cleanup()
    
    def test_sampling_validation(self):
        """测试采样验证"""
        # 创建测试数据
        test_data = pd.DataFrame({
            'disease': ['Lung Cancer', 'Diabetes', 'COVID-19', 'Breast Cancer'],
            'tissue_location': ['Lung', 'Pancreas', 'Blood', 'Breast']
        })
        
        field_def = {
            'field_name': 'is_cancer',
            'field_type': 'BOOLEAN',
            'definition': '是否为癌症相关疾病',
            'judgment_criteria': '疾病名称包含Cancer'
        }
        
        # 执行采样验证
        validation_result = self.engine.field_expander._validate_with_sampling(
            field_def,
            test_data
        )
        
        # 验证结果
        self.assertIn('passed', validation_result, "应该有通过状态")
        self.assertIn('accuracy', validation_result, "应该有准确率")
        self.assertGreaterEqual(validation_result['accuracy'], 0.0, "准确率应该>=0")
        self.assertLessEqual(validation_result['accuracy'], 1.0, "准确率应该<=1")


if __name__ == '__main__':
    unittest.main(verbosity=2)