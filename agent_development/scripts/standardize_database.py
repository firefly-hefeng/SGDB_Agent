#!/usr/bin/env python3
"""
数据库标准化脚本
清洗和标准化疾病名称、组织名称、平台名称等字段
生成高质量的统一数据
"""

import sqlite3
import re
from pathlib import Path
from collections import defaultdict
import json

# 疾病名称标准化映射
DISEASE_MAPPING = {
    # 缩写 -> 标准名称
    'PDAC': 'Pancreatic Ductal Adenocarcinoma',
    'MEL': 'Melanoma',
    'OV': 'Ovarian Cancer',
    'LC': 'Lung Cancer',
    'GBM': 'Glioblastoma',
    'BC': 'Breast Cancer',
    'CRC': 'Colorectal Cancer',
    'HCC': 'Hepatocellular Carcinoma',
    'NSCLC': 'Non-Small Cell Lung Cancer',
    'SCLC': 'Small Cell Lung Cancer',
    'PCa': 'Prostate Cancer',
    'ccRCC': 'Clear Cell Renal Cell Carcinoma',
    'AML': 'Acute Myeloid Leukemia',
    'ALL': 'Acute Lymphoblastic Leukemia',
    'CLL': 'Chronic Lymphocytic Leukemia',
    'CML': 'Chronic Myeloid Leukemia',
    'DLBCL': 'Diffuse Large B-Cell Lymphoma',
    'FL': 'Follicular Lymphoma',
    'BL': 'Burkitt Lymphoma',
    'MM': 'Multiple Myeloma',
    'MDS': 'Myelodysplastic Syndromes',
    
    # 同义词统一
    'COVID19': 'COVID-19',
    'Covid-19': 'COVID-19',
    'covid-19': 'COVID-19',
    'SARS-CoV-2': 'COVID-19',
    
    'Alzheimer': "Alzheimer's Disease",
    'Alzheimer disease': "Alzheimer's Disease",
    'Alzheimers Disease': "Alzheimer's Disease",
    
    'glioblastoma': 'Glioblastoma',
    'Glioblastoma multiforme': 'Glioblastoma',
    
    'colon cancer': 'Colorectal Cancer',
    'colorectal cancer': 'Colorectal Cancer',
    'rectal cancer': 'Colorectal Cancer',
    
    'normal': 'Normal',
    'healthy': 'Normal',
    'control': 'Normal',
}

# 组织名称标准化映射
TISSUE_MAPPING = {
    # 大小写统一
    'blood': 'Blood',
    'liver': 'Liver',
    'lung': 'Lung',
    'brain': 'Brain',
    'heart': 'Heart',
    'kidney': 'Kidney',
    'skin': 'Skin',
    'colon': 'Colon',
    'intestine': 'Intestine',
    'spleen': 'Spleen',
    'thymus': 'Thymus',
    'lymph node': 'Lymph Node',
    'bone marrow': 'Bone Marrow',
    'pancreas': 'Pancreas',
    'stomach': 'Stomach',
    'esophagus': 'Esophagus',
    'bladder': 'Bladder',
    'prostate': 'Prostate',
    'ovary': 'Ovary',
    'uterus': 'Uterus',
    'breast': 'Breast',
    'testis': 'Testis',
    'retina': 'Retina',
    'muscle': 'Muscle',
    'adipose': 'Adipose',
    'fat': 'Adipose',
    'placenta': 'Placenta',
    'cord blood': 'Cord Blood',
    'pbmc': 'PBMC',
    'PBMC': 'PBMC',
    'tumor': 'Tumor',
    'tumour': 'Tumor',
    
    # 需要清理的值
    'total RNA': None,
    'genomic DNA': None,
    'synthetic_RNA': None,
    'synthetic_DNA': None,
    'polyA RNA': None,
    'unknown': None,
    'cell': None,
    'not specified': None,
}

# 平台名称标准化映射
PLATFORM_MAPPING = {
    '10x Genomics': '10x Genomics',
    '10x': '10x Genomics',
    '10X': '10x Genomics',
    '10x genomics': '10x Genomics',
    '10X Genomics': '10x Genomics',
    
    'Smart-seq2': 'Smart-seq2',
    'Smart-seq': 'Smart-seq2',
    'SmartSeq2': 'Smart-seq2',
    'SmartSeq': 'Smart-seq2',
    
    'Drop-seq': 'Drop-seq',
    'DropSeq': 'Drop-seq',
    
    'Seq-Well': 'Seq-Well',
    'SeqWell': 'Seq-Well',
    
    'inDrop': 'inDrop',
    'indrop': 'inDrop',
    
    'CEL-Seq2': 'CEL-Seq2',
    'CEL-Seq': 'CEL-Seq2',
    
    'MARS-seq': 'MARS-seq',
    'MARSseq': 'MARS-seq',
}

def normalize_disease_name(name):
    """标准化疾病名称"""
    if not name or pd.isna(name):
        return None
    
    name = str(name).strip()
    
    # 处理组合值（如 "COVID-19; normal"）
    if ';' in name or '|' in name:
        parts = re.split(r'[;|]', name)
        diseases = []
        for part in parts:
            part = part.strip()
            normalized = normalize_single_disease(part)
            if normalized and normalized != 'Normal':
                diseases.append(normalized)
        
        if diseases:
            # 返回主要疾病，如果有多个用分号分隔
            return '; '.join(list(dict.fromkeys(diseases)))  # 去重保持顺序
        return 'Normal' if 'normal' in name.lower() else None
    
    return normalize_single_disease(name)

def normalize_single_disease(name):
    """标准化单个疾病名称"""
    name = name.strip()
    
    # 直接匹配
    if name in DISEASE_MAPPING:
        return DISEASE_MAPPING[name]
    
    # 大小写不敏感匹配
    name_lower = name.lower()
    for key, value in DISEASE_MAPPING.items():
        if key.lower() == name_lower:
            return value
    
    # 首字母大写
    if name.isupper():
        return name
    
    return name.title() if len(name) > 3 else name.upper()

def normalize_tissue_name(name):
    """标准化组织名称"""
    if not name or pd.isna(name):
        return None
    
    name = str(name).strip().lower()
    
    # 需要清理的值
    if name in ['total rna', 'genomic dna', 'synthetic_rna', 'synthetic_dna', 
                'polya rna', 'unknown', 'cell', 'not specified', '']:
        return None
    
    # 直接匹配
    if name in TISSUE_MAPPING:
        result = TISSUE_MAPPING[name]
        return result if result else None
    
    # 包含匹配
    for key, value in TISSUE_MAPPING.items():
        if key.lower() in name:
            return value if value else None
    
    # 首字母大写
    return name.title()

def normalize_platform_name(name):
    """标准化平台名称"""
    if not name or pd.isna(name):
        return None
    
    name = str(name).strip()
    
    # 直接匹配
    if name in PLATFORM_MAPPING:
        return PLATFORM_MAPPING[name]
    
    # 包含10x
    if re.search(r'10x', name, re.IGNORECASE):
        return '10x Genomics'
    
    # 包含Smart
    if re.search(r'smart', name, re.IGNORECASE):
        return 'Smart-seq2'
    
    return name

def standardize_database(db_path='data/scrnaseq.db', table='std'):
    """标准化数据库"""
    import pandas as pd
    
    print("=" * 80)
    print("🧹 数据库标准化处理")
    print("=" * 80)
    
    conn = sqlite3.connect(db_path)
    
    # 1. 创建新的标准化字段
    print("\n📋 步骤1: 创建标准化字段...")
    
    new_fields = [
        ('disease_clean', 'TEXT'),
        ('disease_category_clean', 'TEXT'),
        ('tissue_clean', 'TEXT'),
        ('platform_clean', 'TEXT'),
    ]
    
    for field_name, field_type in new_fields:
        try:
            conn.execute(f'ALTER TABLE {table} ADD COLUMN "{field_name}" {field_type}')
            print(f"  ✅ 添加字段: {field_name}")
        except sqlite3.OperationalError as e:
            if 'duplicate column' in str(e).lower():
                print(f"  ⚠️  字段已存在: {field_name}")
            else:
                raise
    
    # 2. 标准化疾病名称
    print("\n🩺 步骤2: 标准化疾病名称...")
    
    # 获取所有disease_general值
    df = pd.read_sql_query(
        f'SELECT rowid, disease_general FROM {table} WHERE disease_general IS NOT NULL AND disease_general != ""',
        conn
    )
    
    print(f"  处理 {len(df)} 条疾病记录...")
    
    updates = []
    for _, row in df.iterrows():
        rowid = row['rowid']
        original = row['disease_general']
        clean = normalize_disease_name(original)
        
        if clean:
            updates.append((clean, rowid))
        
        if len(updates) >= 1000:
            conn.executemany(f'UPDATE {table} SET disease_clean = ? WHERE rowid = ?', updates)
            conn.commit()
            updates = []
    
    if updates:
        conn.executemany(f'UPDATE {table} SET disease_clean = ? WHERE rowid = ?', updates)
        conn.commit()
    
    # 统计标准化后的疾病
    stats = pd.read_sql_query(
        f'SELECT disease_clean, COUNT(*) as cnt FROM {table} '
        f'WHERE disease_clean IS NOT NULL GROUP BY disease_clean ORDER BY cnt DESC LIMIT 20',
        conn
    )
    print(f"  ✅ 标准化完成，前10个疾病:")
    for _, row in stats.head(10).iterrows():
        print(f"     {row['disease_clean']}: {row['cnt']:,}")
    
    # 3. 标准化组织名称
    print("\n🫀 步骤3: 标准化组织名称...")
    
    df = pd.read_sql_query(
        f'SELECT rowid, tissue_location FROM {table} WHERE tissue_location IS NOT NULL AND tissue_location != ""',
        conn
    )
    
    print(f"  处理 {len(df)} 条组织记录...")
    
    updates = []
    for _, row in df.iterrows():
        rowid = row['rowid']
        original = row['tissue_location']
        clean = normalize_tissue_name(original)
        
        if clean:
            updates.append((clean, rowid))
        
        if len(updates) >= 1000:
            conn.executemany(f'UPDATE {table} SET tissue_clean = ? WHERE rowid = ?', updates)
            conn.commit()
            updates = []
    
    if updates:
        conn.executemany(f'UPDATE {table} SET tissue_clean = ? WHERE rowid = ?', updates)
        conn.commit()
    
    # 统计
    stats = pd.read_sql_query(
        f'SELECT tissue_clean, COUNT(*) as cnt FROM {table} '
        f'WHERE tissue_clean IS NOT NULL GROUP BY tissue_clean ORDER BY cnt DESC LIMIT 10',
        conn
    )
    print(f"  ✅ 标准化完成，前10个组织:")
    for _, row in stats.iterrows():
        print(f"     {row['tissue_clean']}: {row['cnt']:,}")
    
    # 4. 标准化平台名称
    print("\n🧬 步骤4: 标准化平台名称...")
    
    df = pd.read_sql_query(
        f'SELECT rowid, sequencing_platform FROM {table} WHERE sequencing_platform IS NOT NULL AND sequencing_platform != ""',
        conn
    )
    
    print(f"  处理 {len(df)} 条平台记录...")
    
    updates = []
    for _, row in df.iterrows():
        rowid = row['rowid']
        original = row['sequencing_platform']
        clean = normalize_platform_name(original)
        
        if clean:
            updates.append((clean, rowid))
        
        if len(updates) >= 1000:
            conn.executemany(f'UPDATE {table} SET platform_clean = ? WHERE rowid = ?', updates)
            conn.commit()
            updates = []
    
    if updates:
        conn.executemany(f'UPDATE {table} SET platform_clean = ? WHERE rowid = ?', updates)
        conn.commit()
    
    # 统计
    stats = pd.read_sql_query(
        f'SELECT platform_clean, COUNT(*) as cnt FROM {table} '
        f'WHERE platform_clean IS NOT NULL GROUP BY platform_clean ORDER BY cnt DESC LIMIT 10',
        conn
    )
    print(f"  ✅ 标准化完成，前10个平台:")
    for _, row in stats.iterrows():
        print(f"     {row['platform_clean']}: {row['cnt']:,}")
    
    # 5. 生成标准化报告
    print("\n📊 步骤5: 生成标准化报告...")
    
    report = {
        'total_records': conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0],
        'disease_clean_count': conn.execute(f'SELECT COUNT(*) FROM {table} WHERE disease_clean IS NOT NULL').fetchone()[0],
        'tissue_clean_count': conn.execute(f'SELECT COUNT(*) FROM {table} WHERE tissue_clean IS NOT NULL').fetchone()[0],
        'platform_clean_count': conn.execute(f'SELECT COUNT(*) FROM {table} WHERE platform_clean IS NOT NULL').fetchone()[0],
    }
    
    print(f"\n  标准化统计:")
    print(f"    总记录数: {report['total_records']:,}")
    print(f"    疾病标准化: {report['disease_clean_count']:,} ({report['disease_clean_count']/report['total_records']*100:.1f}%)")
    print(f"    组织标准化: {report['tissue_clean_count']:,} ({report['tissue_clean_count']/report['total_records']*100:.1f}%)")
    print(f"    平台标准化: {report['platform_clean_count']:,} ({report['platform_clean_count']/report['total_records']*100:.1f}%)")
    
    # 保存报告
    with open('data/standardization_report.json', 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    
    conn.close()
    
    print("\n" + "=" * 80)
    print("✅ 数据库标准化完成！")
    print("=" * 80)
    
    return report

if __name__ == '__main__':
    import pandas as pd
    standardize_database()
