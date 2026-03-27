#!/usr/bin/env python3
"""
导出 celltype 级别合并表（最细粒度）
将 celltypes + samples + series + projects 合并为一张表
"""

import sqlite3
import csv
from pathlib import Path
from datetime import datetime

DB_PATH = Path(__file__).parent.parent / "unified_db" / "unified_metadata.db"
OUTPUT_DIR = Path(__file__).parent

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def main():
    log("导出 celltype 级别合并表（最细粒度）...")
    
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode = WAL")
    
    total = conn.execute("SELECT COUNT(*) FROM unified_celltypes").fetchone()[0]
    log(f"总记录数: {total:,}")
    
    output_file = OUTPUT_DIR / "00_merged_celltype_level.csv"
    
    columns = [
        # celltype 层级
        'celltype_pk', 'cell_type_name', 'cell_type_ontology_term_id', 'celltype_source', 'source_field',
        # sample 层级
        'sample_pk', 'sample_id', 'sample_source', 'organism', 'tissue', 'tissue_general',
        'sample_cell_type', 'disease', 'sex', 'age', 'age_unit', 'development_stage', 'ethnicity',
        'individual_id', 'n_cells', 'n_cell_types', 'biological_identity_hash',
        # series 层级
        'series_pk', 'series_id', 'series_source', 'assay', 'series_cell_count', 'gene_count',
        'has_h5ad', 'has_rds', 'asset_h5ad_url', 'explorer_url',
        # project 层级
        'project_pk', 'project_id', 'project_source', 'pmid', 'doi', 'publication_date', 
        'journal', 'citation_count'
    ]
    
    query = """
    SELECT 
        ct.pk, ct.cell_type_name, ct.cell_type_ontology_term_id, ct.source_database, ct.source_field,
        s.pk, s.sample_id, s.source_database, s.organism, s.tissue, s.tissue_general,
        s.cell_type, s.disease, s.sex, s.age, s.age_unit, s.development_stage, s.ethnicity,
        s.individual_id, s.n_cells, s.n_cell_types, s.biological_identity_hash,
        sr.pk, sr.series_id, sr.source_database, sr.assay, sr.cell_count, sr.gene_count,
        sr.has_h5ad, sr.has_rds, sr.asset_h5ad_url, sr.explorer_url,
        p.pk, p.project_id, p.source_database, p.pmid, p.doi, p.publication_date, 
        p.journal, p.citation_count
    FROM unified_celltypes ct
    LEFT JOIN unified_samples s ON ct.sample_pk = s.pk
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
                if exported % 50000 == 0:
                    log(f"  已导出: {exported:,} / {total:,}")
        
        if batch:
            writer.writerows(batch)
            exported += len(batch)
    
    conn.close()
    
    size_mb = output_file.stat().st_size / (1024 * 1024)
    log(f"✅ 完成! 导出 {exported:,} 条记录")
    log(f"   文件: {output_file}")
    log(f"   大小: {size_mb:.2f} MB")

if __name__ == "__main__":
    main()
