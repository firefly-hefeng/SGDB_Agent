# NCBI BioProject / SRA 元数据采集

## 数据来源
NCBI BioProject + SRA + BioSample + PubMed（https://www.ncbi.nlm.nih.gov/）

## 目录结构
```
ncbi_bioproject_sra_data/
├── bioproject_sra_metadata.db            # 原始 SQLite 数据库（14 GB）
├── raw_bioprojects.csv                   # 10,828 个 BioProject
├── raw_biosamples.csv                    # 217,513 个 BioSample
├── raw_sra_studies.csv                   # 8,833 个 SRA Study
├── raw_sra_experiments.csv               # 1,472,801 个 SRA Experiment
├── raw_sra_runs.csv                      # 1,748,093 个 SRA Run
├── raw_pubmed_articles.csv               # 5,686 篇 PubMed 文章
├── bioproject_sra_metadata_enhanced.csv  # 合并导出（含 metadata_completeness 评分）
├── fastq_download_links.csv              # FASTQ 下载链接
└── collection_statistics_enhanced.txt    # 采集统计报告
```

## 注意事项
- CSV 文件带 BOM（UTF-8 BOM），读取时需用 `encoding='utf-8-sig'`
- `raw_xml` 字段可能超过 128KB，需设置 `csv.field_size_limit(10*1024*1024)`
- `sra_experiments.biosample_accession` 使用 SRS* 格式（非 SAMN*）
- `bioprojects.raw_xml` 中含 GEO 交叉引用: `<CenterID center="GEO">GSExxxxx</CenterID>`
- `bioprojects.publications` 是 JSON 数组格式: `["39824181"]`

## 在统一数据库中的映射
- BioProject → `unified_projects` (project_id_type='bioproject')
- SRA Study → `unified_series` (series_id_type='sra_study')
- BioSample → `unified_samples` (sample_id_type='biosample')
