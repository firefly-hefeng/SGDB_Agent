#!/usr/bin/env python3
"""
轻量级导出脚本 - 使用底层 SQLite 和 CSV 模块
"""

import sqlite3
import csv
from pathlib import Path
from datetime import datetime

DB_PATH = Path(__file__).parent.parent / "unified_db" / "unified_metadata.db"
OUTPUT_DIR = Path(__file__).parent

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def export_table(table_name, columns, output_filename):
    """导出单表到 CSV"""
    log(f"导出 {table_name} ...")
    
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode = WAL")
    
    # 获取总数
    count = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
    log(f"  总记录数: {count:,}")
    
    output_file = OUTPUT_DIR / output_filename
    
    col_str = ', '.join(columns)
    query = f"SELECT {col_str} FROM {table_name}"
    
    cursor = conn.execute(query)
    
    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(columns)  # 表头
        
        batch = []
        exported = 0
        
        for row in cursor:
            batch.append(row)
            if len(batch) >= 10000:
                writer.writerows(batch)
                exported += len(batch)
                batch = []
                if exported % 50000 == 0:
                    log(f"  已导出: {exported:,}")
        
        if batch:
            writer.writerows(batch)
            exported += len(batch)
    
    conn.close()
    
    size_mb = output_file.stat().st_size / (1024 * 1024)
    log(f"  ✅ 完成: {exported:,} 条记录, {size_mb:.2f} MB")
    return count

def export_projects():
    cols = ['pk', 'project_id', 'source_database', 'title', 'organism', 'pmid', 'doi', 
            'publication_date', 'journal', 'citation_count', 'sample_count', 'total_cells']
    return export_table('unified_projects', cols, '01_projects.csv')

def export_series():
    cols = ['pk', 'series_id', 'source_database', 'project_pk', 'title', 'organism',
            'assay', 'cell_count', 'gene_count', 'has_h5ad', 'has_rds', 'asset_h5ad_url']
    return export_table('unified_series', cols, '02_series.csv')

def export_samples():
    cols = ['pk', 'sample_id', 'source_database', 'series_pk', 'project_pk', 'organism',
            'tissue', 'tissue_general', 'cell_type', 'disease', 'sex', 'age', 'age_unit',
            'development_stage', 'ethnicity', 'individual_id', 'n_cells', 'n_cell_types',
            'biological_identity_hash']
    return export_table('unified_samples', cols, '03_samples.csv')

def export_celltypes():
    cols = ['pk', 'sample_pk', 'cell_type_name', 'cell_type_ontology_term_id', 'source_database']
    return export_table('unified_celltypes', cols, '04_celltypes.csv')

def export_merged_sample_level():
    """导出 sample 级别合并表"""
    log("导出 merged_sample_level ...")
    
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode = WAL")
    
    total = conn.execute("SELECT COUNT(*) FROM unified_samples").fetchone()[0]
    log(f"  总记录数: {total:,}")
    
    output_file = OUTPUT_DIR / "00_merged_sample_level.csv"
    
    columns = [
        'sample_pk', 'sample_id', 'sample_source', 'organism', 'tissue', 'tissue_general',
        'cell_type', 'disease', 'sex', 'age', 'age_unit', 'development_stage', 'ethnicity',
        'individual_id', 'n_cells', 'n_cell_types', 'biological_identity_hash',
        'series_pk', 'series_id', 'series_source', 'assay', 'series_cell_count', 'gene_count',
        'has_h5ad', 'has_rds', 'asset_h5ad_url', 'explorer_url',
        'project_pk', 'project_id', 'project_source', 'pmid', 'doi', 'publication_date', 
        'journal', 'citation_count'
    ]
    
    query = """
    SELECT 
        s.pk, s.sample_id, s.source_database, s.organism, s.tissue, s.tissue_general,
        s.cell_type, s.disease, s.sex, s.age, s.age_unit, s.development_stage, s.ethnicity,
        s.individual_id, s.n_cells, s.n_cell_types, s.biological_identity_hash,
        sr.pk, sr.series_id, sr.source_database, sr.assay, sr.cell_count, sr.gene_count,
        sr.has_h5ad, sr.has_rds, sr.asset_h5ad_url, sr.explorer_url,
        p.pk, p.project_id, p.source_database, p.pmid, p.doi, p.publication_date, 
        p.journal, p.citation_count
    FROM unified_samples s
    LEFT JOIN unified_series sr ON s.series_pk = sr.pk
    LEFT JOIN unified_projects p ON s.project_pk = p.pk
    """
    
    cursor = conn.execute(query)
    
    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        
        batch = []
        exported = 0
        
        for row in cursor:
            batch.append(row)
            if len(batch) >= 10000:
                writer.writerows(batch)
                exported += len(batch)
                batch = []
                if exported % 100000 == 0:
                    log(f"  已导出: {exported:,} / {total:,}")
        
        if batch:
            writer.writerows(batch)
            exported += len(batch)
    
    conn.close()
    
    size_mb = output_file.stat().st_size / (1024 * 1024)
    log(f"  ✅ 完成: {exported:,} 条记录, {size_mb:.2f} MB")
    return exported

def main():
    log("="*60)
    log("统一元数据库导出")
    log("="*60)
    
    export_projects()
    export_series()
    export_samples()
    export_celltypes()
    export_merged_sample_level()
    
    log("="*60)
    log("✅ 全部导出完成!")
    log("="*60)

if __name__ == "__main__":
    main()
