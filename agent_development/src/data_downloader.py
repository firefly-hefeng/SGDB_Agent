"""
数据下载器模块 - 支持各大单细胞数据库的数据下载
支持: GEO, SRA, CellxGene, CNGBdb 等
"""

import os
import re
import json
import logging
import requests
import hashlib
import time
import ftplib
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse, quote
import pandas as pd


@dataclass
class DownloadTask:
    """下载任务"""
    task_id: str
    sample_uid: str
    project_id: str
    database: str
    download_url: Optional[str]
    target_path: Path
    file_type: str  # 'matrix', 'raw', 'metadata', 'supplementary'
    file_format: str  # 'h5ad', 'h5', 'rds', 'csv', 'mtx', 'fastq', etc.
    status: str = 'pending'  # pending, downloading, paused, completed, failed
    progress: float = 0.0
    total_size: int = 0
    downloaded_size: int = 0
    speed: float = 0.0  # bytes/s
    error_message: str = ''
    retry_count: int = 0
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'task_id': self.task_id,
            'sample_uid': self.sample_uid,
            'project_id': self.project_id,
            'database': self.database,
            'download_url': self.download_url,
            'target_path': str(self.target_path),
            'file_type': self.file_type,
            'file_format': self.file_format,
            'status': self.status,
            'progress': self.progress,
            'total_size': self.total_size,
            'downloaded_size': self.downloaded_size,
            'speed': self.speed,
            'error_message': self.error_message,
            'retry_count': self.retry_count,
            'created_at': self.created_at.isoformat(),
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None
        }


class BaseDownloader(ABC):
    """下载器基类"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.logger = logging.getLogger(self.__class__.__name__)
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'SCDB-Agent/2.0 (Bioinformatics Data Download Tool)'
        })
        self.timeout = config.get('timeout', 300)
        self.chunk_size = config.get('chunk_size', 8192)
        
    @abstractmethod
    def can_handle(self, database: str) -> bool:
        """是否能处理该数据库的数据"""
        pass
    
    @abstractmethod
    def get_download_info(self, project_id: str, 
                          file_type: str = 'matrix') -> Dict[str, Any]:
        """获取下载信息（URL、文件列表等）"""
        pass
    
    def download(self, task: DownloadTask, 
                 progress_callback: Optional[Callable] = None) -> bool:
        """
        执行下载
        
        Args:
            task: 下载任务
            progress_callback: 进度回调函数 (task_id, progress, speed)
        
        Returns:
            是否下载成功
        """
        try:
            task.status = 'downloading'
            task.started_at = datetime.now()
            
            if not task.download_url:
                # 获取下载链接
                info = self.get_download_info(task.project_id, task.file_type)
                task.download_url = info.get('url')
                if not task.download_url:
                    raise ValueError(f"无法获取下载链接: {task.project_id}")
            
            # 确保目录存在
            task.target_path.parent.mkdir(parents=True, exist_ok=True)
            
            # 执行下载
            success = self._do_download(task, progress_callback)
            
            if success:
                task.status = 'completed'
                task.progress = 100.0
                task.completed_at = datetime.now()
            else:
                task.status = 'failed'
                
            return success
            
        except Exception as e:
            self.logger.error(f"下载失败 {task.task_id}: {e}")
            task.status = 'failed'
            task.error_message = str(e)
            task.retry_count += 1
            return False
    
    def _do_download(self, task: DownloadTask,
                     progress_callback: Optional[Callable] = None) -> bool:
        """实际下载逻辑（支持断点续传）"""
        temp_path = task.target_path.with_suffix(task.target_path.suffix + '.tmp')
        
        # 检查临时文件，支持断点续传
        downloaded_size = temp_path.stat().st_size if temp_path.exists() else 0
        
        headers = {}
        if downloaded_size > 0:
            headers['Range'] = f'bytes={downloaded_size}-'
            self.logger.info(f"断点续传: {task.task_id} from {downloaded_size} bytes")
        
        try:
            response = self.session.get(
                task.download_url, 
                headers=headers, 
                stream=True, 
                timeout=self.timeout
            )
            response.raise_for_status()
            
            # 获取文件总大小
            if 'Content-Length' in response.headers:
                task.total_size = int(response.headers['Content-Length']) + downloaded_size
            elif 'content-length' in response.headers:
                task.total_size = int(response.headers['content-length']) + downloaded_size
            
            # 下载文件
            mode = 'ab' if downloaded_size > 0 else 'wb'
            last_time = time.time()
            last_size = downloaded_size
            
            with open(temp_path, mode) as f:
                for chunk in response.iter_content(chunk_size=self.chunk_size):
                    if chunk:
                        f.write(chunk)
                        task.downloaded_size += len(chunk)
                        
                        # 计算进度和速度
                        if task.total_size > 0:
                            task.progress = (task.downloaded_size / task.total_size) * 100
                        
                        current_time = time.time()
                        if current_time - last_time >= 1.0:  # 每秒更新一次
                            task.speed = (task.downloaded_size - last_size) / (current_time - last_time)
                            last_time = current_time
                            last_size = task.downloaded_size
                            
                            if progress_callback:
                                progress_callback(task.task_id, task.progress, task.speed)
            
            # 下载完成，移动文件
            temp_path.rename(task.target_path)
            return True
            
        except Exception as e:
            self.logger.error(f"下载错误 {task.task_id}: {e}")
            return False
    
    def _extract_geo_accession(self, project_id: str) -> Optional[str]:
        """提取GEO编号 (GSEXXXXX)"""
        match = re.search(r'GSE\d+', project_id, re.IGNORECASE)
        return match.group(0).upper() if match else None
    
    def _extract_sra_accession(self, project_id: str) -> Optional[str]:
        """提取SRA编号 (SRPXXXXX)"""
        match = re.search(r'(SRP|ERP|DRP)\d+', project_id, re.IGNORECASE)
        return match.group(0).upper() if match else None


class GEODownloader(BaseDownloader):
    """GEO数据库下载器"""
    
    BASE_URL = "https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi"
    FTP_HOST = "ftp.ncbi.nlm.nih.gov"
    
    def can_handle(self, database: str) -> bool:
        return database.upper() in ['GEO', 'GENE EXPRESSION OMNIBUS']
    
    def get_download_info(self, project_id: str, 
                          file_type: str = 'matrix') -> Dict[str, Any]:
        """获取GEO数据下载信息"""
        gse_id = self._extract_geo_accession(project_id)
        if not gse_id:
            raise ValueError(f"无效的GEO编号: {project_id}")
        
        info = {
            'project_id': gse_id,
            'database': 'GEO',
            'urls': [],
            'metadata': {}
        }
        
        # 构建FTP路径
        gse_num = int(gse_id[3:])
        gse_dir = f"geo/series/{gse_id[:-3]}nnn/{gse_id}"
        
        try:
            # 尝试连接FTP获取文件列表
            with ftplib.FTP(self.FTP_HOST) as ftp:
                ftp.login()
                ftp.cwd(f"{gse_dir}/suppl/")
                files = ftp.nlst()
                
                for file in files:
                    file_lower = file.lower()
                    url = f"ftp://{self.FTP_HOST}/{gse_dir}/suppl/{file}"
                    
                    # 分类文件类型
                    if any(ext in file_lower for ext in ['_matrix.mtx', '_barcodes.tsv', '_features.tsv']):
                        info['urls'].append({'url': url, 'type': 'matrix', 'format': 'mtx'})
                    elif file_lower.endswith('.h5') or file_lower.endswith('.h5ad'):
                        info['urls'].append({'url': url, 'type': 'matrix', 'format': 'h5'})
                    elif file_lower.endswith('.rds') or file_lower.endswith('.rda'):
                        info['urls'].append({'url': url, 'type': 'matrix', 'format': 'rds'})
                    elif file_lower.endswith('.txt.gz') or file_lower.endswith('.csv.gz'):
                        info['urls'].append({'url': url, 'type': 'metadata', 'format': 'txt'})
                    elif file_lower.endswith('.tar') or file_lower.endswith('.tar.gz'):
                        info['urls'].append({'url': url, 'type': 'raw', 'format': 'tar'})
                        
        except Exception as e:
            self.logger.warning(f"FTP列表获取失败，使用备用方法: {e}")
            # 备用：使用HTTP链接
            info['urls'].append({
                'url': f"{self.BASE_URL}?acc={gse_id}&targ=suppl",
                'type': 'supplementary',
                'format': 'html'
            })
        
        # 获取元数据
        info['metadata_url'] = f"{self.BASE_URL}?acc={gse_id}&targ=self&form=text"
        
        return info
    
    def download_metadata(self, gse_id: str, target_dir: Path) -> Path:
        """下载GEO元数据"""
        gse_id = self._extract_geo_accession(gse_id)
        metadata_url = f"{self.BASE_URL}?acc={gse_id}&targ=self&form=text"
        
        response = self.session.get(metadata_url, timeout=self.timeout)
        response.raise_for_status()
        
        metadata_path = target_dir / f"{gse_id}_metadata.txt"
        metadata_path.write_text(response.text, encoding='utf-8')
        
        return metadata_path


class CellxGeneDownloader(BaseDownloader):
    """CellxGene数据库下载器"""
    
    API_BASE = "https://api.cellxgene.cziscience.com"
    
    def can_handle(self, database: str) -> bool:
        return database.upper() in ['CELLXGENE', 'CELLXGENE CZISCIENCE', 'CZ CELLXGENE']
    
    def get_download_info(self, project_id: str,
                          file_type: str = 'matrix') -> Dict[str, Any]:
        """获取CellxGene数据下载信息"""
        # CellxGene使用collection_id或dataset_id
        info = {
            'project_id': project_id,
            'database': 'CellxGene',
            'urls': [],
            'metadata': {}
        }
        
        try:
            # 获取collection信息
            collection_url = f"{self.API_BASE}/dp/v1/collections/{project_id}"
            response = self.session.get(collection_url, timeout=self.timeout)
            
            if response.status_code == 200:
                collection_data = response.json()
                info['metadata'] = {
                    'name': collection_data.get('name'),
                    'description': collection_data.get('description'),
                    'datasets': []
                }
                
                # 获取每个dataset的下载链接
                for dataset in collection_data.get('datasets', []):
                    dataset_id = dataset.get('id')
                    assets = dataset.get('dataset_assets', [])
                    
                    for asset in assets:
                        filetype = asset.get('filetype', '')
                        url = asset.get('url')
                        
                        if url:
                            info['urls'].append({
                                'url': url,
                                'type': 'matrix' if filetype in ['H5AD', 'RDS'] else 'raw',
                                'format': filetype.lower(),
                                'dataset_id': dataset_id
                            })
                            
                    info['metadata']['datasets'].append({
                        'id': dataset_id,
                        'name': dataset.get('name')
                    })
            else:
                # 尝试作为dataset_id处理
                dataset_url = f"{self.API_BASE}/dp/v1/datasets/{project_id}/assets"
                response = self.session.get(dataset_url, timeout=self.timeout)
                
                if response.status_code == 200:
                    assets = response.json()
                    for asset in assets:
                        info['urls'].append({
                            'url': asset.get('url'),
                            'type': 'matrix',
                            'format': asset.get('filetype', 'h5ad').lower()
                        })
                        
        except Exception as e:
            self.logger.error(f"获取CellxGene信息失败: {e}")
            raise
        
        return info


class SRADownloader(BaseDownloader):
    """SRA数据库下载器 (使用prefetch/fasterq-dump)"""
    
    def can_handle(self, database: str) -> bool:
        return database.upper() in ['SRA', 'SEQUENCE READ ARCHIVE', 'NCBI SRA']
    
    def get_download_info(self, project_id: str,
                          file_type: str = 'raw') -> Dict[str, Any]:
        """获取SRA数据下载信息"""
        srp_id = self._extract_sra_accession(project_id)
        if not srp_id:
            raise ValueError(f"无效的SRA编号: {project_id}")
        
        info = {
            'project_id': srp_id,
            'database': 'SRA',
            'urls': [],
            'metadata': {},
            'requires_tool': 'sra-toolkit',
            'commands': []
        }
        
        # SRA数据需要使用sra-toolkit工具下载
        # 这里返回使用说明
        info['commands'] = [
            f"prefetch {srp_id}",
            f"fasterq-dump {srp_id} --split-files"
        ]
        
        # 尝试获取元数据
        try:
            eutils_url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
            params = {
                'db': 'sra',
                'term': srp_id,
                'retmode': 'json'
            }
            response = self.session.get(eutils_url, params=params, timeout=self.timeout)
            if response.status_code == 200:
                info['metadata'] = response.json()
        except Exception as e:
            self.logger.warning(f"获取SRA元数据失败: {e}")
        
        return info
    
    def download(self, task: DownloadTask,
                 progress_callback: Optional[Callable] = None) -> bool:
        """
        SRA数据下载需要使用sra-toolkit命令行工具
        这里返回操作指南而不是直接下载
        """
        try:
            task.status = 'downloading'
            task.started_at = datetime.now()
            
            # 创建说明文件
            readme_content = f"""# SRA数据下载指南

项目编号: {task.project_id}
数据库: SRA (Sequence Read Archive)

## 下载步骤

### 1. 安装SRA Toolkit
```bash
# Ubuntu/Debian
sudo apt-get install sra-toolkit

# macOS
brew install sra-toolkit

# 或使用conda
conda install -c bioconda sra-tools
```

### 2. 下载数据
```bash
# 下载SRA文件
prefetch {task.project_id}

# 转换为FASTQ格式
fasterq-dump {task.project_id} --split-files --outdir {task.target_path.parent}

# 或使用并行版本
pfastq-dump -t 8 -s {task.project_id} -O {task.target_path.parent}
```

### 3. 压缩数据（可选）
```bash
gzip {task.target_path.parent}/*.fastq
```

## 参考链接
- https://github.com/ncbi/sra-tools
- https://www.ncbi.nlm.nih.gov/sra/?term={task.project_id}
"""
            
            readme_path = task.target_path.parent / f"{task.project_id}_download_guide.md"
            readme_path.write_text(readme_content, encoding='utf-8')
            
            task.status = 'completed'
            task.progress = 100.0
            task.completed_at = datetime.now()
            
            return True
            
        except Exception as e:
            self.logger.error(f"SRA下载准备失败: {e}")
            task.status = 'failed'
            task.error_message = str(e)
            return False


class CNGBDownloader(BaseDownloader):
    """国家基因库(CNGBdb)下载器"""
    
    API_BASE = "https://db.cngb.org/api"
    
    def can_handle(self, database: str) -> bool:
        return database.upper() in ['CNGB', 'CNGBDB', '国家基因库']
    
    def get_download_info(self, project_id: str,
                          file_type: str = 'matrix') -> Dict[str, Any]:
        """获取CNGBdb数据下载信息"""
        info = {
            'project_id': project_id,
            'database': 'CNGBdb',
            'urls': [],
            'metadata': {}
        }
        
        # CNPxxxxxx 格式的项目编号
        if project_id.startswith('CNP'):
            try:
                api_url = f"{self.API_BASE}/projects/{project_id}"
                response = self.session.get(api_url, timeout=self.timeout)
                
                if response.status_code == 200:
                    data = response.json()
                    info['metadata'] = data
                    
                    # 提取下载链接
                    files = data.get('files', [])
                    for file in files:
                        info['urls'].append({
                            'url': file.get('download_url'),
                            'type': file.get('file_type', 'raw'),
                            'format': file.get('format', 'unknown'),
                            'size': file.get('size')
                        })
                        
            except Exception as e:
                self.logger.error(f"获取CNGBdb信息失败: {e}")
        
        return info


class UniversalDownloader(BaseDownloader):
    """通用下载器 - 处理直接URL"""
    
    def can_handle(self, database: str) -> bool:
        # 通用下载器可以处理任何有直接URL的数据
        return True
    
    def get_download_info(self, project_id: str,
                          file_type: str = 'matrix') -> Dict[str, Any]:
        """如果project_id是URL，直接返回"""
        if project_id.startswith(('http://', 'https://', 'ftp://')):
            return {
                'project_id': project_id,
                'database': 'Direct_URL',
                'urls': [{'url': project_id, 'type': file_type, 'format': 'auto'}],
                'metadata': {}
            }
        raise ValueError(f"无法解析的项目ID: {project_id}")


class DataDownloader:
    """
    数据下载管理器 - 统一接口管理各类数据库下载
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.logger = logging.getLogger(__name__)
        
        # 下载目录
        self.download_dir = Path(config.get('download_dir', 'data/downloads'))
        self.download_dir.mkdir(parents=True, exist_ok=True)
        
        # 并发设置
        self.max_concurrent = config.get('max_concurrent_downloads', 3)
        self.retry_attempts = config.get('retry_attempts', 3)
        
        # 注册下载器
        self.downloaders: List[BaseDownloader] = [
            GEODownloader(config),
            CellxGeneDownloader(config),
            SRADownloader(config),
            CNGBDownloader(config),
            UniversalDownloader(config)
        ]
        
        # 任务管理
        self.tasks: Dict[str, DownloadTask] = {}
        self._executor = ThreadPoolExecutor(max_workers=self.max_concurrent)
        
    def create_download_tasks(self, records: pd.DataFrame,
                              file_types: List[str] = None,
                              output_dir: Optional[str] = None) -> List[DownloadTask]:
        """
        根据查询结果创建下载任务
        
        Args:
            records: 查询结果DataFrame
            file_types: 要下载的文件类型 ['matrix', 'raw', 'metadata']
            output_dir: 输出目录
        
        Returns:
            下载任务列表
        """
        if file_types is None:
            file_types = ['matrix']
            
        tasks = []
        base_dir = Path(output_dir) if output_dir else self.download_dir
        base_dir.mkdir(parents=True, exist_ok=True)
        
        for _, record in records.iterrows():
            sample_uid = record.get('sample_uid', '')
            project_id = record.get('project_id_primary', '')
            database = record.get('database_standardized', record.get('source_database', 'Unknown'))
            
            if not project_id:
                continue
            
            # 为每种文件类型创建任务
            for file_type in file_types:
                task_id = self._generate_task_id(sample_uid, file_type)
                
                # 确定文件格式和路径
                file_format = self._determine_format(record, file_type)
                target_path = self._build_target_path(
                    base_dir, database, project_id, sample_uid, file_type, file_format
                )
                
                task = DownloadTask(
                    task_id=task_id,
                    sample_uid=sample_uid,
                    project_id=project_id,
                    database=database,
                    download_url=record.get('access_link'),
                    target_path=target_path,
                    file_type=file_type,
                    file_format=file_format
                )
                
                tasks.append(task)
                self.tasks[task_id] = task
        
        self.logger.info(f"创建了 {len(tasks)} 个下载任务")
        return tasks
    
    def start_download(self, tasks: List[DownloadTask],
                       progress_callback: Optional[Callable] = None,
                       completion_callback: Optional[Callable] = None) -> Dict[str, Any]:
        """
        开始批量下载
        
        Args:
            tasks: 下载任务列表
            progress_callback: 进度回调函数 (task_id, progress, speed)
            completion_callback: 完成回调函数 (task_id, success)
        
        Returns:
            下载统计信息
        """
        futures = {}
        stats = {'total': len(tasks), 'completed': 0, 'failed': 0}
        
        for task in tasks:
            downloader = self._get_downloader(task.database)
            
            future = self._executor.submit(
                self._download_with_retry,
                downloader,
                task,
                progress_callback
            )
            futures[future] = task
        
        # 等待完成
        for future in as_completed(futures):
            task = futures[future]
            try:
                success = future.result()
                if success:
                    stats['completed'] += 1
                else:
                    stats['failed'] += 1
                    
                if completion_callback:
                    completion_callback(task.task_id, success)
                    
            except Exception as e:
                self.logger.error(f"下载任务异常 {task.task_id}: {e}")
                stats['failed'] += 1
                if completion_callback:
                    completion_callback(task.task_id, False)
        
        return stats
    
    def _download_with_retry(self, downloader: BaseDownloader,
                             task: DownloadTask,
                             progress_callback: Optional[Callable] = None) -> bool:
        """带重试的下载"""
        for attempt in range(self.retry_attempts):
            success = downloader.download(task, progress_callback)
            if success:
                return True
            
            if attempt < self.retry_attempts - 1:
                self.logger.warning(f"下载失败，重试 {attempt + 1}/{self.retry_attempts}: {task.task_id}")
                time.sleep(2 ** attempt)  # 指数退避
        
        return False
    
    def get_task_status(self, task_id: str) -> Optional[DownloadTask]:
        """获取任务状态"""
        return self.tasks.get(task_id)
    
    def get_all_tasks(self) -> List[DownloadTask]:
        """获取所有任务"""
        return list(self.tasks.values())
    
    def pause_download(self, task_id: str) -> bool:
        """暂停下载（待实现）"""
        # 实际实现需要更复杂的信号机制
        task = self.tasks.get(task_id)
        if task and task.status == 'downloading':
            task.status = 'paused'
            return True
        return False
    
    def cancel_download(self, task_id: str) -> bool:
        """取消下载"""
        task = self.tasks.get(task_id)
        if task:
            task.status = 'cancelled'
            return True
        return False
    
    def _get_downloader(self, database: str) -> BaseDownloader:
        """获取适合的下载器"""
        for downloader in self.downloaders:
            if downloader.can_handle(database):
                return downloader
        return self.downloaders[-1]  # 返回通用下载器
    
    def _generate_task_id(self, sample_uid: str, file_type: str) -> str:
        """生成任务ID"""
        content = f"{sample_uid}_{file_type}_{datetime.now().isoformat()}"
        return hashlib.md5(content.encode()).hexdigest()[:16]
    
    def _determine_format(self, record: pd.Series, file_type: str) -> str:
        """确定文件格式"""
        file_type_field = record.get('file_type', '')
        
        if file_type == 'matrix':
            if 'h5ad' in str(file_type_field).lower():
                return 'h5ad'
            elif 'h5' in str(file_type_field).lower():
                return 'h5'
            elif 'rds' in str(file_type_field).lower():
                return 'rds'
            else:
                return 'h5ad'  # 默认
        elif file_type == 'raw':
            return 'fastq'
        else:
            return 'txt'
    
    def _build_target_path(self, base_dir: Path, database: str,
                           project_id: str, sample_uid: str,
                           file_type: str, file_format: str) -> Path:
        """构建目标路径"""
        # 路径结构: downloads/{database}/{project_id}/{sample_uid}_{file_type}.{format}
        safe_db = re.sub(r'[^\w\-]', '_', str(database))[:20]
        safe_proj = re.sub(r'[^\w\-]', '_', str(project_id))[:50]
        safe_sample = re.sub(r'[^\w\-]', '_', str(sample_uid))[:50] if sample_uid else 'unknown'
        
        target_dir = base_dir / safe_db / safe_proj
        target_dir.mkdir(parents=True, exist_ok=True)
        
        return target_dir / f"{safe_sample}_{file_type}.{file_format}"
    
    def generate_download_script(self, tasks: List[DownloadTask],
                                  script_path: Optional[str] = None) -> Path:
        """
        生成批量下载脚本
        
        Args:
            tasks: 下载任务列表
            script_path: 脚本保存路径
        
        Returns:
            脚本文件路径
        """
        if script_path is None:
            script_path = self.download_dir / f"download_batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}.sh"
        else:
            script_path = Path(script_path)
        
        script_content = ["#!/bin/bash", "# Auto-generated download script", ""]
        
        # 按数据库分组
        db_groups = {}
        for task in tasks:
            db = task.database
            if db not in db_groups:
                db_groups[db] = []
            db_groups[db].append(task)
        
        for db, db_tasks in db_groups.items():
            script_content.append(f"# {db} downloads ({len(db_tasks)} tasks)")
            
            for task in db_tasks:
                downloader = self._get_downloader(db)
                info = downloader.get_download_info(task.project_id, task.file_type)
                
                for url_info in info.get('urls', []):
                    url = url_info.get('url')
                    if url:
                        output_file = task.target_path
                        script_content.append(f'# {task.project_id} - {task.file_type}')
                        script_content.append(f'echo "Downloading {task.project_id}..."')
                        script_content.append(f'mkdir -p "{output_file.parent}"')
                        script_content.append(f'wget -c -O "{output_file}" "{url}"')
                        script_content.append('')
            
            script_content.append("")
        
        script_content.append("echo 'All downloads completed!'")
        
        script_path.write_text('\n'.join(script_content), encoding='utf-8')
        script_path.chmod(0o755)  # 添加执行权限
        
        self.logger.info(f"下载脚本已生成: {script_path}")
        return script_path
    
    def export_download_list(self, tasks: List[DownloadTask],
                             output_path: Optional[str] = None) -> Path:
        """
        导出下载列表为CSV
        
        Args:
            tasks: 下载任务列表
            output_path: 输出路径
        
        Returns:
            CSV文件路径
        """
        if output_path is None:
            output_path = self.download_dir / f"download_list_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        else:
            output_path = Path(output_path)
        
        data = []
        for task in tasks:
            data.append({
                'task_id': task.task_id,
                'sample_uid': task.sample_uid,
                'project_id': task.project_id,
                'database': task.database,
                'file_type': task.file_type,
                'file_format': task.file_format,
                'target_path': str(task.target_path),
                'download_url': task.download_url or 'To be resolved',
                'status': task.status
            })
        
        df = pd.DataFrame(data)
        df.to_csv(output_path, index=False, encoding='utf-8-sig')
        
        self.logger.info(f"下载列表已导出: {output_path}")
        return output_path
    
    def shutdown(self):
        """关闭下载器"""
        self._executor.shutdown(wait=True)
        self.logger.info("数据下载器已关闭")
