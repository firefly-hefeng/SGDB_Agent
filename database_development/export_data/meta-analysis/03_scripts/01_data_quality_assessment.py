#!/usr/bin/env python3
"""
单细胞元数据库质量评估脚本
Data Quality Assessment for Single-Cell Metadata Database

执行复核方案书中的所有质量评估任务
"""

import pandas as pd
import numpy as np
import json
import re
from pathlib import Path
from collections import Counter, defaultdict
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')

# 路径设置
DATA_DIR = Path(__file__).parent.parent / "02_data"
RESULTS_DIR = Path(__file__).parent.parent / "04_results"
RESULTS_DIR.mkdir(exist_ok=True)

def log(msg):
    """打印带时间戳的日志"""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def load_data():
    """加载所有数据文件"""
    log("加载数据文件...")
    
    # 使用流式读取减少内存占用
    projects = pd.read_csv(DATA_DIR / "01_projects.csv")
    series = pd.read_csv(DATA_DIR / "02_series.csv")
    samples = pd.read_csv(DATA_DIR / "03_samples.csv")
    celltypes = pd.read_csv(DATA_DIR / "04_celltypes.csv")
    
    log(f"  Projects: {len(projects):,}")
    log(f"  Series: {len(series):,}")
    log(f"  Samples: {len(samples):,}")
    log(f"  Celltypes: {len(celltypes):,}")
    
    return projects, series, samples, celltypes

# ============================================================
# 阶段一：基础统计与完整性扫描
# ============================================================

def analyze_global_profile(projects, series, samples, celltypes):
    """任务1.1: 全局数据画像"""
    log("\n" + "="*60)
    log("任务1.1: 全局数据画像")
    log("="*60)
    
    results = {}
    
    # 1.1.1 数据源贡献度分析
    log("\n1. 数据源贡献度分析")
    source_stats = {}
    for df, name in [(projects, 'projects'), (series, 'series'), 
                     (samples, 'samples'), (celltypes, 'celltypes')]:
        col = f'{name}_source' if f'{name}_source' in df.columns else 'source_database'
        if col in df.columns:
            counts = df[col].value_counts()
            source_stats[name] = counts.to_dict()
            log(f"  {name}:")
            for src, cnt in counts.head(5).items():
                log(f"    {src}: {cnt:,}")
    
    results['source_contribution'] = source_stats
    
    # 1.1.2 时间分布分析
    log("\n2. 时间分布分析")
    if 'publication_date' in projects.columns:
        # 提取年份
        projects['year'] = pd.to_datetime(projects['publication_date'], errors='coerce').dt.year
        year_counts = projects['year'].value_counts().sort_index()
        log(f"  发表年份范围: {year_counts.index.min():.0f} - {year_counts.index.max():.0f}")
        log(f"  近5年数据占比: {(year_counts[year_counts.index >= 2020].sum() / len(projects) * 100):.1f}%")
        results['year_distribution'] = year_counts.to_dict()
    
    # 1.1.3 物种分布
    log("\n3. 物种分布")
    if 'organism' in samples.columns:
        org_counts = samples['organism'].value_counts()
        log(f"  主要物种:")
        for org, cnt in org_counts.head(5).items():
            log(f"    {org}: {cnt:,} ({cnt/len(samples)*100:.1f}%)")
        results['organism_distribution'] = org_counts.to_dict()
    
    return results

def analyze_completeness(samples, series, projects, celltypes):
    """任务1.2: 字段级完整性分析"""
    log("\n" + "="*60)
    log("任务1.2: 字段级完整性分析")
    log("="*60)
    
    results = {}
    
    # 定义关键字段
    critical_fields = {
        'samples': [
            'sample_id', 'organism', 'tissue', 'cell_type', 'disease',
            'sex', 'age', 'development_stage', 'individual_id',
            'n_cells', 'biological_identity_hash'
        ],
        'series': [
            'series_id', 'assay', 'cell_count', 'gene_count'
        ],
        'projects': [
            'project_id', 'title', 'pmid', 'doi', 'publication_date'
        ],
        'celltypes': [
            'cell_type_name', 'sample_pk'
        ]
    }
    
    # 计算各字段填充率
    completeness = {}
    
    log("\nSamples 表关键字段填充率:")
    samples_comp = {}
    for field in critical_fields['samples']:
        if field in samples.columns:
            filled = samples[field].notna().sum()
            rate = filled / len(samples) * 100
            samples_comp[field] = {'filled': int(filled), 'rate': round(rate, 2)}
            status = "✓" if rate >= 70 else "⚠" if rate >= 50 else "✗"
            log(f"  {status} {field}: {rate:.1f}% ({filled:,}/{len(samples):,})")
    completeness['samples'] = samples_comp
    
    log("\nProjects 表关键字段填充率:")
    projects_comp = {}
    for field in critical_fields['projects']:
        if field in projects.columns:
            filled = projects[field].notna().sum()
            rate = filled / len(projects) * 100
            projects_comp[field] = {'filled': int(filled), 'rate': round(rate, 2)}
            status = "✓" if rate >= 70 else "⚠" if rate >= 50 else "✗"
            log(f"  {status} {field}: {rate:.1f}% ({filled:,}/{len(projects):,})")
    completeness['projects'] = projects_comp
    
    log("\nSeries 表关键字段填充率:")
    series_comp = {}
    for field in critical_fields['series']:
        if field in series.columns:
            filled = series[field].notna().sum()
            rate = filled / len(series) * 100
            series_comp[field] = {'filled': int(filled), 'rate': round(rate, 2)}
            status = "✓" if rate >= 70 else "⚠" if rate >= 50 else "✗"
            log(f"  {status} {field}: {rate:.1f}% ({filled:,}/{len(series):,})")
    completeness['series'] = series_comp
    
    results['field_completeness'] = completeness
    
    # 按数据源分层分析
    log("\n按数据源分层的关键字段填充率 (samples):")
    source_completeness = {}
    if 'sample_source' in samples.columns:
        for source in samples['sample_source'].unique():
            if pd.isna(source):
                continue
            source_data = samples[samples['sample_source'] == source]
            source_completeness[source] = {}
            log(f"\n  {source} (n={len(source_data):,}):")
            for field in ['organism', 'tissue', 'cell_type', 'disease', 'sex', 'age']:
                if field in source_data.columns:
                    rate = source_data[field].notna().sum() / len(source_data) * 100
                    source_completeness[source][field] = round(rate, 2)
                    log(f"    {field}: {rate:.1f}%")
    
    results['source_completeness'] = source_completeness
    
    return results

def analyze_hierarchy_integrity(samples, series, projects, celltypes):
    """任务1.3: 层级关系完整性验证"""
    log("\n" + "="*60)
    log("任务1.3: 层级关系完整性验证")
    log("="*60)
    
    results = {}
    
    # 检查celltype -> sample的关联
    log("\n1. Celltype -> Sample 关联完整性")
    valid_sample_pks = set(samples['pk'].dropna())
    ct_with_valid_sample = celltypes['sample_pk'].isin(valid_sample_pks).sum()
    ct_invalid = len(celltypes) - ct_with_valid_sample
    log(f"  有效关联: {ct_with_valid_sample:,} / {len(celltypes):,} ({ct_with_valid_sample/len(celltypes)*100:.1f}%)")
    if ct_invalid > 0:
        log(f"  ⚠️ 孤儿celltype记录: {ct_invalid:,}")
    results['celltype_sample_link'] = {
        'valid': int(ct_with_valid_sample),
        'invalid': int(ct_invalid),
        'valid_rate': round(ct_with_valid_sample/len(celltypes)*100, 2)
    }
    
    # 检查sample -> series的关联
    log("\n2. Sample -> Series 关联完整性")
    valid_series_pks = set(series['pk'].dropna())
    samp_with_series = samples['series_pk'].isin(valid_series_pks).sum()
    samp_without_series = len(samples) - samp_with_series
    log(f"  有关联的sample: {samp_with_series:,} / {len(samples):,} ({samp_with_series/len(samples)*100:.1f}%)")
    log(f"  无series关联: {samp_without_series:,} ({samp_without_series/len(samples)*100:.1f}%)")
    results['sample_series_link'] = {
        'with_series': int(samp_with_series),
        'without_series': int(samp_without_series),
        'link_rate': round(samp_with_series/len(samples)*100, 2)
    }
    
    # 检查sample -> project的关联
    log("\n3. Sample -> Project 关联完整性")
    valid_project_pks = set(projects['pk'].dropna())
    samp_with_project = samples['project_pk'].isin(valid_project_pks).sum()
    samp_without_project = len(samples) - samp_with_project
    log(f"  有关联的sample: {samp_with_project:,} / {len(samples):,} ({samp_with_project/len(samples)*100:.1f}%)")
    results['sample_project_link'] = {
        'with_project': int(samp_with_project),
        'without_project': int(samp_without_project),
        'link_rate': round(samp_with_project/len(samples)*100, 2)
    }
    
    return results

# ============================================================
# 阶段二：跨数据库一致性分析
# ============================================================

def analyze_standardization(samples, projects):
    """任务2.1: 词汇标准化评估"""
    log("\n" + "="*60)
    log("任务2.1: 词汇标准化评估")
    log("="*60)
    
    results = {}
    
    # Organism标准化
    log("\n1. Organism标准化分析")
    if 'organism' in samples.columns:
        org_values = samples['organism'].dropna().unique()
        log(f"  唯一值数量: {len(org_values)}")
        log(f"  值列表: {list(org_values)[:10]}...")
        
        # 检测变体
        org_lower = [str(o).lower().strip() for o in org_values]
        if len(set(org_lower)) < len(org_values):
            log(f"  ⚠️ 检测到大小写/空格变体")
        results['organism_unique_count'] = len(org_values)
    
    # Tissue标准化
    log("\n2. Tissue标准化分析")
    if 'tissue' in samples.columns:
        tissue_counts = samples['tissue'].value_counts()
        log(f"  唯一tissue值: {len(tissue_counts):,}")
        log(f"  最频繁的tissue:")
        for tissue, cnt in tissue_counts.head(10).items():
            log(f"    {tissue}: {cnt:,}")
        
        # 计算标准化程度指标
        # 如果唯一值太多，可能意味着标准化不足
        uniqueness_ratio = len(tissue_counts) / samples['tissue'].notna().sum()
        log(f"  标准化指标（唯一值/总数）: {uniqueness_ratio:.4f}")
        results['tissue_standardization'] = {
            'unique_count': len(tissue_counts),
            'uniqueness_ratio': round(uniqueness_ratio, 4),
            'top10': tissue_counts.head(10).to_dict()
        }
    
    # Disease标准化
    log("\n3. Disease标准化分析")
    if 'disease' in samples.columns:
        disease_counts = samples['disease'].value_counts()
        log(f"  唯一disease值: {len(disease_counts):,}")
        log(f"  最频繁的disease:")
        for disease, cnt in disease_counts.head(10).items():
            if pd.notna(disease):
                log(f"    {disease}: {cnt:,}")
        results['disease_standardization'] = {
            'unique_count': len(disease_counts),
            'top10': {k: v for k, v in disease_counts.head(10).items() if pd.notna(k)}
        }
    
    return results

def analyze_ontology_usage(samples, series):
    """任务2.2: Ontology覆盖率分析"""
    log("\n" + "="*60)
    log("任务2.2: Ontology覆盖率分析")
    log("="*60)
    
    results = {}
    
    ontology_fields = [
        'tissue_ontology_term_id',
        'cell_type_ontology_term_id',
        'disease_ontology_term_id',
        'sex_ontology_term_id'
    ]
    
    log("\n各字段Ontology ID覆盖率:")
    for field in ontology_fields:
        if field in samples.columns:
            coverage = samples[field].notna().sum() / len(samples) * 100
            log(f"  {field}: {coverage:.1f}%")
            results[field] = round(coverage, 2)
    
    # 按数据源分析
    log("\n按数据源的Ontology覆盖率:")
    if 'sample_source' in samples.columns:
        for source in samples['sample_source'].unique()[:5]:
            if pd.isna(source):
                continue
            source_data = samples[samples['sample_source'] == source]
            log(f"\n  {source}:")
            for field in ['tissue_ontology_term_id', 'cell_type_ontology_term_id']:
                if field in source_data.columns:
                    coverage = source_data[field].notna().sum() / len(source_data) * 100
                    log(f"    {field}: {coverage:.1f}%")
    
    return results

def analyze_numerical_quality(samples, series, projects):
    """任务2.3: 数值字段质量分析"""
    log("\n" + "="*60)
    log("任务2.3: 数值字段质量分析")
    log("="*60)
    
    results = {}
    
    # n_cells分析
    log("\n1. n_cells 统计分析")
    if 'n_cells' in samples.columns:
        n_cells = samples['n_cells'].dropna()
        log(f"  有效记录: {len(n_cells):,}")
        log(f"  均值: {n_cells.mean():.0f}")
        log(f"  中位数: {n_cells.median():.0f}")
        log(f"  范围: {n_cells.min():.0f} - {n_cells.max():.0f}")
        log(f"  95%分位数: {n_cells.quantile(0.95):.0f}")
        
        # 异常值检测（IQR法则）
        Q1 = n_cells.quantile(0.25)
        Q3 = n_cells.quantile(0.75)
        IQR = Q3 - Q1
        outliers = n_cells[(n_cells < Q1 - 1.5*IQR) | (n_cells > Q3 + 1.5*IQR)]
        log(f"  异常值数量: {len(outliers):,} ({len(outliers)/len(n_cells)*100:.1f}%)")
        
        results['n_cells'] = {
            'mean': round(n_cells.mean(), 2),
            'median': round(n_cells.median(), 2),
            'min': int(n_cells.min()),
            'max': int(n_cells.max()),
            'p95': round(n_cells.quantile(0.95), 2),
            'outlier_count': int(len(outliers)),
            'outlier_rate': round(len(outliers)/len(n_cells)*100, 2)
        }
    
    # citation_count分析
    log("\n2. citation_count 统计分析")
    if 'citation_count' in projects.columns:
        citations = projects['citation_count'].dropna()
        log(f"  有效记录: {len(citations):,}")
        log(f"  均值: {citations.mean():.1f}")
        log(f"  中位数: {citations.median():.1f}")
        log(f"  范围: {citations.min():.0f} - {citations.max():.0f}")
        log(f"  零引用论文: {(citations == 0).sum():,} ({(citations == 0).sum()/len(citations)*100:.1f}%)")
        
        results['citation_count'] = {
            'mean': round(citations.mean(), 2),
            'median': round(citations.median(), 2),
            'zero_count': int((citations == 0).sum()),
            'zero_rate': round((citations == 0).sum()/len(citations)*100, 2)
        }
    
    return results

# ============================================================
# 阶段三：数据可信度评估
# ============================================================

def detect_duplicates(samples):
    """任务3.1: 重复数据检测"""
    log("\n" + "="*60)
    log("任务3.1: 重复数据检测")
    log("="*60)
    
    results = {}
    
    # 基于biological_identity_hash的精确重复
    log("\n1. 基于 biological_identity_hash 的重复")
    if 'biological_identity_hash' in samples.columns:
        hash_counts = samples['biological_identity_hash'].value_counts()
        duplicates = hash_counts[hash_counts > 1]
        log(f"  唯一hash值: {len(hash_counts):,}")
        log(f"  重复hash值: {len(duplicates):,}")
        log(f"  涉及重复的记录: {duplicates.sum():,}")
        if len(duplicates) > 0:
            log(f"  最大重复次数: {duplicates.max()}")
        results['hash_duplicates'] = {
            'unique_hashes': len(hash_counts),
            'duplicate_hashes': len(duplicates),
            'records_involved': int(duplicates.sum()) if len(duplicates) > 0 else 0
        }
    
    # 基于sample_id的重复
    log("\n2. 基于 sample_id + source_database 的重复")
    if 'sample_id' in samples.columns and 'sample_source' in samples.columns:
        dup_mask = samples.duplicated(subset=['sample_id', 'sample_source'], keep=False)
        dup_records = samples[dup_mask]
        log(f"  重复记录数: {len(dup_records):,}")
        results['id_duplicates'] = {
            'duplicate_records': int(len(dup_records))
        }
    
    return results

def check_biological_plausibility(samples):
    """任务3.2: 生物学合理性检查"""
    log("\n" + "="*60)
    log("任务3.2: 生物学合理性检查")
    log("="*60)
    
    results = {}
    
    # 这里实施一些基本的合理性规则
    # 注意：由于数据复杂性，这里只做简单的检查
    
    log("\n1. 基本统计检查")
    
    # 性别值检查
    if 'sex' in samples.columns:
        valid_sex = ['male', 'female', 'unknown', 'mixed']
        sex_values = samples['sex'].dropna().unique()
        invalid_sex = [s for s in sex_values if s not in valid_sex]
        if invalid_sex:
            log(f"  ⚠️ 非标准sex值: {invalid_sex[:10]}")
        results['sex_validation'] = {
            'valid_values': valid_sex,
            'invalid_values_found': len(invalid_sex)
        }
    
    # 年龄合理性
    if 'age' in samples.columns:
        # 尝试提取数值
        age_numeric = pd.to_numeric(samples['age'], errors='coerce')
        invalid_age = ((age_numeric < 0) | (age_numeric > 120)).sum()
        if invalid_age > 0:
            log(f"  ⚠️ 不合理年龄值: {invalid_age} 条")
        results['age_validation'] = {
            'invalid_age_count': int(invalid_age)
        }
    
    return results

def analyze_citation_quality(projects):
    """任务3.3: 引用数据质量"""
    log("\n" + "="*60)
    log("任务3.3: 引用数据质量")
    log("="*60)
    
    results = {}
    
    # PMID格式检查
    if 'pmid' in projects.columns:
        pmids = projects['pmid'].dropna()
        # PMID通常是8位数字
        valid_pmid = pmids.str.match(r'^\d{1,8}$').sum()
        log(f"  PMID记录数: {len(pmids):,}")
        log(f"  格式有效的PMID: {valid_pmid:,}")
        results['pmid_quality'] = {
            'total': len(pmids),
            'valid_format': int(valid_pmid)
        }
    
    # DOI格式检查
    if 'doi' in projects.columns:
        dois = projects['doi'].dropna()
        # 基本DOI格式: 10.xxxx/...
        valid_doi = dois.str.match(r'^10\.\d{4,}/.+').sum()
        log(f"  DOI记录数: {len(dois):,}")
        log(f"  格式有效的DOI: {valid_doi:,}")
        results['doi_quality'] = {
            'total': len(dois),
            'valid_format': int(valid_doi)
        }
    
    return results

# ============================================================
# 阶段四：综合质量评分
# ============================================================

def calculate_quality_scores(completeness_results, consistency_results, 
                            integrity_results, duplicates_results):
    """计算综合质量评分"""
    log("\n" + "="*60)
    log("阶段四: 综合质量评分")
    log("="*60)
    
    scores = {}
    
    # 完整性评分 (40%)
    if 'field_completeness' in completeness_results:
        samples_comp = completeness_results['field_completeness'].get('samples', {})
        critical_rates = []
        for field in ['organism', 'tissue', 'cell_type', 'disease', 'sex']:
            if field in samples_comp:
                critical_rates.append(samples_comp[field]['rate'])
        
        if critical_rates:
            completeness_score = np.mean(critical_rates)
        else:
            completeness_score = 0
    else:
        completeness_score = 0
    
    # 一致性评分 (35%)
    consistency_score = 70  # 基于观察的默认评分
    if 'tissue_standardization' in consistency_results:
        ratio = consistency_results['tissue_standardization'].get('uniqueness_ratio', 1)
        # 唯一值比例越低越好
        consistency_score = min(100, max(0, (1 - ratio) * 100))
    
    # 准确性评分 (25%)
    accuracy_score = 80  # 默认评分
    if 'hash_duplicates' in duplicates_results:
        dup_rate = duplicates_results['hash_duplicates'].get('records_involved', 0) / 756579 * 100
        accuracy_score = max(0, 100 - dup_rate * 10)
    
    # 加权总分
    total_score = (completeness_score * 0.4 + 
                   consistency_score * 0.35 + 
                   accuracy_score * 0.25)
    
    log(f"\n质量评分:")
    log(f"  完整性评分 (40%): {completeness_score:.1f}")
    log(f"  一致性评分 (35%): {consistency_score:.1f}")
    log(f"  准确性评分 (25%): {accuracy_score:.1f}")
    log(f"  综合评分: {total_score:.1f}")
    
    # 分级
    if total_score >= 85:
        grade = "A级 (优秀)"
    elif total_score >= 70:
        grade = "B级 (良好)"
    elif total_score >= 60:
        grade = "C级 (可接受)"
    else:
        grade = "D级 (需改进)"
    
    log(f"  等级: {grade}")
    
    scores = {
        'completeness': round(completeness_score, 2),
        'consistency': round(consistency_score, 2),
        'accuracy': round(accuracy_score, 2),
        'total': round(total_score, 2),
        'grade': grade
    }
    
    return scores

# ============================================================
# 主函数
# ============================================================

def main():
    """主函数"""
    log("="*60)
    log("单细胞元数据库质量评估")
    log("="*60)
    
    # 加载数据
    projects, series, samples, celltypes = load_data()
    
    # 执行所有评估任务
    all_results = {}
    
    # 阶段一
    all_results['global_profile'] = analyze_global_profile(projects, series, samples, celltypes)
    all_results['completeness'] = analyze_completeness(samples, series, projects, celltypes)
    all_results['hierarchy_integrity'] = analyze_hierarchy_integrity(samples, series, projects, celltypes)
    
    # 阶段二
    all_results['standardization'] = analyze_standardization(samples, projects)
    all_results['ontology_usage'] = analyze_ontology_usage(samples, series)
    all_results['numerical_quality'] = analyze_numerical_quality(samples, series, projects)
    
    # 阶段三
    all_results['duplicates'] = detect_duplicates(samples)
    all_results['plausibility'] = check_biological_plausibility(samples)
    all_results['citation_quality'] = analyze_citation_quality(projects)
    
    # 阶段四
    all_results['quality_scores'] = calculate_quality_scores(
        all_results['completeness'],
        all_results['standardization'],
        all_results['hierarchy_integrity'],
        all_results['duplicates']
    )
    
    # 保存结果
    output_file = RESULTS_DIR / "data_quality_assessment_results.json"
    with open(output_file, 'w') as f:
        json.dump(all_results, f, indent=2, default=str)
    
    log("\n" + "="*60)
    log(f"评估完成! 结果已保存至: {output_file}")
    log("="*60)
    
    return all_results

if __name__ == "__main__":
    results = main()
