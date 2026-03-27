"""
数据下载模块测试
"""

import pytest
import pandas as pd
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import sys

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.data_downloader import (
    DataDownloader, DownloadTask, GEODownloader, 
    CellxGeneDownloader, SRADownloader
)


class TestDownloadTask:
    """测试下载任务类"""
    
    def test_task_creation(self):
        """测试任务创建"""
        task = DownloadTask(
            task_id="test123",
            sample_uid="SAMPLE001",
            project_id="GSE12345",
            database="GEO",
            download_url="https://example.com/data.h5ad",
            target_path=Path("/tmp/test.h5ad"),
            file_type="matrix",
            file_format="h5ad"
        )
        
        assert task.task_id == "test123"
        assert task.status == "pending"
        assert task.progress == 0.0
        assert task.retry_count == 0
    
    def test_task_to_dict(self):
        """测试任务序列化"""
        task = DownloadTask(
            task_id="test123",
            sample_uid="SAMPLE001",
            project_id="GSE12345",
            database="GEO",
            download_url="https://example.com/data.h5ad",
            target_path=Path("/tmp/test.h5ad"),
            file_type="matrix",
            file_format="h5ad"
        )
        
        data = task.to_dict()
        assert data['task_id'] == "test123"
        assert data['database'] == "GEO"
        assert data['status'] == "pending"
        assert 'created_at' in data


class TestGEODownloader:
    """测试GEO下载器"""
    
    def test_can_handle(self):
        """测试数据库识别"""
        config = {'timeout': 300}
        downloader = GEODownloader(config)
        
        assert downloader.can_handle("GEO")
        assert downloader.can_handle("Gene Expression Omnibus")
        assert not downloader.can_handle("SRA")
    
    def test_extract_geo_accession(self):
        """测试GEO编号提取"""
        config = {'timeout': 300}
        downloader = GEODownloader(config)
        
        assert downloader._extract_geo_accession("GSE12345") == "GSE12345"
        assert downloader._extract_geo_accession("some_GSE12345_text") == "GSE12345"
        assert downloader._extract_geo_accession("gse12345") == "GSE12345"
        assert downloader._extract_geo_accession("invalid") is None


class TestCellxGeneDownloader:
    """测试CellxGene下载器"""
    
    def test_can_handle(self):
        """测试数据库识别"""
        config = {'timeout': 300}
        downloader = CellxGeneDownloader(config)
        
        assert downloader.can_handle("CellxGene")
        assert downloader.can_handle("CELLXGENE")
        assert downloader.can_handle("CZ CELLXGENE")
        assert not downloader.can_handle("GEO")


class TestSRADownloader:
    """测试SRA下载器"""
    
    def test_can_handle(self):
        """测试数据库识别"""
        config = {'timeout': 300}
        downloader = SRADownloader(config)
        
        assert downloader.can_handle("SRA")
        assert downloader.can_handle("Sequence Read Archive")
        assert downloader.can_handle("NCBI SRA")
        assert not downloader.can_handle("GEO")
    
    def test_extract_sra_accession(self):
        """测试SRA编号提取"""
        config = {'timeout': 300}
        downloader = SRADownloader(config)
        
        assert downloader._extract_sra_accession("SRP12345") == "SRP12345"
        assert downloader._extract_sra_accession("ERP12345") == "ERP12345"
        assert downloader._extract_sra_accession("DRP12345") == "DRP12345"
        assert downloader._extract_sra_accession("invalid") is None


class TestDataDownloader:
    """测试数据下载管理器"""
    
    @pytest.fixture
    def config(self):
        return {
            'download_dir': '/tmp/test_downloads',
            'max_concurrent_downloads': 2,
            'retry_attempts': 2,
            'timeout': 300,
            'chunk_size': 8192
        }
    
    @pytest.fixture
    def sample_records(self):
        """创建测试数据记录"""
        return pd.DataFrame([
            {
                'sample_uid': 'SAMPLE001',
                'project_id_primary': 'GSE12345',
                'database_standardized': 'GEO',
                'source_database': 'GEO',
                'title': 'Test Dataset 1',
                'access_link': 'https://example.com/data1.h5ad',
                'file_type': 'h5ad'
            },
            {
                'sample_uid': 'SAMPLE002',
                'project_id_primary': 'collection-abc',
                'database_standardized': 'CellxGene',
                'source_database': 'CellxGene',
                'title': 'Test Dataset 2',
                'access_link': 'https://example.com/data2.h5ad',
                'file_type': 'h5ad'
            },
            {
                'sample_uid': 'SAMPLE003',
                'project_id_primary': 'SRP12345',
                'database_standardized': 'SRA',
                'source_database': 'SRA',
                'title': 'Test Dataset 3',
                'access_link': None,
                'file_type': 'fastq'
            }
        ])
    
    def test_create_download_tasks(self, config, sample_records):
        """测试创建下载任务"""
        downloader = DataDownloader(config)
        
        tasks = downloader.create_download_tasks(
            sample_records,
            file_types=['matrix'],
            output_dir='/tmp/test_output'
        )
        
        assert len(tasks) == 3  # 3条记录 × 1种文件类型
        
        # 检查任务属性
        task = tasks[0]
        assert task.sample_uid == 'SAMPLE001'
        assert task.project_id == 'GSE12345'
        assert task.database == 'GEO'
        assert task.file_type == 'matrix'
        assert task.file_format == 'h5ad'
    
    def test_create_download_tasks_multiple_types(self, config, sample_records):
        """测试创建多种文件类型的下载任务"""
        downloader = DataDownloader(config)
        
        tasks = downloader.create_download_tasks(
            sample_records,
            file_types=['matrix', 'raw'],
            output_dir='/tmp/test_output'
        )
        
        assert len(tasks) == 6  # 3条记录 × 2种文件类型
    
    def test_get_downloader(self, config):
        """测试获取适合的下载器"""
        downloader = DataDownloader(config)
        
        geo_downloader = downloader._get_downloader('GEO')
        assert isinstance(geo_downloader, GEODownloader)
        
        cxg_downloader = downloader._get_downloader('CellxGene')
        assert isinstance(cxg_downloader, CellxGeneDownloader)
        
        sra_downloader = downloader._get_downloader('SRA')
        assert isinstance(sra_downloader, SRADownloader)
    
    def test_build_target_path(self, config):
        """测试目标路径构建"""
        downloader = DataDownloader(config)
        
        path = downloader._build_target_path(
            Path('/tmp/downloads'),
            'GEO',
            'GSE12345',
            'SAMPLE_001',
            'matrix',
            'h5ad'
        )
        
        assert 'GEO' in str(path)
        assert 'GSE12345' in str(path)
        assert path.suffix == '.h5ad'
    
    def test_build_target_path_special_chars(self, config):
        """测试特殊字符处理"""
        downloader = DataDownloader(config)
        
        path = downloader._build_target_path(
            Path('/tmp/downloads'),
            'GEO/Database',
            'GSE12345:test',
            'SAMPLE@001#test',
            'matrix',
            'h5ad'
        )
        
        # 特殊字符应该被替换
        assert '/' not in path.stem
        assert ':' not in path.stem
        assert '@' not in path.stem
        assert '#' not in path.stem
    
    def test_export_download_list(self, config, sample_records, tmp_path):
        """测试导出下载列表"""
        downloader = DataDownloader(config)
        
        tasks = downloader.create_download_tasks(sample_records)
        output_path = tmp_path / 'download_list.csv'
        
        result_path = downloader.export_download_list(tasks, str(output_path))
        
        assert Path(result_path).exists()
        
        # 验证CSV内容
        df = pd.read_csv(result_path)
        assert len(df) == 3
        assert 'task_id' in df.columns
        assert 'project_id' in df.columns
        assert 'database' in df.columns
    
    @patch('ftplib.FTP')
    def test_geo_get_download_info(self, mock_ftp_class, config):
        """测试GEO下载信息获取"""
        # 模拟FTP响应
        mock_ftp = MagicMock()
        mock_ftp_class.return_value.__enter__.return_value = mock_ftp
        mock_ftp.nlst.return_value = [
            'GSE12345_matrix.mtx.gz',
            'GSE12345_barcodes.tsv.gz',
            'GSE12345_features.tsv.gz',
            'GSE12345_metadata.txt.gz'
        ]
        
        downloader = GEODownloader(config)
        info = downloader.get_download_info('GSE12345', 'matrix')
        
        assert info['project_id'] == 'GSE12345'
        assert info['database'] == 'GEO'
        assert len(info['urls']) > 0
        
        # 检查文件分类
        url_types = [u['type'] for u in info['urls']]
        assert 'matrix' in url_types
    
    def test_generate_download_script(self, config, sample_records, tmp_path):
        """测试生成下载脚本"""
        downloader = DataDownloader(config)
        
        tasks = downloader.create_download_tasks(sample_records)
        script_path = tmp_path / 'download.sh'
        
        result_path = downloader.generate_download_script(tasks, str(script_path))
        
        assert Path(result_path).exists()
        
        # 验证脚本内容
        content = Path(result_path).read_text()
        assert '#!/bin/bash' in content
        assert 'wget' in content
        assert 'GSE12345' in content or 'collection-abc' in content or 'SRP12345' in content


class TestDownloadIntegration:
    """集成测试"""
    
    def test_full_download_workflow(self):
        """测试完整下载流程（使用mock）"""
        config = {
            'download_dir': '/tmp/test_integration',
            'max_concurrent_downloads': 1,
            'retry_attempts': 1,
            'timeout': 300,
            'chunk_size': 8192
        }
        
        # 创建测试数据
        records = pd.DataFrame([
            {
                'sample_uid': 'TEST001',
                'project_id_primary': 'GSE99999',
                'database_standardized': 'GEO',
                'source_database': 'GEO',
                'title': 'Integration Test',
                'access_link': 'https://test.example.com/data.h5ad',
                'file_type': 'h5ad'
            }
        ])
        
        downloader = DataDownloader(config)
        
        # 创建任务
        tasks = downloader.create_download_tasks(records, file_types=['matrix'])
        assert len(tasks) == 1
        
        # 验证任务属性
        task = tasks[0]
        assert task.sample_uid == 'TEST001'
        assert task.status == 'pending'
        
        # 生成脚本
        script_path = downloader.generate_download_script(tasks)
        assert script_path.exists()
        
        # 导出列表
        list_path = downloader.export_download_list(tasks)
        assert list_path.exists()
        
        # 清理
        downloader.shutdown()


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
