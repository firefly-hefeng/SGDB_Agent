"""
数据合并与导出模块
=================

合并所有收集的数据并导出为CSV和JSON格式。
"""

import pandas as pd
import json
import logging
from pathlib import Path
from typing import List, Dict


class DataMerger:
    """数据合并器"""
    
    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        self.raw_dir = self.data_dir / "raw"
        self.processed_dir = self.data_dir / "processed"
        self.processed_dir.mkdir(parents=True, exist_ok=True)
        self.logger = logging.getLogger(__name__)
    
    def merge_collections(self, collections: List[Dict], 
                         datasets_df: pd.DataFrame) -> pd.DataFrame:
        """合并Collections数据并添加统计"""
        self.logger.info("Merging collections data...")
        
        df = pd.DataFrame(collections)
        
        # 添加统计列
        stats = []
        for coll_id in df['collection_id']:
            coll_datasets = datasets_df[datasets_df['collection_id'] == coll_id]
            stats.append({
                'collection_id': coll_id,
                'n_datasets': len(coll_datasets),
                'total_cells': coll_datasets['cell_count'].sum() if 'cell_count' in coll_datasets.columns else 0,
            })
        
        stats_df = pd.DataFrame(stats)
        df = df.merge(stats_df, on='collection_id', how='left')
        
        return df
    
    def merge_datasets(self, datasets: List[Dict],
                      samples_df: pd.DataFrame,
                      collections_df: pd.DataFrame) -> pd.DataFrame:
        """合并Datasets数据并添加统计"""
        self.logger.info("Merging datasets data...")
        
        df = pd.DataFrame(datasets)
        
        # 添加sample统计
        sample_stats = []
        for ds_id in df['dataset_id']:
            ds_samples = samples_df[samples_df['dataset_id'] == ds_id]
            sample_stats.append({
                'dataset_id': ds_id,
                'n_samples': len(ds_samples),
                'total_cells': ds_samples['n_cells'].sum() if 'n_cells' in ds_samples.columns else 0,
                'sample_ids': '; '.join(ds_samples['sample_id'].unique()) if len(ds_samples) > 0 else '',
            })
        
        stats_df = pd.DataFrame(sample_stats)
        df = df.merge(stats_df, on='dataset_id', how='left')
        
        # 合并collection信息
        coll_info = collections_df[['collection_id', 'doi', 'pm_journal', 'pm_published_year']]
        df = df.merge(coll_info, on='collection_id', how='left')
        
        return df
    
    def export_hierarchy_json(self, collections_df: pd.DataFrame,
                             datasets_df: pd.DataFrame,
                             samples_df: pd.DataFrame):
        """导出层级JSON"""
        self.logger.info("Exporting hierarchy JSON...")
        
        hierarchy = []
        
        for _, coll_row in collections_df.iterrows():
            coll_id = coll_row['collection_id']
            
            coll_data = {
                'collection_id': coll_id,
                'name': coll_row.get('name'),
                'description': coll_row.get('description'),
                'doi': coll_row.get('doi'),
                'pm_journal': coll_row.get('pm_journal'),
                'pm_published_year': coll_row.get('pm_published_year'),
                'n_datasets': coll_row.get('n_datasets'),
                'datasets': []
            }
            
            # 添加datasets
            coll_datasets = datasets_df[datasets_df['collection_id'] == coll_id]
            for _, ds_row in coll_datasets.iterrows():
                ds_id = ds_row['dataset_id']
                
                ds_data = {
                    'dataset_id': ds_id,
                    'title': ds_row.get('title'),
                    'cell_count': ds_row.get('cell_count'),
                    'citation_count': ds_row.get('citation_count'),
                    'n_samples': ds_row.get('n_samples'),
                }
                
                # 添加samples
                ds_samples = samples_df[samples_df['dataset_id'] == ds_id]
                if len(ds_samples) > 0:
                    ds_data['samples'] = ds_samples.to_dict('records')
                
                coll_data['datasets'].append(ds_data)
            
            hierarchy.append(coll_data)
        
        # 保存
        output_file = self.processed_dir / "hierarchy.json"
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(hierarchy, f, indent=2, ensure_ascii=False)
        
        self.logger.info(f"Hierarchy saved to: {output_file}")
    
    def export_all(self, collections: List[Dict], datasets: List[Dict], 
                   samples_df: pd.DataFrame):
        """导出所有数据"""
        self.logger.info("=" * 60)
        self.logger.info("Exporting All Data")
        self.logger.info("=" * 60)
        
        # 先创建临时datasets df用于collection统计
        datasets_temp = pd.DataFrame(datasets)
        
        # 合并并导出collections
        collections_df = self.merge_collections(collections, datasets_temp)
        collections_file = self.processed_dir / "collections.csv"
        collections_df.to_csv(collections_file, index=False, encoding='utf-8-sig')
        self.logger.info(f"Collections saved: {collections_file}")
        
        # 合并并导出datasets
        datasets_df = self.merge_datasets(datasets, samples_df, collections_df)
        datasets_file = self.processed_dir / "datasets.csv"
        datasets_df.to_csv(datasets_file, index=False, encoding='utf-8-sig')
        self.logger.info(f"Datasets saved: {datasets_file}")
        
        # 导出samples
        samples_file = self.processed_dir / "samples.csv"
        samples_df.to_csv(samples_file, index=False, encoding='utf-8-sig')
        self.logger.info(f"Samples saved: {samples_file}")
        
        # 导出层级JSON
        self.export_hierarchy_json(collections_df, datasets_df, samples_df)
        
        self.logger.info("=" * 60)
        self.logger.info("Export Complete!")
        self.logger.info("=" * 60)
        
        return collections_df, datasets_df


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from src.utils import setup_logging
    
    logger = setup_logging()
    
    # 加载数据
    with open("data/raw/collections_raw.json", 'r') as f:
        import json
        collections = json.load(f)
    
    with open("data/raw/datasets_raw.json", 'r') as f:
        datasets = json.load(f)
    
    samples_df = pd.read_csv("data/processed/samples_full.csv")
    
    # 合并导出
    merger = DataMerger()
    collections_df, datasets_df = merger.export_all(collections, datasets, samples_df)
    
    print(f"\nExported {len(collections_df)} collections, {len(datasets_df)} datasets")
