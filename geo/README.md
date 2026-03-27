# GEO 元数据采集

## 数据来源
NCBI Gene Expression Omnibus（https://www.ncbi.nlm.nih.gov/geo/）

## 目录结构
```
geo/
├── merged_samples_with_citation.xlsx   # 原始 Excel（80 MB）
└── merged_samples_with_citation.csv    # 转换后 CSV（ETL 时自动生成）
```

## 数据规模
- 378,773 行（样本级记录）
- 5,666 个唯一 Series (GSE)
- 342,368 个唯一 Sample (GSM)
- 35 个字段

## 关键字段
- `Series_id` (GSE*), `Sample_id` (GSM*)
- `Characteristics` — **Python dict 字面量字符串**（需用 `ast.literal_eval()` 解析）
- `Series_PubMed_ID` — **浮点数**（如 28953884.0），需转 int→str
- `Series_SRA_Link` — 仅 0.5% 有值，不可靠
- `Source_name` — 常包含组织信息，可作为 tissue 的兜底

## Characteristics 解析
GEO 的 Characteristics 是自由文本，key 名称不统一。ETL 中使用映射字典匹配：
- tissue: 'tissue', 'organ', 'body site' 等 16 个候选 key
- disease: 'disease', 'diagnosis', 'condition' 等 14 个候选 key
- sex: 'sex', 'gender'
- age: 'age', 'donor_age', 'patient age' 等 11 个候选 key

## 在统一数据库中的映射
- Series → `unified_projects` + `unified_series` (geo_series)
- Sample → `unified_samples` (sample_id_type='gsm')
