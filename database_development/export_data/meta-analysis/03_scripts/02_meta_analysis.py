#!/usr/bin/env python3
"""
单细胞元数据Meta分析脚本
Meta-Analysis for Single-Cell Metadata

执行meta分析方案书中的所有分析任务
"""

import pandas as pd
import numpy as np
import json
from pathlib import Path
from datetime import datetime
from scipy import stats
import warnings
warnings.filterwarnings('ignore')

# 路径设置
DATA_DIR = Path(__file__).parent.parent / "02_data"
RESULTS_DIR = Path(__file__).parent.parent / "04_results"
RESULTS_DIR.mkdir(exist_ok=True)

def log(msg):
    """打印带时间戳的日志"""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def load_and_clean_data():
    """加载并清洗数据"""
    log("加载数据...")
    
    # 加载基础表（避免合并表的格式问题）
    log("  加载 samples 表...")
    samples = pd.read_csv(DATA_DIR / "03_samples.csv")
    log(f"    记录数: {len(samples):,}")
    
    log("  加载 series 表...")
    series = pd.read_csv(DATA_DIR / "02_series.csv")
    log(f"    记录数: {len(series):,}")
    
    log("  加载 projects 表...")
    projects = pd.read_csv(DATA_DIR / "01_projects.csv")
    log(f"    记录数: {len(projects):,}")
    
    # 合并数据
    log("  合并数据...")
    df = samples.copy()
    
    # 重命名samples中的source_database避免冲突
    df = df.rename(columns={'source_database': 'sample_source'})
    
    # 合并 series
    series_cols = ['pk', 'assay', 'cell_count', 'gene_count', 'source_database']
    series_subset = series[series_cols].copy()
    series_subset = series_subset.rename(columns={
        'pk': 'series_pk',
        'source_database': 'series_source'
    })
    df = df.merge(series_subset, on='series_pk', how='left')
    
    # 合并 projects
    project_cols = ['pk', 'pmid', 'doi', 'publication_date', 'citation_count', 'source_database']
    project_subset = projects[project_cols].copy()
    project_subset = project_subset.rename(columns={
        'pk': 'project_pk',
        'source_database': 'project_source'
    })
    df = df.merge(project_subset, on='project_pk', how='left')
    
    log(f"  合并后记录数: {len(df):,}")
    
    # 数据清洗
    log("数据清洗...")
    
    # 1. 提取有效的年份
    if 'publication_date' in df.columns:
        df['year'] = pd.to_datetime(df['publication_date'], errors='coerce').dt.year
    
    # 2. 清洗citation_count
    if 'citation_count' in df.columns:
        df['citation_count'] = pd.to_numeric(df['citation_count'], errors='coerce')
        df['log_citation'] = np.log1p(df['citation_count'])
    
    # 3. 清洗n_cells
    if 'n_cells' in df.columns:
        df['n_cells'] = pd.to_numeric(df['n_cells'], errors='coerce')
        # 去除极端异常值
        df.loc[(df['n_cells'] < 100) | (df['n_cells'] > 1000000), 'n_cells'] = np.nan
        df['log_n_cells'] = np.log1p(df['n_cells'])
    
    # 4. 标准化assay
    if 'assay' in df.columns:
        df['assay_category'] = df['assay'].apply(categorize_assay)
    
    # 5. 标准化disease
    if 'disease' in df.columns:
        df['disease_category'] = df['disease'].apply(categorize_disease)
    
    # 6. 标准化data_availability
    if 'data_availability' in df.columns:
        df['data_availability'] = df['data_availability'].fillna('unknown')
    
    # 排除标准
    initial_n = len(df)
    df = df[df['year'] >= 2015]  # 排除2015年前的数据
    df = df[df['year'] <= 2026]  # 排除未来日期
    
    log(f"  清洗后记录数: {len(df):,} (排除了 {initial_n - len(df):,} 条)")
    
    return df

def categorize_assay(assay):
    """将assay归类为技术平台"""
    if pd.isna(assay):
        return 'Unknown'
    
    assay_str = str(assay).lower()
    
    if '10x' in assay_str or 'chromium' in assay_str:
        return '10x Genomics'
    elif 'smart-seq' in assay_str:
        return 'Smart-seq'
    elif 'drop-seq' in assay_str:
        return 'Drop-seq'
    elif 'seq-well' in assay_str:
        return 'Seq-Well'
    else:
        return 'Other'

def categorize_disease(disease):
    """将疾病归类"""
    if pd.isna(disease):
        return 'Not specified'
    
    disease_str = str(disease).lower()
    
    if any(x in disease_str for x in ['normal', 'healthy', 'control']):
        return 'Normal/Healthy'
    elif any(x in disease_str for x in ['cancer', 'carcinoma', 'tumor', 'melanoma', 'leukemia', 'lymphoma']):
        return 'Cancer'
    elif any(x in disease_str for x in ['covid', 'sars-cov']):
        return 'COVID-19'
    elif any(x in disease_str for x in ['diabetes', 't1d', 't2d']):
        return 'Diabetes'
    elif any(x in disease_str for x in ['alzheimer', 'parkinson', 'dementia', 'epilepsy']):
        return 'Neurological'
    elif any(x in disease_str for x in ['arthritis', 'lupus', 'scleroderma']):
        return 'Autoimmune'
    elif any(x in disease_str for x in ['infection', 'virus', 'bacterial']):
        return 'Infectious'
    else:
        return 'Other Disease'

# ============================================================
# 主题一：数据共享与科学影响力
# ============================================================

def analyze_data_sharing_impact(df):
    """主题一：数据共享与引用量的关系"""
    log("\n" + "="*60)
    log("主题一: 数据共享与科学影响力")
    log("="*60)
    
    results = {}
    
    # 分析1.1: 开放数据 vs 引用量
    log("\n分析1.1: 数据可用性与引用量的关系")
    
    # 根据project_source判断数据可用性
    df['access_type'] = df['project_source'].apply(
        lambda x: 'Open' if x == 'cellxgene' else 
                  'Controlled' if x in ['ega', 'dbgap'] else 'Open'
    )
    
    # 统计各类型引用
    citation_by_access = df.groupby('access_type')['citation_count'].agg([
        'count', 'mean', 'median', 'std'
    ]).round(2)
    
    log("\n各数据可用性类型的引用统计:")
    log(citation_by_access.to_string())
    results['citation_by_access'] = citation_by_access.to_dict()
    
    # 非参数检验（Kruskal-Wallis）
    open_cit = df[df['access_type'] == 'Open']['citation_count'].dropna()
    ctrl_cit = df[df['access_type'] == 'Controlled']['citation_count'].dropna()
    
    if len(open_cit) > 0 and len(ctrl_cit) > 0:
        statistic, p_value = stats.kruskal(open_cit, ctrl_cit)
        log(f"\nKruskal-Wallis检验:")
        log(f"  H统计量: {statistic:.2f}")
        log(f"  p值: {p_value:.2e}")
        results['kruskal_test'] = {'H': statistic, 'p': p_value}
    
    # 分析1.2: 不同数据库的引用差异
    log("\n分析1.2: 不同数据源的引用比较")
    
    db_citation = df.groupby('project_source')['citation_count'].agg([
        'count', 'mean', 'median'
    ]).round(2)
    db_citation = db_citation[db_citation['count'] >= 100]  # 至少100条记录
    db_citation = db_citation.sort_values('mean', ascending=False)
    
    log("\n主要数据源的引用统计（至少100条记录）:")
    log(db_citation.head(10).to_string())
    results['citation_by_database'] = db_citation.to_dict()
    
    # 分析1.3: 发表年份与引用关系（时间趋势）
    log("\n分析1.3: 引用量的时间分布")
    
    year_citation = df.groupby('year')['citation_count'].agg([
        'count', 'mean', 'median'
    ]).round(2)
    year_citation = year_citation[year_citation.index <= 2024]  # 排除最近年份
    
    log("\n各年份平均引用量:")
    log(year_citation.to_string())
    results['citation_by_year'] = year_citation.to_dict()
    
    return results

# ============================================================
# 主题二：技术演进与数据特征
# ============================================================

def analyze_technology_evolution(df):
    """主题二：技术平台演进分析"""
    log("\n" + "="*60)
    log("主题二: 技术演进与数据特征")
    log("="*60)
    
    results = {}
    
    # 分析2.1: 技术平台分布
    log("\n分析2.1: 技术平台分布")
    
    assay_dist = df['assay_category'].value_counts()
    assay_pct = df['assay_category'].value_counts(normalize=True) * 100
    
    log("\n技术平台分布:")
    for assay in assay_dist.index:
        log(f"  {assay}: {assay_dist[assay]:,} ({assay_pct[assay]:.1f}%)")
    
    results['assay_distribution'] = assay_dist.to_dict()
    
    # 分析2.2: 技术平台与细胞产出
    log("\n分析2.2: 技术平台的细胞产出比较")
    
    assay_cells = df.groupby('assay_category')['n_cells'].agg([
        'count', 'mean', 'median', 'std'
    ]).round(2)
    assay_cells = assay_cells[assay_cells['count'] >= 100]
    assay_cells = assay_cells.sort_values('median', ascending=False)
    
    log("\n各技术平台的细胞产出统计（至少100条记录）:")
    log(assay_cells.to_string())
    results['cells_by_assay'] = assay_cells.to_dict()
    
    # 方差分析
    assay_groups = []
    assay_names = []
    for assay in df['assay_category'].unique():
        if assay != 'Unknown':
            cells = df[df['assay_category'] == assay]['n_cells'].dropna()
            if len(cells) >= 100:
                assay_groups.append(cells)
                assay_names.append(assay)
    
    if len(assay_groups) >= 2:
        f_stat, p_value = stats.f_oneway(*assay_groups)
        log(f"\nANOVA检验（细胞数差异）:")
        log(f"  F统计量: {f_stat:.2f}")
        log(f"  p值: {p_value:.2e}")
        results['anova_assay'] = {'F': f_stat, 'p': p_value}
    
    # 分析2.3: 技术采纳趋势
    log("\n分析2.3: 技术采纳时间趋势")
    
    tech_trend = df.groupby(['year', 'assay_category']).size().unstack(fill_value=0)
    tech_trend_pct = tech_trend.div(tech_trend.sum(axis=1), axis=0) * 100
    tech_trend_pct = tech_trend_pct[tech_trend_pct.index <= 2024]
    
    log("\n各年份技术平台占比(%):")
    log(tech_trend_pct.to_string())
    results['tech_trend'] = tech_trend_pct.to_dict()
    
    return results

# ============================================================
# 主题三：疾病研究的数据景观
# ============================================================

def analyze_disease_landscape(df):
    """主题三：疾病数据景观分析"""
    log("\n" + "="*60)
    log("主题三: 疾病研究的数据景观")
    log("="*60)
    
    results = {}
    
    # 分析3.1: 疾病领域分布
    log("\n分析3.1: 疾病领域分布")
    
    disease_dist = df['disease_category'].value_counts()
    disease_pct = df['disease_category'].value_counts(normalize=True) * 100
    
    log("\n疾病领域样本分布:")
    for disease in disease_dist.index:
        log(f"  {disease}: {disease_dist[disease]:,} ({disease_pct[disease]:.1f}%)")
    
    results['disease_distribution'] = disease_dist.to_dict()
    
    # 分析3.2: 疾病研究的细胞数特征
    log("\n分析3.2: 不同疾病领域的细胞产出")
    
    disease_cells = df.groupby('disease_category')['n_cells'].agg([
        'count', 'mean', 'median', 'sum'
    ]).round(2)
    disease_cells = disease_cells.sort_values('sum', ascending=False)
    
    log("\n各疾病领域的细胞统计（按总细胞数排序）:")
    log(disease_cells.to_string())
    results['cells_by_disease'] = disease_cells.to_dict()
    
    # 分析3.3: 疾病数据的时间趋势
    log("\n分析3.3: 主要疾病领域的时间趋势")
    
    top_diseases = disease_dist.head(5).index.tolist()
    disease_trend = df[df['disease_category'].isin(top_diseases)].groupby(['year', 'disease_category']).size().unstack(fill_value=0)
    disease_trend = disease_trend[disease_trend.index <= 2024]
    
    log("\n主要疾病领域年度样本数:")
    log(disease_trend.to_string())
    results['disease_trend'] = disease_trend.to_dict()
    
    return results

# ============================================================
# 主题四：样本特征与研究设计
# ============================================================

def analyze_sample_characteristics(df):
    """主题四：样本特征分析"""
    log("\n" + "="*60)
    log("主题四: 样本特征与研究设计")
    log("="*60)
    
    results = {}
    
    # 分析4.1: 性别分布
    log("\n分析4.1: 性别分布")
    
    if 'sex' in df.columns:
        # 标准化性别值
        df['sex_clean'] = df['sex'].apply(
            lambda x: x if pd.notna(x) and x in ['male', 'female'] else 'unknown'
        )
        
        sex_dist = df['sex_clean'].value_counts()
        sex_pct = df['sex_clean'].value_counts(normalize=True) * 100
        
        log("\n性别分布:")
        for sex in sex_dist.index:
            log(f"  {sex}: {sex_dist[sex]:,} ({sex_pct[sex]:.1f}%)")
        
        results['sex_distribution'] = sex_dist.to_dict()
    
    # 分析4.2: 年龄分布
    log("\n分析4.2: 年龄分布")
    
    if 'age' in df.columns:
        # 提取数值年龄
        df['age_numeric'] = pd.to_numeric(df['age'], errors='coerce')
        df_age = df[(df['age_numeric'] >= 0) & (df['age_numeric'] <= 120)]
        
        age_stats = df_age['age_numeric'].describe()
        log("\n年龄统计（排除异常值）:")
        log(f"  有效记录: {df_age['age_numeric'].notna().sum():,}")
        log(f"  均值: {age_stats['mean']:.1f}")
        log(f"  中位数: {age_stats['50%']:.1f}")
        log(f"  标准差: {age_stats['std']:.1f}")
        log(f"  范围: {age_stats['min']:.0f} - {age_stats['max']:.0f}")
        
        results['age_stats'] = age_stats.to_dict()
    
    # 分析4.3: 组织分布
    log("\n分析4.3: 组织分布（Top 15）")
    
    if 'tissue' in df.columns:
        tissue_dist = df['tissue'].value_counts().head(15)
        
        log("\nTop 15 组织类型:")
        for tissue, count in tissue_dist.items():
            log(f"  {tissue}: {count:,}")
        
        results['top_tissues'] = tissue_dist.to_dict()
    
    # 分析4.4: 物种分布
    log("\n分析4.4: 物种分布")
    
    if 'organism' in df.columns:
        organism_dist = df['organism'].value_counts().head(10)
        organism_pct = df['organism'].value_counts(normalize=True).head(10) * 100
        
        log("\nTop 10 物种:")
        for org in organism_dist.index:
            log(f"  {org}: {organism_dist[org]:,} ({organism_pct[org]:.1f}%)")
        
        results['organism_distribution'] = organism_dist.to_dict()
    
    return results

# ============================================================
# 主题五：数据生产的时间动态
# ============================================================

def analyze_temporal_dynamics(df):
    """主题五：时间动态分析"""
    log("\n" + "="*60)
    log("主题五: 数据生产的时间动态")
    log("="*60)
    
    results = {}
    
    # 分析5.1: 年度数据产量
    log("\n分析5.1: 年度数据产量")
    
    year_counts = df.groupby('year').agg({
        'pk': 'count',
        'n_cells': 'sum'
    }).rename(columns={'pk': 'sample_count'})
    year_counts = year_counts[year_counts.index <= 2024]
    
    log("\n各年度数据产量:")
    log(year_counts.to_string())
    results['yearly_production'] = year_counts.to_dict()
    
    # 计算增长率
    log("\n年度增长率:")
    for i in range(1, len(year_counts)):
        if year_counts.index[i-1] >= 2018:  # 从2018年开始计算
            prev = year_counts.iloc[i-1]['sample_count']
            curr = year_counts.iloc[i]['sample_count']
            if prev > 0:
                growth = (curr - prev) / prev * 100
                log(f"  {int(year_counts.index[i-1])}->{int(year_counts.index[i])}: {growth:+.1f}%")
    
    # 分析5.2: COVID-19影响
    log("\n分析5.2: COVID-19对数据生产的影响")
    
    # 呼吸系统相关数据
    respiratory = df[df['tissue'].str.contains('lung|respiratory|bronchial', case=False, na=False)]
    
    pre_covid = respiratory[respiratory['year'].isin([2018, 2019])]
    covid_period = respiratory[respiratory['year'].isin([2020, 2021])]
    
    log("\n呼吸系统研究样本数:")
    log(f"  2018-2019 (COVID前): {len(pre_covid):,}")
    log(f"  2020-2021 (COVID期): {len(covid_period):,}")
    
    if len(pre_covid) > 0:
        change = (len(covid_period) - len(pre_covid)) / len(pre_covid) * 100
        log(f"  变化: {change:+.1f}%")
    
    results['covid_impact'] = {
        'pre_covid': len(pre_covid),
        'covid_period': len(covid_period)
    }
    
    # 分析5.3: 数据质量的时间趋势
    log("\n分析5.3: 元数据完整性的时间趋势")
    
    # 计算每年的元数据完整度评分
    def calc_completeness_score(row):
        fields = ['tissue', 'cell_type', 'disease', 'sex', 'age']
        score = sum([1 for f in fields if pd.notna(row[f])]) / len(fields) * 100
        return score
    
    df['completeness_score'] = df.apply(calc_completeness_score, axis=1)
    
    quality_trend = df.groupby('year')['completeness_score'].mean()
    quality_trend = quality_trend[quality_trend.index <= 2024]
    
    log("\n各年度平均元数据完整度评分:")
    for year, score in quality_trend.items():
        log(f"  {int(year)}: {score:.1f}")
    
    results['quality_trend'] = quality_trend.to_dict()
    
    return results

# ============================================================
# 主函数
# ============================================================

def main():
    """主函数"""
    log("="*60)
    log("单细胞元数据Meta分析")
    log("="*60)
    
    # 加载和清洗数据
    df = load_and_clean_data()
    
    # 执行所有分析
    all_results = {}
    
    all_results['data_sharing_impact'] = analyze_data_sharing_impact(df)
    all_results['technology_evolution'] = analyze_technology_evolution(df)
    all_results['disease_landscape'] = analyze_disease_landscape(df)
    all_results['sample_characteristics'] = analyze_sample_characteristics(df)
    all_results['temporal_dynamics'] = analyze_temporal_dynamics(df)
    
    # 保存分析结果
    output_file = RESULTS_DIR / "meta_analysis_results.json"
    with open(output_file, 'w') as f:
        json.dump(all_results, f, indent=2, default=str)
    
    log("\n" + "="*60)
    log(f"分析完成! 结果已保存至: {output_file}")
    log("="*60)
    
    return all_results, df

if __name__ == "__main__":
    results, df = main()
