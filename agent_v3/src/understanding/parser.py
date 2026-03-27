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
from typing import Optional

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

# ========== 生物学实体关键词 (高频) ==========

TISSUE_KEYWORDS: dict[str, list[str]] = {
    "brain": ["大脑", "脑", "brain", "cerebral", "cerebellum", "hippocampus", "cortex"],
    "liver": ["肝", "肝脏", "liver", "hepatic", "hepato"],
    "lung": ["肺", "肺部", "lung", "pulmonary"],
    "heart": ["心脏", "心", "heart", "cardiac", "myocardial"],
    "kidney": ["肾", "肾脏", "kidney", "renal"],
    "blood": ["血液", "外周血", "blood", "PBMC", "peripheral blood"],
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
    "melanoma": ["黑色素瘤", "melanoma"],
    "glioblastoma": ["胶质母细胞瘤", "glioblastoma", "GBM"],
    "atherosclerosis": ["动脉粥样硬化", "atherosclerosis"],
    "inflammatory bowel disease": ["炎症性肠病", "IBD", "Crohn", "ulcerative colitis"],
    "multiple sclerosis": ["多发性硬化", "multiple sclerosis", "MS"],
    "Parkinson's disease": ["帕金森", "parkinson"],
    "autism": ["自闭症", "autism", "ASD"],
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
    "T cell": ["T细胞", "t cell", "t-cell", "CD4", "CD8"],
    "B cell": ["B细胞", "b cell", "b-cell"],
    "macrophage": ["巨噬细胞", "macrophage"],
    "neutrophil": ["中性粒细胞", "neutrophil"],
    "fibroblast": ["成纤维细胞", "fibroblast"],
    "epithelial cell": ["上皮细胞", "epithelial"],
    "endothelial cell": ["内皮细胞", "endothelial"],
    "neuron": ["神经元", "neuron", "neuronal"],
    "astrocyte": ["星形胶质细胞", "astrocyte"],
    "hepatocyte": ["肝细胞", "hepatocyte"],
    "NK cell": ["NK细胞", "natural killer", "NK cell"],
    "dendritic cell": ["树突状细胞", "dendritic cell", "DC"],
    "monocyte": ["单核细胞", "monocyte"],
    "stem cell": ["干细胞", "stem cell"],
}

SOURCE_KEYWORDS: dict[str, list[str]] = {
    "cellxgene": ["cellxgene", "cxg", "CZI"],
    "geo": ["geo", "GEO", "gene expression omnibus"],
    "ncbi": ["ncbi", "sra", "SRA", "bioproject"],
    "ebi": ["ebi", "EBI", "arrayexpress", "EMBL"],
    "hca": ["hca", "human cell atlas"],
    "htan": ["htan", "human tumor atlas"],
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
        entities = self._extract_entities(query_lower)

        # Step 4: 检查是否是多轮细化
        if context and context.turns and self._is_refinement(query_lower):
            return self._build_refinement_query(query_lower, entities, context, lang)

        # Step 5: 构建结构化查询
        filters = self._entities_to_filters(entities)

        # Step 6: 聚合检测
        aggregation = self._detect_aggregation(query_lower, entities)

        # Step 7: 排序检测
        ordering = self._detect_ordering(query_lower)

        # Step 8: 目标级别
        target = self._detect_target_level(query_lower, entities, intent)

        # 计算置信度
        confidence = self._compute_confidence(intent, entities, ids)

        # 复杂度评估
        complexity = self._assess_complexity(intent, entities, aggregation)

        return ParsedQuery(
            intent=intent,
            complexity=complexity,
            entities=entities,
            filters=filters,
            target_level=target,
            aggregation=aggregation,
            ordering=ordering,
            limit=20,
            original_text=query,
            language=lang,
            confidence=confidence,
            parse_method="rule",
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
        """意图分类"""
        scores: dict[str, int] = {k: 0 for k in INTENT_KEYWORDS}

        for intent_name, keywords in INTENT_KEYWORDS.items():
            for kw in keywords:
                if kw in query_lower:
                    scores[intent_name] += 1

        best = max(scores, key=scores.get)
        if scores[best] > 0:
            return QueryIntent[best]

        return QueryIntent.SEARCH  # 默认

    def _extract_entities(self, query_lower: str) -> list[BioEntity]:
        """提取生物学实体"""
        entities: list[BioEntity] = []

        # Tissue
        for canonical, keywords in TISSUE_KEYWORDS.items():
            for kw in keywords:
                if kw.lower() in query_lower:
                    entities.append(BioEntity(
                        text=kw, entity_type="tissue", normalized_value=canonical,
                    ))
                    break  # 每个canonical只匹配一次

        # Disease
        for canonical, keywords in DISEASE_KEYWORDS.items():
            for kw in keywords:
                if kw.lower() in query_lower:
                    entities.append(BioEntity(
                        text=kw, entity_type="disease", normalized_value=canonical,
                    ))
                    break

        # Assay
        for canonical, keywords in ASSAY_KEYWORDS.items():
            for kw in keywords:
                if kw.lower() in query_lower:
                    entities.append(BioEntity(
                        text=kw, entity_type="assay", normalized_value=canonical,
                    ))
                    break

        # Cell type
        for canonical, keywords in CELL_TYPE_KEYWORDS.items():
            for kw in keywords:
                if kw.lower() in query_lower:
                    entities.append(BioEntity(
                        text=kw, entity_type="cell_type", normalized_value=canonical,
                    ))
                    break

        # Source database
        for canonical, keywords in SOURCE_KEYWORDS.items():
            for kw in keywords:
                if kw.lower() in query_lower:
                    entities.append(BioEntity(
                        text=kw, entity_type="source_database", normalized_value=canonical,
                    ))
                    break

        # Organism
        for canonical, keywords in ORGANISM_KEYWORDS.items():
            for kw in keywords:
                if kw.lower() in query_lower:
                    entities.append(BioEntity(
                        text=kw, entity_type="organism", normalized_value=canonical,
                    ))
                    break

        # 否定检测
        negation_patterns = ["非", "不是", "排除", "除了", "not ", "without ", "exclude "]
        for entity in entities:
            for neg in negation_patterns:
                idx = query_lower.find(entity.text.lower())
                if idx > 0 and query_lower[max(0, idx - 10):idx].strip().endswith(neg.strip()):
                    entity.negated = True

        # Sex
        sex_map = {"男": "male", "女": "female", "male": "male", "female": "female"}
        for kw, val in sex_map.items():
            if kw in query_lower:
                entities.append(BioEntity(
                    text=kw, entity_type="sex", normalized_value=val,
                ))
                break

        return entities

    def _entities_to_filters(self, entities: list[BioEntity]) -> QueryFilters:
        """实体列表 → 结构化过滤条件"""
        filters = QueryFilters()
        for e in entities:
            val = e.normalized_value or e.text
            if e.entity_type == "tissue" and not e.negated:
                filters.tissues.append(val)
            elif e.entity_type == "disease" and not e.negated:
                filters.diseases.append(val)
            elif e.entity_type == "cell_type":
                filters.cell_types.append(val)
            elif e.entity_type == "assay":
                filters.assays.append(val)
            elif e.entity_type == "source_database":
                filters.source_databases.append(val)
            elif e.entity_type == "organism" and not e.negated:
                filters.organisms.append(val)
            elif e.entity_type == "sex":
                filters.sex = val
        return filters

    def _detect_aggregation(self, query_lower: str, entities: list[BioEntity]) -> AggregationSpec | None:
        """检测聚合需求"""
        agg_keywords = ["统计", "分布", "多少", "数量", "计数",
                        "distribution", "count", "how many", "statistics", "breakdown"]
        if not any(kw in query_lower for kw in agg_keywords):
            return None

        # 确定GROUP BY字段
        group_hints = {
            "组织": "tissue", "tissue": "tissue", "器官": "tissue",
            "疾病": "disease", "disease": "disease",
            "数据库": "source_database", "来源": "source_database",
            "database": "source_database", "source": "source_database",
            "平台": "assay", "assay": "assay", "技术": "assay",
            "细胞类型": "cell_type", "cell type": "cell_type",
            "性别": "sex", "sex": "sex",
        }
        for kw, field in group_hints.items():
            if kw in query_lower:
                return AggregationSpec(group_by=[field], metric="count")

        # 默认按tissue分组
        return AggregationSpec(group_by=["source_database"], metric="count")

    def _detect_ordering(self, query_lower: str) -> OrderingSpec | None:
        """检测排序需求"""
        if any(kw in query_lower for kw in ["引用最多", "最高引用", "most cited", "top cited"]):
            return OrderingSpec(field="citation_count", direction="desc")
        if any(kw in query_lower for kw in ["最新", "最近", "latest", "newest", "recent"]):
            return OrderingSpec(field="published_at", direction="desc")
        if any(kw in query_lower for kw in ["细胞数最多", "most cells", "largest"]):
            return OrderingSpec(field="n_cells", direction="desc")
        return None

    def _detect_target_level(self, query_lower: str, entities: list, intent: QueryIntent) -> str:
        """确定目标层级"""
        if any(kw in query_lower for kw in ["项目", "project", "study", "研究"]):
            return "project"
        if any(kw in query_lower for kw in ["series"]):
            return "series"
        if any(kw in query_lower for kw in ["细胞类型", "cell type"]):
            return "celltype"
        # "数据集"/"dataset" 默认走sample级别视图 (包含最完整的元数据)
        return "sample"

    def _is_refinement(self, query_lower: str) -> bool:
        """判断是否是多轮细化"""
        patterns = ["这些", "其中", "上面", "刚才", "这里面",
                    "these", "those", "above", "from them", "of them",
                    "哪些是", "筛选", "过滤"]
        return any(p in query_lower for p in patterns)

    def _build_refinement_query(
        self, query_lower: str, entities: list[BioEntity],
        context: SessionContext, lang: str,
    ) -> ParsedQuery:
        """构建多轮细化查询"""
        # 基于上一轮的过滤条件，添加新条件
        prev_filters = context.active_filters or QueryFilters()
        new_filters = self._entities_to_filters(entities)

        # 合并
        merged = QueryFilters(
            organisms=prev_filters.organisms + new_filters.organisms,
            tissues=prev_filters.tissues or new_filters.tissues,
            diseases=prev_filters.diseases or new_filters.diseases,
            cell_types=prev_filters.cell_types + new_filters.cell_types,
            assays=prev_filters.assays + new_filters.assays,
            source_databases=prev_filters.source_databases + new_filters.source_databases,
            sex=new_filters.sex or prev_filters.sex,
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
            confidence=0.8,
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
            temperature=0.0,
            max_tokens=1024,
        )

        try:
            # 提取JSON
            text = response.content.strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            data = json.loads(text)

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
                aggregation = AggregationSpec(
                    group_by=agg_data.get("group_by", []),
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
