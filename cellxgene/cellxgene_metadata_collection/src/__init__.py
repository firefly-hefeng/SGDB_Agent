"""
CellxGene Metadata Collection Package
======================================

用于收集CellxGene数据库的完整元数据，包括：
- Collections (研究项目)
- Datasets (数据集)
- Samples (样本/Donor)
- Citations (论文引用)

Author: AI Assistant
Date: 2025-02-22
"""

__version__ = "1.0.0"
__author__ = "AI Assistant"

from .collect_collections import CollectionCollector
from .collect_datasets import DatasetCollector
from .collect_samples import SampleCollector
from .collect_citations import CitationCollector
from .merge_data import DataMerger

__all__ = [
    'CollectionCollector',
    'DatasetCollector', 
    'SampleCollector',
    'CitationCollector',
    'DataMerger',
]
