"""
Samples收集模块
==============

从CellxGene Census收集Sample (Donor)级别的数据。
"""

import pandas as pd
import json
import time
import logging
from pathlib import Path
from typing import List, Dict, Optional


class SampleCollector:
    """CellxGene Samples收集器 (从Census)"""
    
    # Census obs字段
    OBS_FIELDS = [
        "dataset_id", "donor_id", "observation_joinid",
        "assay", "assay_ontology_term_id",
        "cell_type", "cell_type_ontology_term_id",
        "development_stage", "development_stage_ontology_term_id",
        "disease", "disease_ontology_term_id",
        "self_reported_ethnicity", "self_reported_ethnicity_ontology_term_id",
        "sex", "sex_ontology_term_id",
        "suspension_type", "tissue", "tissue_ontology_term_id",
        "tissue_general", "tissue_general_ontology_term_id", "tissue_type",
        "is_primary_data",
        "nnz", "n_measured_vars", "raw_sum", "raw_mean_nnz", "raw_variance_nnz"
    ]
    
    def __init__(self, output_dir: str = "data/processed"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.logger = logging.getLogger(__name__)
        self.census = None
        
    def open_census(self):
        """打开Census连接"""
        try:
            import cellxgene_census
            self.logger.info("Opening CELLxGENE Census...")
            self.census = cellxgene_census.open_soma(census_version="stable")
            self.logger.info("Census opened successfully")
        except ImportError:
            raise RuntimeError("cellxgene_census not installed. Run: pip install cellxgene-census")
    
    def close_census(self):
        """关闭Census连接"""
        if self.census:
            self.census.close()
            self.census = None
    
    def collect_samples_for_dataset(self, dataset_id: str, 
                                     collection_name: str = "",
                                     dataset_title: str = "") -> List[Dict]:
        """
        从Census收集单个Dataset的所有Samples
        
        Returns:
            List[Dict]: Samples列表
        """
        if not self.census:
            self.open_census()
        
        try:
            human = self.census["census_data"]["homo_sapiens"]
            
            # 读取obs数据
            obs = human.obs.read(
                column_names=self.OBS_FIELDS,
                value_filter=f"dataset_id == '{dataset_id}'"
            ).concat().to_pandas()
            
            if obs.empty:
                return []
            
            # 按donor_id聚合
            samples = []
            for donor_id, group in obs.groupby('donor_id'):
                sample = {
                    'dataset_id': dataset_id,
                    'dataset_title': dataset_title,
                    'collection_name': collection_name,
                    'sample_id': donor_id,
                    'n_cells': len(group),
                    'n_cell_types': group['cell_type'].nunique(),
                    'cell_type_list': '; '.join(sorted(group['cell_type'].dropna().unique())),
                    'tissue': '; '.join(group['tissue'].unique()),
                    'tissue_general': '; '.join(group['tissue_general'].unique()),
                    'tissue_ontology_term_id': '; '.join(group['tissue_ontology_term_id'].unique()),
                    'assay': '; '.join(group['assay'].unique()),
                    'disease': '; '.join(group['disease'].unique()),
                    'sex': group['sex'].iloc[0] if not group['sex'].empty else '',
                    'development_stage': group['development_stage'].iloc[0] if not group['development_stage'].empty else '',
                    'self_reported_ethnicity': group['self_reported_ethnicity'].iloc[0] if not group['self_reported_ethnicity'].empty else '',
                    'suspension_type': '; '.join(group['suspension_type'].unique()),
                    'is_primary_data': group['is_primary_data'].all(),
                    'expr_raw_sum_mean': group['raw_sum'].mean() if 'raw_sum' in group.columns else 0,
                    'expr_raw_sum_min': group['raw_sum'].min() if 'raw_sum' in group.columns else 0,
                    'expr_raw_sum_max': group['raw_sum'].max() if 'raw_sum' in group.columns else 0,
                    'expr_nnz_mean': group['nnz'].mean() if 'nnz' in group.columns else 0,
                }
                samples.append(sample)
            
            return samples
            
        except Exception as e:
            self.logger.error(f"Error collecting samples for {dataset_id}: {e}")
            return []
    
    def collect(self, datasets: List[Dict], batch_size: int = 50) -> pd.DataFrame:
        """
        为所有Datasets收集Samples
        
        Args:
            datasets: Datasets列表
            batch_size: 批次保存大小
        
        Returns:
            pd.DataFrame: 所有Samples
        """
        self.logger.info("=" * 60)
        self.logger.info("Starting Samples Collection from Census")
        self.logger.info("=" * 60)
        
        self.open_census()
        
        all_samples = []
        processed = 0
        failed = 0
        
        try:
            for i, ds in enumerate(datasets):
                ds_id = ds.get('dataset_id')
                coll_name = ds.get('collection_name', '')
                ds_title = ds.get('title', '')
                
                samples = self.collect_samples_for_dataset(ds_id, coll_name, ds_title)
                
                if samples:
                    all_samples.extend(samples)
                    processed += 1
                else:
                    failed += 1
                
                # 进度报告
                if (i + 1) % 10 == 0 or (i + 1) == len(datasets):
                    total_cells = sum(s['n_cells'] for s in all_samples)
                    self.logger.info(
                        f"Progress: {i+1}/{len(datasets)} | "
                        f"Success: {processed} | Failed: {failed} | "
                        f"Samples: {len(all_samples)} | Cells: {total_cells:,}"
                    )
                
                # 批次保存
                if (i + 1) % batch_size == 0:
                    self._save_intermediate(all_samples)
                
                time.sleep(0.1)
        
        finally:
            self.close_census()
        
        # 最终保存
        df = pd.DataFrame(all_samples)
        output_file = self.output_dir / "samples_full.csv"
        df.to_csv(output_file, index=False, encoding='utf-8-sig')
        
        self.logger.info("=" * 60)
        self.logger.info("Collection Complete!")
        self.logger.info(f"  Total samples: {len(df):,}")
        self.logger.info(f"  Total cells: {df['n_cells'].sum():,}")
        self.logger.info(f"  Output: {output_file}")
        self.logger.info("=" * 60)
        
        return df
    
    def _save_intermediate(self, samples: List[Dict]):
        """保存中间结果"""
        if samples:
            df = pd.DataFrame(samples)
            output_file = self.output_dir / "samples_intermediate.csv"
            df.to_csv(output_file, index=False, encoding='utf-8-sig')


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from src.utils import setup_logging
    from src.collect_collections import CollectionCollector
    from src.collect_datasets import DatasetCollector
    
    logger = setup_logging()
    
    # 收集collections和datasets
    coll_collector = CollectionCollector()
    collections = coll_collector.collect()
    
    ds_collector = DatasetCollector()
    datasets = ds_collector.collect(collections)
    
    # 收集samples
    sample_collector = SampleCollector()
    samples_df = sample_collector.collect(datasets)
    
    print(f"\nCollected {len(samples_df)} samples")
