#!/usr/bin/env python3
"""
CellxGene元数据收集主程序
=========================

完整的收集流程：
1. 收集Collections
2. 收集Datasets  
3. 从Census收集Samples
4. 收集Citations
5. 合并导出

使用方法:
    python run_collection.py [--skip-collections] [--skip-samples]
"""

import argparse
import sys
from pathlib import Path

# 添加src到路径
sys.path.insert(0, str(Path(__file__).parent))

from src.utils import setup_logging, ensure_dir
from src.collect_collections import CollectionCollector
from src.collect_datasets import DatasetCollector
from src.collect_samples import SampleCollector
from src.collect_citations import CitationCollector
from src.merge_data import DataMerger
import pandas as pd
import json


def main():
    parser = argparse.ArgumentParser(
        description='CellxGene Metadata Collection Pipeline'
    )
    parser.add_argument('--skip-collections', action='store_true',
                       help='Skip collections collection (use cached)')
    parser.add_argument('--skip-datasets', action='store_true',
                       help='Skip datasets collection (use cached)')
    parser.add_argument('--skip-samples', action='store_true',
                       help='Skip samples collection (use cached)')
    parser.add_argument('--skip-citations', action='store_true',
                       help='Skip citations collection')
    parser.add_argument('--data-dir', default='data',
                       help='Data directory (default: data)')
    
    args = parser.parse_args()
    
    # 设置
    logger = setup_logging(log_dir=f"{args.data_dir}/logs")
    data_dir = Path(args.data_dir)
    raw_dir = ensure_dir(data_dir / "raw")
    processed_dir = ensure_dir(data_dir / "processed")
    
    logger.info("=" * 80)
    logger.info("CellxGene Metadata Collection Pipeline")
    logger.info("=" * 80)
    
    # Step 1: Collect Collections
    if args.skip_collections and (raw_dir / "collections_raw.json").exists():
        logger.info("\n[Step 1/5] Loading cached collections...")
        with open(raw_dir / "collections_raw.json", 'r') as f:
            collections_raw = json.load(f)
        # 重新处理
        coll_collector = CollectionCollector(output_dir=raw_dir)
        collections = [coll_collector.process_collection(c) for c in collections_raw]
    else:
        logger.info("\n[Step 1/5] Collecting Collections...")
        coll_collector = CollectionCollector(output_dir=raw_dir)
        collections_raw = coll_collector.fetch_all_collections()
        collections = [coll_collector.process_collection(c) for c in collections_raw]
    
    logger.info(f"Collections: {len(collections)}")
    
    # Step 2: Collect Datasets
    if args.skip_datasets and (raw_dir / "datasets_raw.json").exists():
        logger.info("\n[Step 2/5] Loading cached datasets...")
        with open(raw_dir / "datasets_raw.json", 'r') as f:
            datasets_raw = json.load(f)
        ds_collector = DatasetCollector(output_dir=raw_dir)
        datasets = [ds_collector.process_dataset(d) for d in datasets_raw]
    else:
        logger.info("\n[Step 2/5] Collecting Datasets...")
        ds_collector = DatasetCollector(output_dir=raw_dir)
        datasets_raw = ds_collector.collect(collections_raw if 'collections_raw' in locals() else collections)
        datasets = [ds_collector.process_dataset(d) for d in datasets_raw]
    
    logger.info(f"Datasets: {len(datasets)}")
    
    # Step 3: Collect Samples
    samples_file = processed_dir / "samples.csv"
    if args.skip_samples and samples_file.exists():
        logger.info("\n[Step 3/5] Loading cached samples...")
        samples_df = pd.read_csv(samples_file)
    else:
        logger.info("\n[Step 3/5] Collecting Samples from Census...")
        sample_collector = SampleCollector(output_dir=processed_dir)
        samples_df = sample_collector.collect(datasets_raw if 'datasets_raw' in locals() else datasets)
    
    logger.info(f"Samples: {len(samples_df):,}")
    if 'n_cells' in samples_df.columns:
        logger.info(f"Total cells: {samples_df['n_cells'].sum():,}")
    
    # Step 4: Collect Citations
    if not args.skip_citations:
        logger.info("\n[Step 4/5] Collecting Citations...")
        
        # 准备DataFrames
        collections_df = pd.DataFrame(collections)
        datasets_df = pd.DataFrame(datasets)
        
        citation_collector = CitationCollector(
            cache_file=data_dir / "cache" / "citation_cache.json"
        )
        datasets_with_citations = citation_collector.collect(datasets_df, collections_df)
        
        # 更新datasets
        datasets_df = datasets_with_citations
        citation_count = datasets_df['citation_count'].notna().sum()
        logger.info(f"Datasets with citations: {citation_count}")
    else:
        datasets_df = pd.DataFrame(datasets)
        collections_df = pd.DataFrame(collections)
    
    # Step 5: Merge and Export
    logger.info("\n[Step 5/5] Merging and Exporting...")
    merger = DataMerger(data_dir=args.data_dir)
    
    # 手动调用导出
    collections_df = merger.merge_collections(collections, datasets_df)
    collections_df.to_csv(processed_dir / "collections.csv", index=False, encoding='utf-8-sig')
    
    datasets_df = merger.merge_datasets(
        datasets_raw if 'datasets_raw' in locals() else datasets, 
        samples_df, 
        collections_df
    )
    datasets_df.to_csv(processed_dir / "datasets.csv", index=False, encoding='utf-8-sig')
    
    samples_df.to_csv(processed_dir / "samples.csv", index=False, encoding='utf-8-sig')
    
    merger.export_hierarchy_json(collections_df, datasets_df, samples_df)
    
    # 最终统计
    logger.info("=" * 80)
    logger.info("Collection Complete!")
    logger.info("=" * 80)
    logger.info(f"Collections: {len(collections_df)}")
    logger.info(f"Datasets: {len(datasets_df)}")
    logger.info(f"Samples: {len(samples_df):,}")
    if 'n_cells' in samples_df.columns:
        logger.info(f"Total cells: {samples_df['n_cells'].sum():,}")
    if 'citation_count' in datasets_df.columns:
        logger.info(f"Datasets with citations: {datasets_df['citation_count'].notna().sum()}")
    logger.info("=" * 80)
    logger.info(f"Output directory: {processed_dir}")
    logger.info("=" * 80)


if __name__ == "__main__":
    main()
