"""
Datasets收集模块
===============

收集每个Collection下的所有Datasets。
"""

import requests
import json
import time
import logging
from pathlib import Path
from typing import List, Dict, Optional


class DatasetCollector:
    """CellxGene Datasets收集器"""
    
    BASE_URL = "https://api.cellxgene.cziscience.com/curation/v1/collections"
    
    def __init__(self, output_dir: str = "data/raw"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.logger = logging.getLogger(__name__)
        self.session = requests.Session()
        
    def fetch_datasets_for_collection(self, collection_id: str) -> List[Dict]:
        """获取指定Collection的所有Datasets"""
        try:
            url = f"{self.BASE_URL}/{collection_id}"
            response = self.session.get(url, timeout=60)
            response.raise_for_status()
            
            data = response.json()
            datasets = data.get('datasets', [])
            
            # 添加Collection信息
            for ds in datasets:
                ds['collection_id'] = collection_id
                ds['collection_name'] = data.get('name', '')
                ds['collection_doi'] = data.get('doi', '')
            
            return datasets
            
        except Exception as e:
            self.logger.error(f"Failed to fetch datasets for {collection_id}: {e}")
            return []
    
    def process_dataset(self, dataset: Dict) -> Dict:
        """处理单个Dataset"""
        # 提取assets
        assets = dataset.get('assets', [])
        h5ad_url = ""
        rds_url = ""
        for asset in assets:
            ft = asset.get('filetype', '')
            url = asset.get('url', '')
            if ft == 'H5AD':
                h5ad_url = url
            elif ft == 'RDS':
                rds_url = url
        
        # 提取ontology信息
        def extract_ontology(terms: List[Dict]) -> str:
            if not terms:
                return ""
            return '; '.join([
                f"{t.get('label', '')} ({t.get('ontology_term_id', '')})"
                for t in terms
            ])
        
        return {
            'dataset_id': dataset.get('dataset_id'),
            'dataset_version_id': dataset.get('dataset_version_id'),
            'title': dataset.get('title'),
            'collection_id': dataset.get('collection_id'),
            'collection_name': dataset.get('collection_name'),
            'citation': dataset.get('citation'),
            'cell_count': dataset.get('cell_count', 0),
            'primary_cell_count': dataset.get('primary_cell_count', 0),
            'mean_genes_per_cell': dataset.get('mean_genes_per_cell', 0),
            'explorer_url': dataset.get('explorer_url'),
            'asset_h5ad_url': h5ad_url,
            'asset_rds_url': rds_url,
            'organisms': extract_ontology(dataset.get('organism', [])),
            'diseases': extract_ontology(dataset.get('disease', [])),
            'tissues': extract_ontology(dataset.get('tissue', [])),
            'assays': extract_ontology(dataset.get('assay', [])),
            'cell_types': extract_ontology(dataset.get('cell_type', [])),
        }
    
    def collect(self, collections: List[Dict]) -> List[Dict]:
        """
        为所有Collections收集Datasets
        
        Args:
            collections: Collections列表
        
        Returns:
            List[Dict]: 所有Datasets
        """
        self.logger.info("=" * 60)
        self.logger.info("Starting Datasets Collection")
        self.logger.info("=" * 60)
        
        all_datasets = []
        
        for i, coll in enumerate(collections):
            coll_id = coll.get('collection_id')
            coll_name = coll.get('name', 'Unknown')
            
            self.logger.info(f"[{i+1}/{len(collections)}] {coll_name}")
            
            datasets = self.fetch_datasets_for_collection(coll_id)
            all_datasets.extend(datasets)
            
            if (i + 1) % 10 == 0:
                self.logger.info(f"  Progress: {i+1}/{len(collections)}, Total datasets: {len(all_datasets)}")
            
            time.sleep(0.3)
        
        # 保存原始数据
        output_file = self.output_dir / "datasets_raw.json"
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(all_datasets, f, indent=2, ensure_ascii=False)
        
        self.logger.info(f"Total datasets fetched: {len(all_datasets)}")
        self.logger.info(f"Raw data saved to: {output_file}")
        
        # 处理数据
        processed = [self.process_dataset(d) for d in all_datasets]
        return processed


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from src.utils import setup_logging
    from src.collect_collections import CollectionCollector
    
    logger = setup_logging()
    
    # 先收集collections
    coll_collector = CollectionCollector()
    collections = coll_collector.collect()
    
    # 再收集datasets
    ds_collector = DatasetCollector()
    datasets = ds_collector.collect(collections)
    
    print(f"\nCollected {len(datasets)} datasets")
