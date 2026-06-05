"""
Query Understanding Module

规则优先 + LLM兜底的双轨查询解析器。
- 规则引擎处理~70%常见查询 (ID查询、简单搜索、统计)
- LLM处理~30%复杂/歧义查询
"""

from __future__ import annotations

import json
import logging
import re

from ..core.models import (
    AggregationSpec,
    BioEntity,
    OrderingSpec,
    ParsedQuery,
    QueryComplexity,
    QueryFilters,
    QueryIntent,
    SessionContext,
)
from ..core.interfaces import ILLMClient

logger = logging.getLogger(__name__)


# ========== ID模式 ==========

ID_PATTERNS: dict[str, re.Pattern] = {
    "geo_project": re.compile(r"\b(GSE\d{4,8})\b", re.I),
    "geo_sample": re.compile(r"\b(GSM\d{4,8})\b", re.I),
    "sra_project": re.compile(r"\b(PRJNA\d{4,8})\b", re.I),
    "sra_study": re.compile(r"\b(SRP\d{4,8})\b", re.I),
    "sra_sample": re.compile(r"\b(SRS\d{4,8})\b", re.I),
    "biosample": re.compile(r"\b(SAM[NE]A?\d{6,12})\b", re.I),
    "pmid": re.compile(r"(?:PMID[:\s]*|pubmed[:\s]*)(\d{6,9})\b", re.I),
    "doi": re.compile(r"\b(10\.\d{4,}/[^\s,;]+)\b"),
}

# ========== 意图关键词 ==========

INTENT_KEYWORDS: dict[str, list[str]] = {
    "SEARCH": [
        "查找", "搜索", "找到", "有哪些", "哪些数据", "什么数据", "列出",
        "find", "search", "look for", "show me", "list", "get", "which",
        "what datasets", "what data",
    ],
    "COMPARE": [
        "比较", "对比", "差异", "区别", "不同", "versus",
        "compare", "difference", "vs", "between",
    ],
    "STATISTICS": [
        "统计", "多少", "数量", "分布", "占比", "总共", "计数", "百分比",
        "how many", "count", "distribution", "statistics", "total", "percentage",
        "per database", "per source", "number of", "breakdown",
        "projects per", "samples per", "datasets per",
        "by database", "by source",
        # Phase 20-A: "across all sources" alone is a search idiom ("find X
        # across all sources"), not necessarily an aggregation. Keep
        # "per X" / "by X" as the aggregation signal.
    ],
    "EXPLORE": [
        "所有", "全部", "所有的", "全部的",
        "探索", "浏览", "有什么", "概况", "概览", "看看",
        "explore", "browse", "overview", "what is available", "what do you have",
        "what datasets", "what data do", "available datasets", "available data",
    ],
    "DOWNLOAD": [
        "下载", "获取数据", "导出", "h5ad", "rds",
        "download", "get data", "export", "access data",
    ],
    "LINEAGE": [
        "来源", "出处", "来自", "血缘", "追溯", "关联数据库", "跨库",
        "source", "origin", "provenance", "which database", "cross-database",
        "linked", "related",
    ],
}

# ========== 超级最值 / 排名检测 (Phase 37) ==========
# Superlative ranking words. A superlative PAIRED WITH an explicit group
# dimension ("which TISSUE has the most data") signals a ranked aggregation;
# a superlative alone ("most recent datasets") does not (handled by the caller).
_SUP_DESC_RE = re.compile(
    r"\b(most|highest|largest|greatest|biggest|most[- ]abundant|most[- ]common|"
    r"most[- ]frequent|most[- ]numerous|top)\b", re.IGNORECASE)
_SUP_ASC_RE = re.compile(
    r"\b(least|lowest|smallest|fewest|rarest|less[- ]common)\b", re.IGNORECASE)
_SUP_DESC_ZH = ("最多", "最高", "最大", "最常见", "最丰富", "占比最高", "数量最")
_SUP_ASC_ZH = ("最少", "最低", "最小", "最罕见", "占比最低")


def _superlative_direction(query_lower: str) -> str | None:
    """Return 'desc' (most/highest), 'asc' (least/fewest), or None."""
    if any(z in query_lower for z in _SUP_DESC_ZH) or _SUP_DESC_RE.search(query_lower):
        return "desc"
    if any(z in query_lower for z in _SUP_ASC_ZH) or _SUP_ASC_RE.search(query_lower):
        return "asc"
    return None


# ========== 生物学实体关键词 (高频) ==========

TISSUE_KEYWORDS: dict[str, list[str]] = {
    # Phase 20-A: specific brain regions BEFORE the umbrella "brain"
    # so "hippocampus, cortex, cerebellum" extracts each as a distinct
    # entity (used by tissue LIKE for raw-column widening). The engine
    # will route these via LIKE since they're not in
    # _TISSUE_KEYWORD_TO_STANDARD as canonical values.
    "hippocampus": ["hippocampus", "hippocampal", "海马"],
    "cortex": ["cortex", "cortical", "prefrontal cortex", "皮层", "皮质"],
    "cerebellum": ["cerebellum", "cerebellar", "小脑"],
    "midbrain": ["midbrain", "中脑"],
    "brainstem": ["brainstem", "brain stem", "脑干"],
    "spinal cord": ["spinal cord", "spinal", "脊髓"],
    "brain": ["大脑", "脑", "brain", "cerebral"],
    # Phase 20-A: remove "hepato" prefix — it shadows "hepatocyte"
    # (cell type) when the parser claims its span first. Use "hepatic"
    # which is the proper adjective form.
    "liver": ["肝", "肝脏", "liver", "hepatic"],
    "lung": ["肺", "肺部", "lung", "pulmonary"],
    "heart": ["心脏", "心", "heart", "cardiac", "myocardial"],
    "kidney": ["肾", "肾脏", "kidney", "renal"],
    "blood": ["血液", "blood"],
    "PBMC": ["PBMC", "外周血单核", "外周血单个核",
             "peripheral blood mononuclear"],
    "peripheral blood": ["外周血", "peripheral blood"],
    "bone marrow": ["骨髓", "bone marrow"],
    "skin": ["皮肤", "skin", "dermis", "epidermis"],
    "intestine": ["肠", "肠道", "intestine", "gut", "colon", "bowel"],
    "pancreas": ["胰腺", "pancreas", "pancreatic"],
    "breast": ["乳腺", "breast", "mammary"],
    "eye": ["眼", "视网膜", "eye", "retina", "retinal"],
    "stomach": ["胃", "stomach", "gastric"],
    "prostate": ["前列腺", "prostate"],
    "ovary": ["卵巢", "ovary", "ovarian"],
    "testis": ["睾丸", "testis", "testes"],
    "thyroid": ["甲状腺", "thyroid"],
    "spleen": ["脾脏", "脾", "spleen"],
    "lymph node": ["淋巴结", "lymph node", "lymph"],
    "muscle": ["肌肉", "muscle", "skeletal muscle"],
    "placenta": ["胎盘", "placenta", "placental"],
    "adipose tissue": ["脂肪", "adipose", "fat tissue"],
    # Umbrella tissue categories — resolved via OntologyResolver.UMBRELLA_TERMS
    "gastrointestinal tract": ["gastrointestinal tract", "GI tract", "消化道"],
    "central nervous system": ["central nervous system", "CNS", "中枢神经"],
    "respiratory system": ["respiratory system", "呼吸系统"],
    "urinary system": ["urinary system", "泌尿系统"],
    "reproductive system": ["reproductive system", "生殖系统"],
    "musculoskeletal system": ["musculoskeletal system", "肌肉骨骼系统"],
    "cardiovascular system": ["cardiovascular system", "心血管系统"],
}

DISEASE_KEYWORDS: dict[str, list[str]] = {
    "normal": ["正常", "健康", "对照", "normal", "healthy", "control"],
    "cancer": ["癌", "肿瘤", "恶性", "cancer", "tumor", "carcinoma", "malignant", "neoplasm"],
    "Alzheimer's disease": ["阿尔茨海默", "老年痴呆", "alzheimer", "AD"],
    "COVID-19": ["新冠", "covid", "sars-cov-2", "coronavirus"],
    "diabetes": ["糖尿病", "diabetes", "diabetic"],
    "fibrosis": ["纤维化", "fibrosis", "fibrotic"],
    "hepatocellular carcinoma": ["肝癌", "肝细胞癌", "hepatocellular", "HCC"],
    "lung cancer": ["肺癌", "lung cancer", "NSCLC", "SCLC"],
    "breast cancer": ["乳腺癌", "breast cancer"],
    "colorectal cancer": ["结直肠癌", "colorectal", "colon cancer"],
    "leukemia": ["白血病", "leukemia", "AML", "CLL", "ALL"],
    "clonal hematopoiesis": ["克隆性造血", "clonal hematopoiesis", "clonal haematopoiesis"],
    "melanoma": ["黑色素瘤", "melanoma"],
    "glioblastoma": ["胶质母细胞瘤", "glioblastoma", "GBM"],
    "glioma": ["胶质瘤", "脑胶质瘤", "glioma"],
    "atherosclerosis": ["动脉粥样硬化", "atherosclerosis"],
    "inflammatory bowel disease": ["炎症性肠病", "IBD", "Crohn", "ulcerative colitis"],
    "multiple sclerosis": ["多发性硬化", "multiple sclerosis", "MS"],
    "Parkinson's disease": ["帕金森", "parkinson"],
    "autism": ["自闭症", "autism", "ASD"],
    # Umbrella / category diseases — expand via OntologyResolver.UMBRELLA_TERMS
    # Phase 38: keep stems generous so Chinese morphological variants all match
    # ("自身免疫" matches 自身免疫病 / 自身免疫性 / 自身免疫疾病 / 自身免疫性疾病).
    "autoimmune disease": ["autoimmune disease", "autoimmune disorder", "autoimmune",
                            "自身免疫", "自身免疫病", "自身免疫性"],
    "neurodegenerative disease": ["neurodegenerative disease", "neurodegenerative disorder",
                                    "neurodegeneration", "神经退行性"],
    "neurological disease": ["neurological disease", "neurological disorder",
                              "neurological", "神经系统疾病", "神经性疾病", "神经病"],
    "cardiovascular disease": ["cardiovascular disease", "cardiovascular disorder",
                                "cardiac disease", "心血管疾病"],
    "hematological disease": ["hematological", "haematological", "hematologic",
                               "blood cancer", "blood cancers", "blood malignancy",
                               "血液病", "血液系统疾病", "血液肿瘤", "血液恶性肿瘤"],
    "metabolic disease": ["metabolic disease", "metabolic disorder", "metabolic syndrome",
                           "metabolic and endocrine", "endocrine disease",
                           "endocrine disorder", "endocrine", "代谢疾病", "内分泌疾病"],
    "infectious disease": ["infectious disease", "infection disease", "感染性疾病"],
    "inflammatory disease": ["inflammatory disease", "inflammatory disorder",
                              "炎症性疾病"],
    "genetic disorder": ["genetic disorder", "hereditary disease", "inherited disease",
                          "遗传疾病"],
}

ASSAY_KEYWORDS: dict[str, list[str]] = {
    "10x 3' v3": ["10x", "10x chromium", "chromium", "10x 3'", "10x v3"],
    "Smart-seq2": ["smart-seq", "smartseq", "smart-seq2"],
    "Drop-seq": ["drop-seq", "dropseq"],
    "sci-RNA-seq": ["sci-rna", "sci-RNA-seq"],
    "CITE-seq": ["cite-seq", "citeseq"],
    "Visium": ["visium", "spatial"],
    "Slide-seq": ["slide-seq", "slideseq"],
}

CELL_TYPE_KEYWORDS: dict[str, list[str]] = {
    # Phase 20-A: specific T cell subtypes BEFORE the umbrella "T cell"
    # entry so a query like "CD8+ T cell exhaustion" matches the specific
    # subtype instead of being widened to all T cells.
    "CD8+ T cell": ["CD8+ T cell", "CD8 T cell", "CD8+ T cells",
                     "CD8 T cells", "cd8+ t cell", "cd8 t cell",
                     "cd8+ t cells", "cd8 t cells", "CD8+T",
                     "cytotoxic T cell", "killer T cell"],
    "CD4+ T cell": ["CD4+ T cell", "CD4 T cell", "CD4+ T cells",
                     "CD4 T cells", "cd4+ t cell", "cd4 t cell",
                     "cd4+ t cells", "cd4 t cells", "CD4+T",
                     "helper T cell"],
    "regulatory T cell": ["regulatory T cell", "Treg", "T regulatory",
                           "FOXP3+ T cell", "Treg cell"],
    "gamma-delta T cell": ["gamma-delta T cell", "γδ T cell",
                            "gd T cell", "gamma delta T"],
    "NKT cell": ["NKT cell", "NK-T cell", "natural killer T"],
    # Generic T cell as fallback umbrella
    "T cell": ["T细胞", "t cell", "t-cell", "T lymphocyte"],
    "B cell": ["B细胞", "b cell", "b-cell", "B lymphocyte"],
    "plasma cell": ["plasma cell", "plasma cells", "浆细胞"],
    "macrophage": ["巨噬细胞", "macrophage", "macrophages"],
    "microglia": ["microglia", "microglial", "小胶质细胞"],
    "neutrophil": ["中性粒细胞", "neutrophil"],
    "fibroblast": ["成纤维细胞", "fibroblast", "fibroblasts"],
    "epithelial cell": ["上皮细胞", "epithelial"],
    "endothelial cell": ["内皮细胞", "endothelial"],
    # Specific neuronal subtypes
    "GABAergic neuron": ["GABAergic", "GABA neuron", "inhibitory neuron"],
    "glutamatergic neuron": ["glutamatergic", "glutamate neuron",
                              "excitatory neuron"],
    "dopaminergic neuron": ["dopaminergic", "dopamine neuron",
                             "DA neuron"],
    "neuron": ["神经元", "neuron", "neuronal", "neurons"],
    "astrocyte": ["星形胶质细胞", "astrocyte", "astrocytes"],
    "oligodendrocyte": ["少突胶质细胞", "oligodendrocyte"],
    # Specific hepatic / pancreatic cells
    "hepatocyte": ["肝细胞", "hepatocyte", "hepatocytes"],
    "pancreatic islet": ["pancreatic islet", "islet cell", "islet cells",
                         "islets of langerhans", "胰岛", "胰岛细胞"],
    "pancreatic beta cell": ["pancreatic beta cell", "beta cell",
                              "β cell", "β-cell", "胰岛β细胞"],
    "pancreatic alpha cell": ["pancreatic alpha cell", "alpha cell",
                               "α cell", "α-cell"],
    "NK cell": ["NK细胞", "natural killer cell", "NK cell"],
    "dendritic cell": ["树突状细胞", "dendritic cell", "DC cell"],
    "monocyte": ["单核细胞", "monocyte", "monocytes"],
    "stem cell": ["干细胞", "stem cell", "stem cells"],
    "hematopoietic stem cell": ["hematopoietic stem cell", "HSC",
                                "造血干细胞"],
    "mesenchymal stem cell": ["mesenchymal stem cell", "MSC",
                              "间充质干细胞"],
    "cardiomyocyte": ["cardiomyocyte", "cardiomyocytes",
                       "心肌细胞", "cardiac myocyte"],
    "podocyte": ["podocyte", "podocytes", "足细胞"],
    # Umbrella cell-type categories — checked LAST so specific entries win
    "immune cell": ["immune cell", "immune cells", "免疫细胞"],
    "stromal cell": ["stromal cell", "stromal cells", "基质细胞"],
    "lymphocyte": ["lymphocyte", "lymphocytes", "淋巴细胞"],
}

SOURCE_KEYWORDS: dict[str, list[str]] = {
    "cellxgene": ["cellxgene", "cxg", "CZI"],
    "geo": ["geo", "GEO", "gene expression omnibus"],
    "ncbi": ["ncbi", "sra", "SRA", "bioproject"],
    "ebi": ["ebi", "EBI", "arrayexpress", "EMBL"],
    "ega": ["ega", "EGA"],
    "hca": ["hca", "human cell atlas"],
    "htan": ["htan", "human tumor atlas"],
    "psychad": ["psychad", "PsychAD"],
    "zenodo": ["zenodo"],
    "biscp": ["biscp", "BISCP"],
    "kpmp": ["kpmp", "KPMP"],
    "figshare": ["figshare"],
}

ORGANISM_KEYWORDS: dict[str, list[str]] = {
    "Homo sapiens": ["人源", "人类", "人的", "human", "homo sapiens", "patient", "patients"],
    "Mus musculus": ["小鼠", "鼠源", "mouse", "mice", "murine", "mus musculus"],
    "Rattus norvegicus": ["大鼠", "rat", "rattus"],
    "Danio rerio": ["斑马鱼", "zebrafish", "danio"],
    "Drosophila melanogaster": ["果蝇", "drosophila", "fly"],
    "Macaca fascicularis": ["猴", "猕猴", "macaque", "monkey", "primate"],
    "Sus scrofa": ["猪", "pig", "porcine"],
}


# ========== Categorical normalized fields (new in v2) ==========

SAMPLE_TYPE_KEYWORDS: dict[str, list[str]] = {
    "tumor": ["肿瘤样本", "tumor sample", "tumor samples", "tumour sample", "tumour samples"],
    "cell_line": ["细胞系", "cell line", "cell_line", "cell-line"],
    "primary_tissue": ["原发组织", "primary tissue", "primary_tissue",
                       "primary sample", "primary samples",
                       "primary donor", "primary donors"],
    "organoid": ["类器官", "organoid"],
    "fetal": ["胎儿样本", "fetal sample"],
    # Phase 19-G: iPSC keyword maps to BOTH iPSC_derived AND PSC_derived
    # since DB curation is inconsistent (some sources tag iPSC samples as
    # PSC_derived). Engine widens via sample_type list.
    "iPSC_derived": ["iPSC sample", "iPSC samples", "iPSC-derived",
                     "iPSC derived", "iPS cell", "iPS cells",
                     "induced pluripotent", "iPSC"],
    "PSC_derived": ["PSC-derived", "PSC derived", "pluripotent stem cell",
                    "pluripotent sample", "PSC sample", "PSC samples"],
    "xenograft": ["xenograft", "PDX", "patient-derived xenograft"],
}

DISEASE_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "neoplasm": ["neoplasm", "neoplasms", "neoplasia", "malignancy", "肿瘤类",
                  "肿瘤疾病"],
    "normal": ["normal sample", "normal samples", "healthy control", "health controls",
                "非疾病", "正常样本", "健康对照"],
    "infectious": ["infectious disease", "infection disease", "感染性疾病"],
    "inflammatory": ["inflammatory disease", "inflammation disease", "炎症性疾病"],
    "genetic": ["genetic disorder", "inherited disease", "遗传性疾病"],
    "autoimmune": ["autoimmune disease", "自身免疫性疾病"],
}

TISSUE_SYSTEM_KEYWORDS: dict[str, list[str]] = {
    "nervous": ["nervous system", "神经系统", "central nervous", "中枢神经"],
    "respiratory": ["respiratory system", "呼吸系统"],
    "cardiovascular": ["cardiovascular system", "心血管系统", "circulatory"],
    "digestive": ["digestive system", "消化系统", "gastrointestinal"],
    "endocrine": ["endocrine system", "内分泌系统"],
    "reproductive": ["reproductive system", "生殖系统"],
    "integumentary": ["integumentary system", "皮肤系统"],
    "blood_lymph": ["blood and lymph", "血液淋巴", "hematopoietic"],
    "immune": ["immune system", "免疫系统"],
    "musculoskeletal": ["musculoskeletal", "肌肉骨骼"],
    "urinary": ["urinary system", "泌尿系统"],
}


class QueryParser:
    """
    查询理解模块

    双轨策略:
    1. 规则引擎 (快速路径): ID查询、关键词匹配、模式化查询
    2. LLM解析器 (深度路径): 复杂语义、歧义消解
    """

    def __init__(self, llm: ILLMClient | None = None, schema_context: dict | None = None):
        self.llm = llm
        self.schema_context = schema_context or {}

    async def parse(
        self,
        query: str,
        context: SessionContext | None = None,
    ) -> ParsedQuery:
        """解析用户查询"""
        query = query.strip()
        if not query:
            return ParsedQuery(
                intent=QueryIntent.EXPLORE,
                original_text=query,
                confidence=0.0,
            )

        # ── Adversarial / injection-shape input ─────────────────────────────
        # Refuse patterns that look like SQL/shell payloads rather than
        # biological questions. The agent should produce an empty, non-crashing
        # response for these.
        lower = query.lower()
        dangerous = ["drop table", "delete from", "update ", "insert into",
                      "truncate ", "alter table", "create table",
                      "union all select", "union select", "; --", "'--",
                      "; 删除", "删除所有"]
        if any(d in lower for d in dangerous):
            return ParsedQuery(
                intent=QueryIntent.SEARCH,
                filters=QueryFilters(),  # no filters → no matches
                target_level="sample",
                original_text=query,
                language="en",
                confidence=0.0,
                parse_method="refused_adversarial",
                sub_intent="adversarial",
            )

        # 1. 检测语言
        lang = self._detect_language(query)

        # 2. 尝试规则解析
        result = self._rule_parse(query, lang, context)
        if result and result.confidence >= 0.7:
            return result

        # 3. 规则解析不够自信 → LLM解析
        if self.llm:
            try:
                llm_result = await self._llm_parse(query, lang, context)
                if llm_result:
                    return llm_result
            except Exception as e:
                logger.warning("LLM parse failed: %s, falling back to rule result", e)

        # 4. 返回规则解析结果 (即使置信度低)
        if result:
            return result

        # 5. 最后兜底：当作自由文本搜索
        return ParsedQuery(
            intent=QueryIntent.SEARCH,
            filters=QueryFilters(free_text=query),
            target_level="sample",
            original_text=query,
            language=lang,
            confidence=0.3,
            parse_method="fallback",
        )

    # ========== 规则引擎 ==========

    def _rule_parse(
        self, query: str, lang: str, context: SessionContext | None
    ) -> ParsedQuery | None:
        """规则引擎解析"""
        query_lower = query.lower()

        # Step 1: ID识别 (最高优先级)
        ids = self._extract_ids(query)
        if ids:
            return self._build_id_query(ids, query, lang)

        # Step 2: 意图分类
        intent = self._classify_intent(query_lower)

        # Step 3: 实体抽取
        entities = self._extract_entities(query_lower, query_text=query)

        # Step 4: 检查是否是多轮细化
        if context and context.turns and self._is_refinement(query_lower):
            return self._build_refinement_query(query_lower, entities, context, lang)

        # Step 5: 构建结构化查询
        filters = self._entities_to_filters(entities)
        # Step 5b: Temporal filter extraction (years, after/before/between)
        self._extract_temporal(query_lower, filters)
        # Step 5c: Numeric / threshold filters
        self._extract_threshold_filters(query_lower, filters)
        # Step 5d: Asset filters (h5ad / rds availability)
        self._extract_asset_filters(query_lower, filters)
        # Step 5e: Sex shorthand ("from female donors", "in male patients")
        self._extract_sex_shorthand(query_lower, filters)
        # Phase 19-G: Step 5f: treatment-present filter
        self._extract_treatment_filter(query_lower, filters)
        # Phase 19-G: Step 5g: "diseased" / non-normal shorthand
        self._extract_diseased_shorthand(query_lower, filters)

        # Step 6: 聚合检测
        aggregation = self._detect_aggregation(query_lower, entities)

        # Phase 37: a query that resolves to a GROUP BY is a STATISTICS query, not
        # a SEARCH. Superlative-ranking queries ("which tissue has the most data")
        # carry no explicit stat keyword, so _classify_intent leaves them SEARCH;
        # align the intent with the detected aggregation so the engine emits the
        # ranked GROUP BY instead of an empty entity search.
        if aggregation is not None and intent in (QueryIntent.SEARCH, QueryIntent.EXPLORE):
            intent = QueryIntent.STATISTICS

        # Step 7: 排序检测
        ordering = self._detect_ordering(query_lower)

        # Step 8: 目标级别
        target = self._detect_target_level(query_lower, entities, intent)

        # 计算置信度
        confidence = self._compute_confidence(intent, entities, ids)

        # 复杂度评估
        complexity = self._assess_complexity(intent, entities, aggregation)

        # Strict-mode detection — honour the literal request instead of
        # widening via disease_category / ontology expansion.
        import re as _re_strict
        strict = bool(_re_strict.search(
            r"\b(strictly|exactly|literally|specifically)\b",
            query_lower, _re_strict.IGNORECASE,
        )) or ("严格" in query_lower) or ("仅限" in query_lower)

        return ParsedQuery(
            intent=intent,
            complexity=complexity,
            entities=entities,
            filters=filters,
            target_level=target,
            aggregation=aggregation,
            ordering=ordering,
            limit=100,
            original_text=query,
            language=lang,
            confidence=confidence,
            parse_method="rule",
            strict_mode=strict,
        )

    def _extract_ids(self, query: str) -> dict[str, list[str]]:
        """提取各类ID"""
        found: dict[str, list[str]] = {}
        for id_type, pattern in ID_PATTERNS.items():
            matches = pattern.findall(query)
            if matches:
                found[id_type] = matches
        return found

    def _build_id_query(self, ids: dict, query: str, lang: str) -> ParsedQuery:
        """构建ID查询"""
        filters = QueryFilters()
        entities: list[BioEntity] = []

        for id_type, values in ids.items():
            if id_type in ("geo_project", "sra_project"):
                filters.project_ids.extend(values)
            elif id_type in ("geo_sample", "sra_sample", "biosample"):
                filters.sample_ids.extend(values)
            elif id_type == "pmid":
                filters.pmids.extend(values)
            elif id_type == "doi":
                filters.dois.extend(values)

            for v in values:
                entities.append(BioEntity(text=v, entity_type="id", normalized_value=v))

        # 如果有跨库/关联关键词，意图是LINEAGE
        q_lower = query.lower()
        intent = QueryIntent.SEARCH
        if any(kw in q_lower for kw in ["关联", "跨库", "linked", "related", "cross"]):
            intent = QueryIntent.LINEAGE

        return ParsedQuery(
            intent=intent,
            complexity=QueryComplexity.SIMPLE,
            entities=entities,
            filters=filters,
            target_level="project" if filters.project_ids else "sample",
            original_text=query,
            language=lang,
            confidence=0.95,
            parse_method="rule",
        )

    def _classify_intent(self, query_lower: str) -> QueryIntent:
        """意图分类 (STATISTICS/COMPARE 优先于 SEARCH)"""
        scores: dict[str, int] = {k: 0 for k in INTENT_KEYWORDS}

        for intent_name, keywords in INTENT_KEYWORDS.items():
            for kw in keywords:
                if kw in query_lower:
                    scores[intent_name] += 1

        # Priority: STATISTICS > COMPARE > SEARCH (when tied)
        # This prevents "compare tumor samples across databases" from being SEARCH
        priority_order = ["STATISTICS", "COMPARE", "DOWNLOAD", "LINEAGE", "EXPLORE", "SEARCH"]
        best_score = max(scores.values())
        if best_score > 0:
            for intent_name in priority_order:
                if scores.get(intent_name, 0) == best_score:
                    return QueryIntent[intent_name]

        return QueryIntent.SEARCH  # 默认

    def _extract_entities(self, query_lower: str, query_text: str = None) -> list[BioEntity]:
        """提取生物学实体"""
        if query_text is None:
            query_text = query_lower
        entities: list[BioEntity] = []
        # Track which substrings have already been claimed by a higher-precedence
        # entity type so we don't double-count (e.g. "tumor" → both sample_type
        # AND disease_category AND disease).
        claimed_spans: list[tuple[int, int]] = []

        def _span_claimed(start: int, end: int) -> bool:
            return any(not (end <= cs or start >= ce) for cs, ce in claimed_spans)

        # Phase 20-A: pre-claim phrases that should NOT be greedily eaten
        # by single-word tissue keywords. "brain region" carries no
        # specific tissue meaning (the user follows with actual regions).
        # "pancreatic islet" / "pancreatic beta cell" should resolve as
        # cell_type, not tissue=pancreas + the word "islet" lost.
        for phrase in ("brain region", "brain regions", "cortical region",
                       "subregion", "anatomical region"):
            idx = query_lower.find(phrase)
            if idx >= 0:
                claimed_spans.append((idx, idx + len(phrase)))

        # Phase 20-A: extract specific cell_type compound phrases BEFORE
        # tissue/disease have a chance to greedily claim sub-words. The
        # `also_emit` field optionally adds the same phrase as a tissue
        # entity too (for "pancreatic islet" which lives on BOTH columns
        # in curation — some samples have tissue='pancreatic islet',
        # others have cell_type='pancreatic islet').
        _early_celltype_phrases = [
            ("pancreatic islet", "pancreatic islet", True),
            ("pancreatic beta cell", "pancreatic beta cell", False),
            ("pancreatic alpha cell", "pancreatic alpha cell", False),
            ("islet of langerhans", "pancreatic islet", True),
            ("islets of langerhans", "pancreatic islet", True),
            ("CD8+ T cell", "CD8+ T cell", False),
            ("CD8 T cell", "CD8+ T cell", False),
            ("CD4+ T cell", "CD4+ T cell", False),
            ("CD4 T cell", "CD4+ T cell", False),
            ("regulatory T cell", "regulatory T cell", False),
        ]
        for phrase, canonical, _also_tissue in _early_celltype_phrases:
            for hit in (query_lower.find(phrase.lower()),):
                if hit >= 0 and not _span_claimed(hit, hit + len(phrase)):
                    entities.append(BioEntity(
                        text=phrase, entity_type="cell_type",
                        normalized_value=canonical,
                    ))
                    claimed_spans.append((hit, hit + len(phrase)))
                    break

        # Phase 38-D: compound DISEASE phrases whose words would otherwise be
        # split by the greedy tissue/disease single-word loops. "blood cancer" is
        # a hematological malignancy (leukaemia/lymphoma/myeloma) — NOT "cancer in
        # blood tissue"; without this it parsed as tissue=blood + disease=cancer
        # (neoplasm), wrongly constraining to blood tissue and the whole neoplasm
        # category. Claim the phrase as one hematological-disease span first.
        _early_disease_phrases = [
            ("blood cancers", "hematological disease"),
            ("blood cancer", "hematological disease"),
            ("blood malignancy", "hematological disease"),
            ("hematological malignancy", "hematological disease"),
            ("haematological malignancy", "hematological disease"),
            # Chinese: longest/most-specific first so they claim the whole span.
            ("血液系统恶性肿瘤", "hematological disease"),
            ("血液恶性肿瘤", "hematological disease"),
            ("血液系统肿瘤", "hematological disease"),
            ("血液肿瘤", "hematological disease"),
            ("血癌", "hematological disease"),
            # Phase 38 / convention C1: a NAMED specific cancer is a disease
            # entity, NOT "cancer in organ X" — claim "breast cancer" as one
            # disease span so "breast" isn't also pulled out as a tissue filter
            # (which wrongly narrowed breast-cancer 38,811 → breast-tissue 9,405,
            # dropping metastatic/peripheral samples). The engine maps these to
            # disease_standard LIKE, no tissue constraint.
            ("breast cancer", "breast cancer"),
            ("乳腺癌", "breast cancer"),
        ]
        for phrase, canonical in _early_disease_phrases:
            hit = query_lower.find(phrase.lower())
            if hit >= 0 and not _span_claimed(hit, hit + len(phrase)):
                entities.append(BioEntity(
                    text=phrase, entity_type="disease", normalized_value=canonical,
                ))
                claimed_spans.append((hit, hit + len(phrase)))
                break

        # Tissue (priority: highest, always resolved)
        for canonical, keywords in TISSUE_KEYWORDS.items():
            for kw in keywords:
                idx = query_lower.find(kw.lower())
                if idx >= 0 and not _span_claimed(idx, idx + len(kw)):
                    entities.append(BioEntity(
                        text=kw, entity_type="tissue", normalized_value=canonical,
                    ))
                    claimed_spans.append((idx, idx + len(kw)))
                    break

        # Sample type (claim "tumor samples" / "cell line" BEFORE disease keywords).
        # Skip when the match is a sub-phrase of a tissue + disease expression
        # (e.g. "brain tumor samples" means brain with a neoplasm, not a tumor
        # sample-type lookup).
        for canonical, keywords in SAMPLE_TYPE_KEYWORDS.items():
            for kw in keywords:
                idx = query_lower.find(kw.lower())
                if idx < 0 or _span_claimed(idx, idx + len(kw)):
                    continue
                # Heuristic: if a tissue was already extracted AND this is a
                # "tumor samples"/"tumour samples" phrase, treat it as neoplasm
                # instead (handled by disease_category below), not sample_type.
                has_tissue = any(e.entity_type == "tissue" for e in entities)
                if canonical == "tumor" and has_tissue:
                    continue
                entities.append(BioEntity(
                    text=kw, entity_type="sample_type", normalized_value=canonical,
                ))
                claimed_spans.append((idx, idx + len(kw)))
                break

        # Disease category (neoplasm, normal, ...) — also emit as a `disease`
        # entity so the OntologyResolver can expand umbrella terms (autoimmune
        # disease → multiple sclerosis, lupus, ...).
        for canonical, keywords in DISEASE_CATEGORY_KEYWORDS.items():
            for kw in keywords:
                idx = query_lower.find(kw.lower())
                if idx >= 0 and not _span_claimed(idx, idx + len(kw)):
                    entities.append(BioEntity(
                        text=kw, entity_type="disease_category", normalized_value=canonical,
                    ))
                    # Also emit as a `disease` entity if the keyword matches a
                    # known umbrella term (so OntologyResolver can expand).
                    UMBRELLA_DISEASE_TERMS = {
                        "autoimmune disease", "neurodegenerative disease",
                        "cardiovascular disease", "metabolic disease",
                        "infectious disease", "inflammatory disease",
                        "genetic disorder",
                    }
                    if kw.lower() in UMBRELLA_DISEASE_TERMS:
                        entities.append(BioEntity(
                            text=kw, entity_type="disease", normalized_value=kw.lower(),
                        ))
                    claimed_spans.append((idx, idx + len(kw)))
                    break

        # Disease (specific diseases — lowest precedence for tumor/cancer words
        # that already triggered sample_type / disease_category)
        for canonical, keywords in DISEASE_KEYWORDS.items():
            for kw in keywords:
                # Short all-uppercase acronyms (ALL, MS, AD, GBM, HCC, IBD, CML,
                # AML, CLL, MPN) must match the user's case exactly — otherwise
                # "all tissues" matches the ALL (leukemia) acronym.
                is_acronym = (len(kw) <= 4 and kw.isupper() and kw.isascii()
                              and kw.isalpha())
                if is_acronym:
                    import re as _re_acr
                    m = _re_acr.search(rf"\b{_re_acr.escape(kw)}\b", query_text)
                    if not m:
                        continue
                    idx = m.start()
                    end = m.end()
                else:
                    idx = query_lower.find(kw.lower())
                    end = idx + len(kw)
                if idx >= 0 and not _span_claimed(idx, end):
                    entities.append(BioEntity(
                        text=kw, entity_type="disease", normalized_value=canonical,
                    ))
                    claimed_spans.append((idx, end))
                    break

        # Assay
        for canonical, keywords in ASSAY_KEYWORDS.items():
            for kw in keywords:
                idx = query_lower.find(kw.lower())
                if idx >= 0 and not _span_claimed(idx, idx + len(kw)):
                    entities.append(BioEntity(
                        text=kw, entity_type="assay", normalized_value=canonical,
                    ))
                    claimed_spans.append((idx, idx + len(kw)))
                    break

        # Cell type
        for canonical, keywords in CELL_TYPE_KEYWORDS.items():
            for kw in keywords:
                idx = query_lower.find(kw.lower())
                if idx >= 0 and not _span_claimed(idx, idx + len(kw)):
                    entities.append(BioEntity(
                        text=kw, entity_type="cell_type", normalized_value=canonical,
                    ))
                    claimed_spans.append((idx, idx + len(kw)))
                    break

        # Source database
        # Phase 23-C: short keywords (≤4 chars) need word-boundary checks
        # so "regardless" doesn't match "ega" and "geometry" doesn't match
        # "geo". Long keywords ("cellxgene", "human cell atlas") use plain
        # substring search. Only treat ASCII letters/digits as part of the
        # same "word" — Chinese / CJK characters next to an English keyword
        # ("from GEO数据库") should still allow the match.
        def _is_word_boundary(text: str, start: int, end: int) -> bool:
            before = text[start - 1] if start > 0 else " "
            after = text[end] if end < len(text) else " "
            def _alnum_ascii(ch: str) -> bool:
                return ch.isascii() and ch.isalnum()
            return not (_alnum_ascii(before) or _alnum_ascii(after))
        for canonical, keywords in SOURCE_KEYWORDS.items():
            for kw in keywords:
                kw_l = kw.lower()
                idx = query_lower.find(kw_l)
                if idx < 0 or _span_claimed(idx, idx + len(kw)):
                    continue
                if len(kw_l) <= 4 and not _is_word_boundary(
                    query_lower, idx, idx + len(kw_l),
                ):
                    continue
                entities.append(BioEntity(
                    text=kw, entity_type="source_database", normalized_value=canonical,
                ))
                claimed_spans.append((idx, idx + len(kw)))
                break

        # Organism
        for canonical, keywords in ORGANISM_KEYWORDS.items():
            for kw in keywords:
                idx = query_lower.find(kw.lower())
                if idx >= 0 and not _span_claimed(idx, idx + len(kw)):
                    entities.append(BioEntity(
                        text=kw, entity_type="organism", normalized_value=canonical,
                    ))
                    claimed_spans.append((idx, idx + len(kw)))
                    break

        # Tissue system
        for canonical, keywords in TISSUE_SYSTEM_KEYWORDS.items():
            for kw in keywords:
                idx = query_lower.find(kw.lower())
                if idx >= 0 and not _span_claimed(idx, idx + len(kw)):
                    entities.append(BioEntity(
                        text=kw, entity_type="tissue_system", normalized_value=canonical,
                    ))
                    claimed_spans.append((idx, idx + len(kw)))
                    break

        # 否定检测 — word-boundary aware (so "no" doesn't match "now", and
        # "except" doesn't match "accept"). Scoping:
        #   - 的 / ， / 。 / . / , / ; close the negation clause in Chinese.
        #   - An entity of a DIFFERENT type between the negation cue and a
        #     candidate entity closes the scope (so "non-tumor liver" negates
        #     only tumor, not liver).
        #   - Coordinators (and/or) extend the scope across entities of the
        #     SAME type ("except brain and liver" negates both).
        import re as _re_neg
        negation_patterns_re = [
            _re_neg.compile(r"(非|不是|排除|除了|不包括|不含)"),
            # Note: `excluding?` would mean `exclud` + optional `ing` —
            # i.e. matches "exclud" not "exclude". Use an explicit
            # alternation instead. Phase 19-C: include bare "no" with a
            # required trailing space (avoids "now", "node"). Also include
            # "no longer", "free of".
            _re_neg.compile(
                r"\b(not|without|exclude|excludes|excluding|"
                r"except|non[- ]?|free\s+of)\b",
                _re_neg.IGNORECASE,
            ),
            _re_neg.compile(r"\bno\s+", _re_neg.IGNORECASE),
        ]
        hard_terminators = [
            _re_neg.compile(r"的"),
            _re_neg.compile(r"[,，;；。.]"),
        ]
        # Sort entities by position
        entity_positions = []
        for entity in entities:
            idx = query_lower.find(entity.text.lower())
            if idx >= 0:
                entity_positions.append((idx, entity))
        entity_positions.sort(key=lambda e: e[0])

        # Sentence-scope negation prefix. 30 chars was too narrow:
        # "...samples from human breast tissue, but exclude any datasets
        #  related to neoplasm..." — the cue ("exclude") is ~32 chars
        # before "neoplasm". A 70-char window catches it, while a hard
        # terminator (punctuation or 的) still ends the scope.
        for i, (entity_idx, entity) in enumerate(entity_positions):
            prefix = query_lower[max(0, entity_idx - 70):entity_idx]
            # Find the most recent negation cue in prefix
            last_neg_pos = -1
            for pat in negation_patterns_re:
                for m in pat.finditer(prefix):
                    last_neg_pos = max(last_neg_pos, m.end())
            if last_neg_pos < 0:
                continue
            scope_region = prefix[last_neg_pos:]
            # Hard terminator closes the scope
            if any(t.search(scope_region) for t in hard_terminators):
                continue
            # If a previous entity of a DIFFERENT type appears between the
            # negation cue and this entity, the scope closed at that entity.
            scope_closed = False
            neg_abs_pos = max(0, entity_idx - 30) + last_neg_pos
            for j in range(i):
                prev_idx, prev_ent = entity_positions[j]
                if prev_idx >= neg_abs_pos and prev_ent.entity_type != entity.entity_type:
                    scope_closed = True
                    break
            if scope_closed:
                continue
            entity.negated = True

        # Sex (ordered: female BEFORE male so "male" substring doesn't shadow
        # "female")
        sex_pairs = [
            ("女性", "female"), ("女", "female"),
            ("男性", "male"), ("男", "male"),
            ("female", "female"), ("male", "male"),
        ]
        for kw, val in sex_pairs:
            # Use word-boundary-ish check for English to avoid matching "male"
            # inside "female".
            kw_l = kw.lower()
            if kw_l in query_lower:
                if kw_l in ("male", "female"):
                    # Ensure this isn't a substring of another word (female → male)
                    idx = query_lower.find(kw_l)
                    before = query_lower[idx - 1] if idx > 0 else " "
                    after = query_lower[idx + len(kw_l)] if idx + len(kw_l) < len(query_lower) else " "
                    if before.isalpha() or after.isalpha():
                        continue
                entities.append(BioEntity(
                    text=kw, entity_type="sex", normalized_value=val,
                ))
                break

        # Phase 35 (F5): the keyword scanner can emit BOTH a generic disease
        # token ("carcinoma"/"cancer" → normalized "cancer") and the specific
        # disease the user actually named ("hepatocellular carcinoma"). Both are
        # same-type, so they OR together downstream and the broad `neoplasm`
        # umbrella swamps the specific leaf (e.g. HCC → 276k instead of 15k).
        # Drop the generic disease entity whenever a *more-specific* disease
        # entity subsumes its keyword as a whole word. A genuinely broad query
        # ("cancer in liver") keeps its single generic entity untouched.
        import re as _re
        disease_ents = [e for e in entities if e.entity_type == "disease"]
        if len(disease_ents) > 1:
            drop_ids: set[int] = set()
            for g in disease_ents:
                g_tok = (g.text or "").lower().strip()
                g_norm = (g.normalized_value or "").lower()
                if not g_tok:
                    continue
                for s in disease_ents:
                    if s is g:
                        continue
                    s_norm = (s.normalized_value or "").lower()
                    if (len(s_norm) > len(g_norm)
                            and _re.search(rf"\b{_re.escape(g_tok)}\b", s_norm)):
                        drop_ids.add(id(g))
                        break
            if drop_ids:
                entities = [e for e in entities if id(e) not in drop_ids]

        return entities

    def _extract_threshold_filters(self, query_lower: str, filters: QueryFilters) -> None:
        """Extract numeric thresholds for cell counts.

        Recognises:
          - "at least 10000 cells", "≥ 10k cells", "more than 5000"
          - "large cohort" / "large study" / "大队列" → min 1000
          - "with 10k+ cells", "10000+ cells"

        Routing rule: if the cell threshold is phrased in terms of a
        *dataset/study/series/cohort* (e.g. "datasets with 10k cells",
        "cohort of 5000 cells", "large study"), apply it to
        `series.cell_count` (dataset-level total). Otherwise apply to
        `n_cells` (per-sample). Single-cell users almost always mean
        the dataset-level interpretation.
        """
        import re as _re
        # Dataset-level phrasing markers in the query.
        dataset_scope = bool(_re.search(
            r"\b(datasets?|studies|study|series|cohorts?|library|libraries)\b",
            query_lower,
        )) or "数据集" in query_lower or "队列" in query_lower
        target = "series" if dataset_scope else "sample"

        if (target == "sample" and filters.min_cells is not None) or \
           (target == "series" and filters.min_series_cells is not None):
            return

        # Numeric patterns: digits, optional comma/space, optional k/K
        num_re = _re.compile(
            r"(?:at\s+least|>=|≥|more\s+than|>|over)\s*"
            r"([\d,]+)\s*([kK])?\s*(?:cells?|samples?|cohort)",
            _re.IGNORECASE,
        )
        plus_re = _re.compile(
            r"\b([\d,]+)\s*([kK])?\+\s*(?:cells?|samples?|cohort)",
            _re.IGNORECASE,
        )
        for m in (num_re.search(query_lower), plus_re.search(query_lower)):
            if m:
                raw = m.group(1).replace(",", "")
                try:
                    val = int(raw)
                    if (m.group(2) or "").lower() == "k":
                        val *= 1000
                    if target == "series":
                        filters.min_series_cells = val
                    else:
                        filters.min_cells = val
                    return
                except ValueError:
                    pass
        # Soft phrasing — "large cohort" usually means dataset-level
        if _re.search(r"\b(large\s+(?:cohort|study|dataset|series))\b",
                      query_lower) or "大队列" in query_lower:
            filters.min_series_cells = 1000

    def _extract_asset_filters(self, query_lower: str, filters: QueryFilters) -> None:
        """Detect h5ad asset availability."""
        import re as _re
        if filters.has_h5ad is None and (
            "h5ad" in query_lower
            or _re.search(r"\b(anndata|adata)\b", query_lower)
        ):
            filters.has_h5ad = True

    def _extract_sex_shorthand(self, query_lower: str, filters: QueryFilters) -> None:
        """Detect 'from female/male donors/patients' shorthand."""
        import re as _re
        if filters.sex:
            return
        if _re.search(r"\b(female)\b\s+(donor|patient|subject|individual|sample|participant)s?\b",
                      query_lower) or "女性" in query_lower:
            filters.sex = "female"
            return
        if _re.search(r"\b(male)\b\s+(donor|patient|subject|individual|sample|participant)s?\b",
                      query_lower) or "男性" in query_lower:
            # be careful not to match "female" → which already happened above
            filters.sex = "male"

    def _extract_treatment_filter(self, query_lower: str, filters: QueryFilters) -> None:
        """Phase 19-G: detect treatment-present filter.

        Triggers `treatment IS NOT NULL` predicate when the query mentions
        treatment-related concepts. Patterns:
          - "with treatment", "any treatment", "treatment annotation"
          - "treated samples", "drug-treated", "with drug"
          - "any kind of X treatment" (where X is cancer/disease)
          - "处理", "治疗", "处理样本", "药物处理"
        """
        import re as _re
        if filters.treatment_present is not None:
            return
        en_patterns = [
            r"\btreated\b",
            r"\bany\s+treatment\b",
            r"\bany\s+kind\s+of\s+\w+\s+treatment\b",
            r"\bwith\s+treatment\b",
            r"\btreatment\s+(annotation|present|info|information|metadata|status)\b",
            r"\bdrug[-\s]+treated\b",
            r"\bwith\s+drug\b",
            r"\bperturbed?\b",
            r"\bperturbation\b",
        ]
        zh_patterns = ["处理样本", "药物处理", "经过治疗",
                       "接受治疗", "药物处理"]
        if any(_re.search(p, query_lower, _re.IGNORECASE) for p in en_patterns):
            filters.treatment_present = True
            return
        if any(p in query_lower for p in zh_patterns):
            filters.treatment_present = True

    def _extract_diseased_shorthand(self, query_lower: str, filters: QueryFilters) -> None:
        """Phase 19-G: 'diseased X' / 'X with disease' / 'any disease' →
        require_disease=True AND exclude normal. Stricter than just excluding
        normal — also requires disease_category IS NOT NULL.
        """
        import re as _re
        if filters.require_disease is True:
            return
        diseased_patterns = [
            r"\bdiseased\b",
            r"\bwith\s+(any\s+)?\w+\s+disease\b",
            r"\bwith\s+\w+\s+disorder\b",
            r"\bnon[\s-]?normal\b",
            r"\bany\s+disease\b",
            r"\bnot\s+(normal|healthy|control)\b",
            r"\bnon[\s-]?healthy\b",
            r"\bnon[\s-]?control\b",
        ]
        zh_patterns = ["患病", "疾病样本", "非正常", "非健康"]
        if (any(_re.search(p, query_lower, _re.IGNORECASE) for p in diseased_patterns)
                or any(p in query_lower for p in zh_patterns)):
            filters.require_disease = True
            filters.exclude_disease_categories = list(
                dict.fromkeys((filters.exclude_disease_categories or []) + ["normal"])
            )

    def _extract_temporal(self, query_lower: str, filters: QueryFilters) -> None:
        """Extract year-based temporal filters from the query.

        Supports:
          - "after 2024" / "since 2024" / "2024 以后" → published_after=2024-01-01
          - "before 2022" / "2022 以前"              → published_before=2022-12-31
          - "from 2020 to 2022" / "between 2020 and 2022" → range
          - "2023 年/datasets"                        → exact year
          - "recent" / "latest" / "最新"              → last 2 years
        """
        import re as _re_t
        from datetime import datetime
        this_year = datetime.now().year
        # Match explicit 4-digit years 20xx within reasonable range (2005-current+1)
        # Digit-boundary (not \b): a Unicode word boundary fails between "4" and
        # a CJK suffix, so "\b20XX\b" missed Chinese "2024年". Require only that
        # the 4-digit year isn't embedded in a longer number.
        year_re = _re_t.compile(r"(?<![0-9])(20[0-2][0-9])(?![0-9])")
        years = [int(y) for y in year_re.findall(query_lower)]
        years = [y for y in years if 2005 <= y <= this_year + 1]

        if not years:
            # "recent" / "latest" / "most recent" / "最新"
            if _re_t.search(r"\b(recent|latest|most\s+recent)\b", query_lower) or "最新" in query_lower:
                filters.published_after = f"{this_year - 2}-01-01"
            return

        # Phase 19-G: "(2024+)" / "2024+" / "2024 onwards" shorthand
        plus_match = _re_t.search(r"\b(20\d{2})\s*\+", query_lower)
        if plus_match:
            year = int(plus_match.group(1))
            filters.published_after = f"{year}-01-01"
            return
        if _re_t.search(r"\b(onwards?|forward|or\s+later)\b", query_lower) and years:
            filters.published_after = f"{min(years)}-01-01"
            return

        if _re_t.search(r"\b(between|from)\b.*\b(to|and|-)\b", query_lower) and len(years) >= 2:
            lo, hi = min(years), max(years)
            filters.published_after = f"{lo}-01-01"
            filters.published_before = f"{hi}-12-31"
            return
        if _re_t.search(r"\b(after|since|>=?|past)\b", query_lower) or "以后" in query_lower or "之后" in query_lower:
            filters.published_after = f"{min(years)}-01-01"
            return
        if _re_t.search(r"\b(before|until|<=?)\b", query_lower) or "以前" in query_lower or "之前" in query_lower:
            # Phase 23-C: "before 2018" / "<2018" means strictly before
            # 2018-01-01. The old "≤ 2018-12-31" cutoff over-included the
            # whole 2018 year. Use strict-less-than via Dec-31 of the
            # preceding year (kept as exclusive upper bound).
            yr = max(years)
            filters.published_before = f"{yr - 1}-12-31"
            return
        # Default: "from YEAR" or "YEAR datasets" → that specific year
        y = years[0]
        filters.published_after = f"{y}-01-01"
        filters.published_before = f"{y}-12-31"

    def _entities_to_filters(self, entities: list[BioEntity]) -> QueryFilters:
        """实体列表 → 结构化过滤条件 (含排除条件)"""
        filters = QueryFilters()
        for e in entities:
            val = e.normalized_value or e.text
            if e.entity_type == "tissue":
                if e.negated:
                    filters.exclude_tissues.append(val)
                else:
                    filters.tissues.append(val)
            elif e.entity_type == "disease":
                if e.negated:
                    filters.exclude_diseases.append(val)
                else:
                    filters.diseases.append(val)
            elif e.entity_type == "cell_type":
                if e.negated:
                    filters.exclude_cell_types.append(val)
                else:
                    filters.cell_types.append(val)
            elif e.entity_type == "assay":
                if e.negated:
                    filters.exclude_assays.append(val)
                else:
                    filters.assays.append(val)
            elif e.entity_type == "source_database":
                if e.negated:
                    filters.exclude_source_databases.append(val)
                else:
                    filters.source_databases.append(val)
            elif e.entity_type == "organism":
                if e.negated:
                    filters.exclude_organisms.append(val)
                else:
                    filters.organisms.append(val)
            elif e.entity_type == "sex":
                filters.sex = val
            elif e.entity_type == "sample_type":
                if e.negated:
                    filters.exclude_sample_types.append(val)
                else:
                    filters.sample_types.append(val)
            elif e.entity_type == "disease_category":
                if e.negated:
                    filters.exclude_disease_categories.append(val)
                else:
                    filters.disease_categories.append(val)
            elif e.entity_type == "tissue_system":
                filters.tissue_systems.append(val)
        return filters

    def _detect_aggregation(self, query_lower: str, entities: list[BioEntity]) -> AggregationSpec | None:
        """检测聚合需求"""
        # Phase 20-A: removed bare "across" — too generic; it matches
        # search idioms like "samples across all sources". Keep bound
        # forms ("across databases") + count/distribution/per-X markers.
        agg_keywords = ["统计", "分布", "多少", "数量", "计数",
                        "distribution", "count", "how many", "statistics",
                        "breakdown",
                        "across databases", "across sources",
                        "per ", "by source", "by database", "by tissue",
                        "by disease"]
        has_explicit_agg = any(kw in query_lower for kw in agg_keywords)

        # 确定GROUP BY字段 (longest-match first so 'disease_category'
        # beats 'disease', 'tissue_system' beats 'tissue' etc.)
        group_hints = {
            "disease_category": "disease_category",
            "disease category": "disease_category",
            "疾病类别": "disease_category", "疾病种类": "disease_category",
            "tissue_system": "tissue_system",
            "tissue system": "tissue_system",
            "组织系统": "tissue_system",
            "sample_type": "sample_type",
            "sample type": "sample_type",
            "样本类型": "sample_type",
            "organism": "organism_common", "物种": "organism_common",
            "组织": "tissue_standard", "器官": "tissue_standard",
            "tissue": "tissue_standard",
            # Group by the cleaned column (721 curated values) rather than raw
            # `disease` (5.3K messy values incl. bare EFO ontology IDs), so the
            # buckets are human-readable and consistent with the tissue dim.
            "疾病": "disease_standard", "disease": "disease_standard",
            "数据库": "source_database", "来源": "source_database",
            "database": "source_database", "source": "source_database",
            "platform": "assay", "平台": "assay", "assay": "assay", "技术": "assay",
            "细胞类型": "cell_type", "cell type": "cell_type",
            "性别": "sex_normalized", "sex": "sex_normalized",
        }
        matched_field = None
        for kw, field in group_hints.items():
            if kw in query_lower:
                matched_field = field
                break

        # Phase 37: superlative / ranking queries — "which disease category has
        # the most data", "哪种疾病类别的数据最多", "which sample type is most
        # abundant". These name a dimension + a superlative but carry NONE of the
        # explicit agg keywords above, so they previously fell through to SEARCH
        # and returned 0. A superlative ALONE (e.g. "most recent datasets") must
        # NOT aggregate — only a superlative *paired with an explicit dimension*.
        if _superlative_direction(query_lower) and matched_field:
            return AggregationSpec(group_by=[matched_field], metric="count")

        if not has_explicit_agg:
            return None

        if matched_field:
            return AggregationSpec(group_by=[matched_field], metric="count")

        # 默认按 source_database 分组
        return AggregationSpec(group_by=["source_database"], metric="count")

    def _detect_ordering(self, query_lower: str) -> OrderingSpec | None:
        """检测排序需求"""
        if any(kw in query_lower for kw in ["引用最多", "最高引用", "most cited", "top cited"]):
            return OrderingSpec(field="citation_count", direction="desc")
        # "latest/recent/最新" is handled via temporal filter (published_after)
        # — no direct ORDER BY because publication_date isn't on the sample view.
        if any(kw in query_lower for kw in ["细胞数最多", "most cells", "largest"]):
            return OrderingSpec(field="n_cells", direction="desc")
        return None

    def _detect_target_level(self, query_lower: str, entities: list, intent: QueryIntent) -> str:
        """确定目标层级。

        Heuristics:
        * Sample-level (default) — anything that mentions samples /
          datasets / 数据集 explicitly, *or* any query that doesn't
          name a higher-level object (the implicit object is samples
          for retrieval).
        * Project-level — only when the *primary* object of the verb
          is project / study, not when "study" / "研究" appears as a
          modifier ("samples FROM cancer studies" should stay
          sample-level).
        * Series-level — explicit mention of "series".
        * Celltype-level — explicit "cell type"/"细胞类型".
        """
        import re as _re_t

        # If the query explicitly mentions samples/datasets, force sample level
        # — this overrides spurious "study/project" mentions.
        if _re_t.search(r"\b(samples?|datasets?|records?|rows?)\b", query_lower):
            return "sample"
        if "样本" in query_lower or "数据集" in query_lower:
            return "sample"

        # Cell type — explicit mention only.
        if _re_t.search(r"\bcell\s*types?\b", query_lower) or "细胞类型" in query_lower:
            return "celltype"

        # Series — explicit only.
        if _re_t.search(r"\b(series)\b", query_lower):
            return "series"

        # Project / study — must be the primary object.
        # Patterns like "show me/list/find/retrieve [the] N projects ..."
        proj_re = _re_t.compile(
            r"\b(?:show|list|find|return|retrieve|count|get)\s+(?:me\s+)?"
            r"(?:all\s+|the\s+|some\s+)?"
            r"(?:[\w\-]+\s+){0,5}"
            r"(projects?|studies|study)\b",
            _re_t.IGNORECASE,
        )
        if proj_re.search(query_lower) or "项目" in query_lower or "研究项目" in query_lower:
            return "project"

        return "sample"

    def _is_refinement(self, query_lower: str) -> bool:
        """判断是否是多轮细化"""
        patterns = [
            # Chinese demonstratives
            "这些", "其中", "上面", "刚才", "这里面", "哪些是", "筛选", "过滤", "里面",
            "只要", "仅仅", "仅保留", "只看", "只从", "只有", "仅从", "只要", "其中的",
            "给我", "哪些有", "添加", "缩小到",
            # English demonstratives
            "these", "those", "above", "from them", "of them",
            "the ones", "show me the", "which of",
            # Refinement connectives
            "narrow to", "narrow it to", "narrow down to", "narrow by",
            "filter by", "filter to", "filter it",
            "just the", "just ones", "just those",
            # "now ..." / "and now ..." → typically refinement
            "now ", "and now", "but only", "but just",
            "ones with", "ones that", "ones from", "ones in",
        ]
        if any(p in query_lower for p in patterns):
            return True
        # "only" patterns — strong refinement signal.  Match "only" as a word
        # (start, preceded by space, or followed by space), paired with another
        # token (avoiding standalone "only" fragments which are rare as full
        # queries anyway).
        import re as _re_r
        if _re_r.search(r"\bonly\b", query_lower):
            return True
        return False

    def _build_refinement_query(
        self, query_lower: str, entities: list[BioEntity],
        context: SessionContext, lang: str,
    ) -> ParsedQuery:
        """构建多轮细化查询 — merges previous-turn filters with the new turn.

        Field-level merge intent (Phase 14, fixes Bug 2 / 4 / 5):
        - "instead / now / 改为 / 换成 / 替换为" → REPLACE: same-type new values
          replace old values entirely.
        - "and also / 还要 / 还有 / 还需要 / 添加" → ADD: concatenate (dedup).
        - default refinement: if new has values for a field, REPLACE; otherwise KEEP.
          This matches typical user intent where an unmentioned dimension is
          assumed to be carried over but a re-mentioned dimension is the new
          target. (Old behaviour was to always concatenate, which retained
          stale tissue/disease values across turns.)
        """
        prev_filters = context.active_filters or QueryFilters()
        new_filters = self._entities_to_filters(entities)

        import re as _re_r
        # Detect explicit replace intent (overrides default)
        REPLACE_RE = _re_r.compile(
            r"\b(instead|rather|replace|switch|change|now)\b|改为|换成|替换为|改成|不要.*要")
        ADD_RE = _re_r.compile(
            r"\b(also|additionally|plus|and add|and also)\b|还要|还有|还需要|添加|另外")
        force_replace = bool(REPLACE_RE.search(query_lower))
        force_add = bool(ADD_RE.search(query_lower))

        def _merge_field(prev: list[str], new: list[str]) -> list[str]:
            if force_add:
                seen: dict[str, None] = {}
                for x in list(prev) + list(new):
                    seen.setdefault(x, None)
                return list(seen)
            if force_replace:
                return list(new) if new else list(prev)
            # Default: replace when user supplied new values for this field
            if new:
                return list(new)
            return list(prev)

        # Temporal — Bug 5 fix: previously dropped entirely
        published_after = (
            new_filters.published_after if new_filters.published_after
            else prev_filters.published_after
        )
        published_before = (
            new_filters.published_before if new_filters.published_before
            else prev_filters.published_before
        )

        # Numeric — Bug 4 fix: explicit None check so min_cells=0 is preserved
        def _num_merge(new_val, prev_val):
            return new_val if new_val is not None else prev_val

        merged = QueryFilters(
            organisms=_merge_field(prev_filters.organisms, new_filters.organisms),
            tissues=_merge_field(prev_filters.tissues, new_filters.tissues),
            diseases=_merge_field(prev_filters.diseases, new_filters.diseases),
            cell_types=_merge_field(prev_filters.cell_types, new_filters.cell_types),
            assays=_merge_field(prev_filters.assays, new_filters.assays),
            source_databases=_merge_field(prev_filters.source_databases, new_filters.source_databases),
            sample_types=_merge_field(prev_filters.sample_types, new_filters.sample_types),
            disease_categories=_merge_field(prev_filters.disease_categories, new_filters.disease_categories),
            tissue_systems=_merge_field(prev_filters.tissue_systems, new_filters.tissue_systems),
            sex=new_filters.sex if new_filters.sex else prev_filters.sex,
            # Exclusions are always additive — once a user says "exclude X" we
            # keep excluding X across turns unless they explicitly say to undo.
            exclude_tissues=list({*prev_filters.exclude_tissues, *new_filters.exclude_tissues}),
            exclude_diseases=list({*prev_filters.exclude_diseases, *new_filters.exclude_diseases}),
            exclude_organisms=list({*prev_filters.exclude_organisms, *new_filters.exclude_organisms}),
            exclude_source_databases=list({*prev_filters.exclude_source_databases, *new_filters.exclude_source_databases}),
            exclude_sample_types=list({*prev_filters.exclude_sample_types, *new_filters.exclude_sample_types}),
            exclude_disease_categories=list({*prev_filters.exclude_disease_categories, *new_filters.exclude_disease_categories}),
            project_ids=prev_filters.project_ids,
            sample_ids=prev_filters.sample_ids,
            pmids=prev_filters.pmids,
            dois=prev_filters.dois,
            min_cells=_num_merge(new_filters.min_cells, prev_filters.min_cells),
            min_citation_count=_num_merge(new_filters.min_citation_count, prev_filters.min_citation_count),
            has_h5ad=(new_filters.has_h5ad if new_filters.has_h5ad is not None else prev_filters.has_h5ad),
            published_after=published_after,
            published_before=published_before,
        )

        return ParsedQuery(
            intent=QueryIntent.SEARCH,
            sub_intent="refinement",
            complexity=QueryComplexity.MODERATE,
            entities=entities,
            filters=merged,
            target_level="sample",
            original_text=query_lower,
            language=lang,
            confidence=0.85,
            parse_method="rule",
        )

    def _compute_confidence(self, intent: QueryIntent, entities: list, ids: dict) -> float:
        """计算解析置信度"""
        if ids:
            return 0.95
        score = 0.5
        if entities:
            score += min(len(entities) * 0.15, 0.35)
        if intent != QueryIntent.SEARCH:  # 非默认意图 = 有明确匹配
            score += 0.1
        return min(score, 0.95)

    def _assess_complexity(
        self, intent: QueryIntent, entities: list, agg: AggregationSpec | None,
    ) -> QueryComplexity:
        """评估查询复杂度"""
        if intent == QueryIntent.COMPARE:
            return QueryComplexity.COMPLEX
        if agg and len(entities) > 2:
            return QueryComplexity.COMPLEX
        if len(entities) > 3:
            return QueryComplexity.MODERATE
        return QueryComplexity.SIMPLE

    def _detect_language(self, text: str) -> str:
        """检测语言"""
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        return "zh" if chinese_chars > len(text) * 0.1 else "en"

    # ========== LLM解析器 ==========

    async def _llm_parse(
        self, query: str, lang: str, context: SessionContext | None,
    ) -> ParsedQuery | None:
        """LLM深度解析"""
        if not self.llm:
            return None

        top_tissues = ", ".join(list(TISSUE_KEYWORDS.keys())[:15])
        top_diseases = ", ".join(list(DISEASE_KEYWORDS.keys())[:15])

        prompt = f"""Parse this single-cell RNA-seq metadata query into structured JSON.

Database fields: organism, tissue, disease, cell_type, assay, sex, source_database, n_cells, pmid, doi, citation_count
Top tissues: {top_tissues}
Top diseases: {top_diseases}
Sources: cellxgene, geo, ncbi, ebi, hca, htan

Output JSON:
{{"intent": "SEARCH|COMPARE|STATISTICS|EXPLORE|DOWNLOAD|LINEAGE",
  "target_level": "project|series|sample|celltype",
  "entities": [{{"text": "...", "type": "tissue|disease|cell_type|assay|organism", "value": "..."}}],
  "filters": {{"tissues": [], "diseases": [], "cell_types": [], "assays": [], "source_databases": [], "sex": null}},
  "aggregation": null | {{"group_by": ["field"], "metric": "count"}},
  "confidence": 0.0-1.0}}

Rules:
- Translate Chinese terms to English standard values
- Default organism: "Homo sapiens"
- "正常"/"健康" → disease: "normal"

Query: {query}

Return ONLY valid JSON, no explanation."""

        response = await self.llm.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=1.0,
            max_tokens=1024,
        )

        try:
            # 提取JSON — robust extraction (Phase 25):
            # Try in order: (1) entire stripped text, (2) inside ```...```
            # block, (3) substring between the first '{' and the matching
            # last '}'. This handles Kimi responses that wrap the JSON in
            # prose or use mixed-style code fences.
            text = response.content.strip()
            data = None
            for attempt in range(3):
                try:
                    if attempt == 0:
                        candidate = text
                    elif attempt == 1 and "```" in text:
                        chunk = text.split("```")[1]
                        if chunk.startswith("json"):
                            chunk = chunk[4:]
                        candidate = chunk.strip()
                    elif "{" in text and "}" in text:
                        first = text.find("{")
                        last = text.rfind("}")
                        candidate = text[first:last + 1]
                    else:
                        continue
                    data = json.loads(candidate)
                    break
                except (json.JSONDecodeError, IndexError):
                    continue
            if data is None:
                raise json.JSONDecodeError("no parseable JSON in response", text, 0)

            entities = [
                BioEntity(
                    text=e.get("text", ""),
                    entity_type=e.get("type", ""),
                    normalized_value=e.get("value"),
                )
                for e in data.get("entities", [])
            ]

            f = data.get("filters", {})
            filters = QueryFilters(
                tissues=f.get("tissues", []),
                diseases=f.get("diseases", []),
                cell_types=f.get("cell_types", []),
                assays=f.get("assays", []),
                source_databases=f.get("source_databases", []),
                sex=f.get("sex"),
            )

            agg_data = data.get("aggregation")
            aggregation = None
            if agg_data:
                # Standardize the grouping dimension so LLM-chosen raw columns
                # (e.g. "disease", "tissue") collapse onto the curated *_standard
                # columns, matching the rule path in _detect_aggregation.
                _std = {"disease": "disease_standard", "tissue": "tissue_standard"}
                gb = [_std.get(f, f) for f in agg_data.get("group_by", [])]
                aggregation = AggregationSpec(
                    group_by=gb,
                    metric=agg_data.get("metric", "count"),
                )

            return ParsedQuery(
                intent=QueryIntent[data.get("intent", "SEARCH")],
                complexity=QueryComplexity.MODERATE,
                entities=entities,
                filters=filters,
                target_level=data.get("target_level", "sample"),
                aggregation=aggregation,
                original_text=query,
                language=lang,
                confidence=data.get("confidence", 0.8),
                parse_method="llm",
            )

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning("Failed to parse LLM response: %s", e)
            return None
