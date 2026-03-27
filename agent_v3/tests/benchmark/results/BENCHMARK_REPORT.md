# SCeQTL-Agent V2 — Benchmark Evaluation Report

Generated: 2026-03-10 11:42
Total evaluation time: 1213.0s

## Executive Summary

| Metric | Value |
|--------|-------|
| Total Questions | 154 |
| **Pass Rate** | **92.2%** (142/154) |
| Failed | 11 |
| Errors | 1 |
| Avg Response Time | 7917ms |
| P95 Response Time | 39420ms |
| Rule Resolution Rate | 68.6% |
| Chinese Query Pass Rate | 100.0% |
| English Query Pass Rate | 98.4% |

## Evaluation Dimensions

### Dimension 1: Query Accuracy

| Metric | Value |
|--------|-------|
| Count Accuracy (results >= expected) | 99.4% |
| Intent Recognition Accuracy | 96.8% |
| Zero-Result Rate | 0.6% |

### Dimension 2: Cross-DB Fusion Quality

| Metric | Value |
|--------|-------|
| Multi-Source Coverage | 13.7% |
| Avg Sources per Query | 1.61 |
| Avg Dedup Rate | 2.8% |

### Dimension 3: User Experience

| Metric | Value |
|--------|-------|
| Avg Response Time | 7917ms |
| P95 Response Time | 39420ms |
| Suggestion Generation Rate | 18.8% |

### Dimension 4: Cost Efficiency

| Method | Rate |
|--------|------|
| Rule-based | 68.6% |
| Template-based | 16.3% |
| LLM-based | 0.0% |
| Error Rate | 0.6% |

## Per-Category Results

| Category | Total | Passed | Failed | Errors | Pass Rate | Avg Time | P95 Time | Rule % |
|----------|-------|--------|--------|--------|-----------|----------|----------|--------|
| simple_search | 30 | 30 | 0 | 0 | 100% | 2699ms | 7216ms | 97% |
| ontology_expansion | 25 | 19 | 6 | 0 | 76% | 3474ms | 9859ms | 88% |
| cross_db_fusion | 25 | 25 | 0 | 0 | 100% | 1991ms | 3130ms | 52% |
| complex_multi_table | 25 | 25 | 0 | 0 | 100% | 3634ms | 9871ms | 56% |
| statistics | 25 | 20 | 5 | 0 | 80% | 29985ms | 87209ms | 32% |
| multi_turn | 19 | 19 | 0 | 0 | 100% | 7815ms | 34328ms | 79% |
| edge_cases | 5 | 4 | 0 | 1 | 80% | 1168ms | 1623ms | 100% |

### simple_search

- **Questions**: 30
- **Pass rate**: 30/30
- **Count accuracy**: 100.0%
- **Intent accuracy**: 100.0%
- **Ontology trigger rate**: 86.7%
- **Multi-source rate**: 6.7%
- **Performance**: avg=2699ms, p50=1896ms, p95=7216ms
- **Methods**: rule=97%, template=0%

### ontology_expansion

- **Questions**: 25
- **Pass rate**: 19/25
- **Count accuracy**: 100.0%
- **Intent accuracy**: 100.0%
- **Ontology trigger rate**: 76.0%
- **Multi-source rate**: 8.0%
- **Performance**: avg=3474ms, p50=2426ms, p95=9859ms
- **Methods**: rule=88%, template=0%

**Failures:**
- `OE14`: no ontology
- `OE16`: no ontology
- `OE19`: no ontology
- `OE20`: no ontology
- `OE22`: no ontology
- `OE23`: no ontology

### cross_db_fusion

- **Questions**: 25
- **Pass rate**: 25/25
- **Count accuracy**: 100.0%
- **Intent accuracy**: 100.0%
- **Ontology trigger rate**: 68.0%
- **Performance**: avg=1991ms, p50=1913ms, p95=3130ms
- **Methods**: rule=52%, template=20%

### complex_multi_table

- **Questions**: 25
- **Pass rate**: 25/25
- **Count accuracy**: 100.0%
- **Intent accuracy**: 100.0%
- **Ontology trigger rate**: 100.0%
- **Multi-source rate**: 8.0%
- **Performance**: avg=3634ms, p50=2839ms, p95=9871ms
- **Methods**: rule=56%, template=0%

### statistics

- **Questions**: 25
- **Pass rate**: 20/25
- **Count accuracy**: 96.0%
- **Intent accuracy**: 84.0%
- **Ontology trigger rate**: 12.0%
- **Multi-source rate**: 44.0%
- **Performance**: avg=29985ms, p50=28379ms, p95=87209ms
- **Methods**: rule=32%, template=64%

**Failures:**
- `ST09`: intent=SEARCH
- `ST13`: count=1
- `ST15`: intent=COMPARE
- `ST21`: intent=SEARCH
- `ST23`: intent=SEARCH

### multi_turn

- **Questions**: 19
- **Pass rate**: 19/19
- **Count accuracy**: 100.0%
- **Intent accuracy**: 100.0%
- **Ontology trigger rate**: 63.2%
- **Multi-source rate**: 21.1%
- **Performance**: avg=7815ms, p50=1444ms, p95=34328ms
- **Methods**: rule=79%, template=21%

### edge_cases

- **Questions**: 5
- **Pass rate**: 4/5
- **Count accuracy**: 100.0%
- **Intent accuracy**: 80.0%
- **Performance**: avg=1168ms, p50=1105ms, p95=1623ms
- **Methods**: rule=100%, template=0%

**Failures:**
- `EC03`: empty_query

## System Configuration

- **Database**: unified_metadata.db (756,579 samples, 23,123 projects)
- **Data Sources**: 12 databases (GEO, NCBI, EBI, CellXGene, HTAN, HCA, PsychAD, ...)
- **Ontology**: UBERON + MONDO + CL + EFO (113K terms)
- **Memory**: 3-layer (Working + Episodic + Semantic)
- **LLM**: None (pure rule-based evaluation)
- **SQL Method**: 3-candidate (template + rule + LLM) with parallel execution
