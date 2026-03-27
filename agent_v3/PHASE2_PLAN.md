# Phase 2 Implementation Plan

**Date:** 2026-03-09
**Status:** Planning
**Goal:** Ontology resolution, memory system, performance optimization

---

## Overview

Phase 2 focuses on three core enhancements:
1. **Ontology Resolution Engine**: Map user terms to standard ontologies (UBERON, MONDO, CL)
2. **Memory System**: 3-layer architecture (working + episodic + semantic)
3. **Performance Optimization**: Composite indexes, FTS5 integration, query plan analysis

---

## Architecture References

### Best Practices Studied
1. **TAG (Table-Augmented Generation)** - UC Berkeley/Stanford CIDR 2025
   - LLM reasoning over structured query results
   - Progressive disclosure: summary → details → raw data

2. **CHESS** - UC Berkeley VLDB 2023
   - Schema linking via embedding similarity
   - Multi-candidate SQL generation with validation

3. **MAC-SQL** - Microsoft Research ACL 2023
   - Multi-agent collaboration for complex queries
   - Ontology-grounded entity resolution

4. **CellAtria** - Broad Institute 2024
   - Cell type ontology (CL) integration
   - Fuzzy matching with ontology expansion

### Key Design Decisions
- **Ontology storage**: SQLite cache (not API calls) for <50ms latency
- **Memory architecture**: 3-layer (working/episodic/semantic) not Redis
- **Expansion strategy**: Progressive (exact → parent → children → siblings)
- **Cache invalidation**: TTL-based (1 hour working, 7 days episodic, permanent semantic)

---

## Module 1: Ontology Resolution Engine

### 1.1 Data Preparation

**Ontology Sources:**
- UBERON (anatomy): ~15,000 terms, OBO format
- MONDO (disease): ~25,000 terms, OBO format
- CL (cell types): ~6,000 terms, OBO format
- EFO (assays): ~3,000 terms, OBO format

**Download & Parse:**
```bash
# Download ontologies
wget http://purl.obolibrary.org/obo/uberon.obo
wget http://purl.obolibrary.org/obo/mondo.obo
wget http://purl.obolibrary.org/obo/cl.obo
wget http://purl.obolibrary.org/obo/efo.obo

# Parse OBO → SQLite
python scripts/parse_ontologies.py
```

**Schema:**
```sql
CREATE TABLE ontology_terms (
    ontology_id TEXT PRIMARY KEY,
    ontology_source TEXT NOT NULL,
    label TEXT NOT NULL,
    definition TEXT,
    synonyms_json TEXT,  -- JSON array
    parent_ids_json TEXT,
    child_ids_json TEXT,
    ancestor_ids_json TEXT,  -- All ancestors for is-a reasoning
    descendant_ids_json TEXT  -- All descendants for expansion
);

CREATE INDEX idx_onto_label ON ontology_terms(label COLLATE NOCASE);
CREATE INDEX idx_onto_source ON ontology_terms(ontology_source);

-- FTS5 for fuzzy matching
CREATE VIRTUAL TABLE fts_ontology USING fts5(
    ontology_id UNINDEXED,
    label,
    synonyms,
    content=ontology_terms
);

-- Value mapping cache (user term → DB values)
CREATE TABLE ontology_value_map (
    ontology_id TEXT NOT NULL,
    field_name TEXT NOT NULL,  -- 'tissue', 'disease', 'cell_type'
    db_value TEXT NOT NULL,
    sample_count INTEGER,
    PRIMARY KEY (ontology_id, field_name, db_value)
);
```

### 1.2 Resolution Pipeline

**Input:** User term (e.g., "brain", "大脑", "cerebral")
**Output:** OntologyTerm + matched DB values + expansion options

**Algorithm:**
```python
class OntologyResolver:
    async def resolve(
        self,
        term: str,
        field_type: str,  # 'tissue', 'disease', 'cell_type'
        expand: bool = True
    ) -> ResolvedEntity:

        # Step 1: Exact match
        exact = self._exact_match(term, field_type)
        if exact:
            return self._build_resolved(exact, expand)

        # Step 2: Synonym match
        synonym = self._synonym_match(term, field_type)
        if synonym:
            return self._build_resolved(synonym, expand)

        # Step 3: FTS5 fuzzy match
        fuzzy = self._fuzzy_match(term, field_type)
        if fuzzy and fuzzy.score > 0.8:
            return self._build_resolved(fuzzy.term, expand)

        # Step 4: LLM-assisted disambiguation
        if self.llm and len(fuzzy) > 1:
            disambiguated = await self._llm_disambiguate(term, fuzzy)
            return self._build_resolved(disambiguated, expand)

        # Step 5: Fallback to free text
        return ResolvedEntity(
            original=term,
            ontology_term=None,
            db_values=[],
            confidence=0.3,
            method='fallback'
        )

    def _build_resolved(self, term: OntologyTerm, expand: bool) -> ResolvedEntity:
        # Get DB values for this term
        db_values = self._get_db_values(term.ontology_id)

        # Optionally expand to children
        if expand:
            for child_id in term.child_ids[:10]:  # Limit expansion
                child_values = self._get_db_values(child_id)
                db_values.extend(child_values)

        return ResolvedEntity(
            original=term.label,
            ontology_term=term,
            db_values=db_values,
            expansion_applied=expand,
            confidence=0.95,
            method='ontology'
        )
```

### 1.3 Value Mapping

**Pre-compute mapping:**
```python
# For each ontology term, find matching DB values
for term in ontology_terms:
    # Exact match
    exact_matches = db.execute(
        "SELECT tissue, COUNT(*) FROM unified_samples "
        "WHERE tissue = ? GROUP BY tissue",
        [term.label]
    )

    # Synonym match
    for syn in term.synonyms:
        syn_matches = db.execute(
            "SELECT tissue, COUNT(*) FROM unified_samples "
            "WHERE tissue LIKE ? GROUP BY tissue",
            [f"%{syn}%"]
        )

    # Store mapping
    for value, count in matches:
        db.execute(
            "INSERT INTO ontology_value_map VALUES (?, ?, ?, ?)",
            [term.ontology_id, 'tissue', value, count]
        )
```

### 1.4 Integration with SQL Generator

**Before:**
```python
# Direct LIKE query
WHERE tissue LIKE '%brain%'
```

**After:**
```python
# Ontology-expanded query
resolved = await ontology_resolver.resolve('brain', 'tissue')
values = [v.raw_value for v in resolved.db_values]
WHERE tissue IN (?, ?, ?, ...)  # 'brain', 'cerebral cortex', 'hippocampus', ...
```

---

## Module 2: Memory System

### 2.1 Working Memory (Session-level)

**Implementation:**
```python
class WorkingMemory:
    """In-process session cache"""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.query_history: List[ParsedQuery] = []
        self.result_cache: LRUCache = LRUCache(maxsize=50)
        self.ontology_cache: Dict[str, ResolvedEntity] = {}
        self.active_filters: QueryFilters = QueryFilters()

    def add_query(self, query: ParsedQuery, results: List[FusedRecord]):
        self.query_history.append(query)
        cache_key = self._compute_cache_key(query)
        self.result_cache.put(cache_key, results)

        # Update active filters for multi-turn
        if query.sub_intent == 'refinement':
            self.active_filters = self._merge_filters(
                self.active_filters,
                query.filters
            )

    def get_context(self) -> SessionContext:
        return SessionContext(
            session_id=self.session_id,
            turns=len(self.query_history),
            recent_queries=self.query_history[-5:],
            active_filters=self.active_filters
        )
```

### 2.2 Episodic Memory (User-level)

**Schema:**
```sql
CREATE TABLE user_profiles (
    user_id TEXT PRIMARY KEY,
    research_domain TEXT,  -- 'cancer', 'neuroscience', etc.
    preferred_tissues_json TEXT,
    preferred_sources_json TEXT,
    created_at TEXT,
    last_active TEXT
);

CREATE TABLE query_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    query_text TEXT NOT NULL,
    parsed_intent TEXT,
    result_count INTEGER,
    success INTEGER,  -- 1 if user engaged with results
    feedback_score INTEGER,  -- 1-5 rating
    created_at TEXT,
    FOREIGN KEY (user_id) REFERENCES user_profiles(user_id)
);

CREATE TABLE query_patterns (
    user_id TEXT NOT NULL,
    pattern_type TEXT NOT NULL,  -- 'tissue', 'disease', 'assay'
    pattern_value TEXT NOT NULL,
    frequency INTEGER DEFAULT 1,
    last_used TEXT,
    PRIMARY KEY (user_id, pattern_type, pattern_value)
);
```

**Usage:**
```python
class EpisodicMemory:
    def record_query(self, user_id: str, query: ParsedQuery, results: List):
        # Save to history
        self.db.execute(
            "INSERT INTO query_history VALUES (?, ?, ?, ?, ?, ?, ?)",
            [user_id, session_id, query.original_text, ...]
        )

        # Update patterns
        for tissue in query.filters.tissues:
            self.db.execute(
                "INSERT INTO query_patterns VALUES (?, 'tissue', ?, 1, ?) "
                "ON CONFLICT DO UPDATE SET frequency = frequency + 1",
                [user_id, tissue, now()]
            )

    def get_user_preferences(self, user_id: str) -> UserProfile:
        # Get top patterns
        patterns = self.db.execute(
            "SELECT pattern_type, pattern_value, frequency "
            "FROM query_patterns WHERE user_id = ? "
            "ORDER BY frequency DESC LIMIT 10",
            [user_id]
        )
        return UserProfile(patterns=patterns)
```

### 2.3 Semantic Memory (System-level)

**Schema Knowledge Base:**
```sql
CREATE TABLE field_knowledge (
    table_name TEXT NOT NULL,
    field_name TEXT NOT NULL,
    semantic_type TEXT,  -- 'tissue', 'disease', 'id', 'metric'
    null_pct REAL,
    unique_count INTEGER,
    top_values_json TEXT,
    last_analyzed TEXT,
    PRIMARY KEY (table_name, field_name)
);

CREATE TABLE query_templates (
    template_id INTEGER PRIMARY KEY AUTOINCREMENT,
    intent TEXT NOT NULL,
    sql_template TEXT NOT NULL,
    success_count INTEGER DEFAULT 0,
    avg_exec_time_ms REAL,
    created_at TEXT
);

CREATE TABLE value_synonyms (
    canonical_value TEXT NOT NULL,
    synonym TEXT NOT NULL,
    field_name TEXT NOT NULL,
    confidence REAL,
    PRIMARY KEY (field_name, synonym)
);
```

**Auto-learning:**
```python
class SemanticMemory:
    def learn_from_query(self, query: ParsedQuery, sql: str, exec_time: float):
        # Extract successful pattern
        if exec_time < 1000:  # Fast query
            template = self._generalize_sql(sql)
            self.db.execute(
                "INSERT INTO query_templates VALUES (?, ?, ?, 1, ?, ?) "
                "ON CONFLICT DO UPDATE SET success_count = success_count + 1",
                [query.intent, template, exec_time, now()]
            )

    def suggest_query_template(self, query: ParsedQuery) -> Optional[str]:
        # Find matching template
        templates = self.db.execute(
            "SELECT sql_template FROM query_templates "
            "WHERE intent = ? ORDER BY success_count DESC LIMIT 1",
            [query.intent]
        )
        return templates[0] if templates else None
```

---

## Module 3: Performance Optimization

### 3.1 Composite Indexes (Retry)

**Strategy:** Create indexes incrementally to avoid memory issues

```python
# Create one index at a time with progress tracking
indexes = [
    ("idx_samples_tissue_disease",
     "CREATE INDEX idx_samples_tissue_disease ON unified_samples(tissue, disease) WHERE tissue IS NOT NULL"),
    ("idx_samples_source_tissue",
     "CREATE INDEX idx_samples_source_tissue ON unified_samples(source_database, tissue)"),
    # ... more
]

for name, sql in indexes:
    print(f"Creating {name}...")
    conn.execute(sql)
    conn.commit()  # Commit after each
    print(f"  ✓ {name}")
```

### 3.2 FTS5 Integration in SQL Generator

**Replace LIKE with FTS5:**
```python
# Before
WHERE tissue LIKE '%brain%'

# After
WHERE sample_pk IN (
    SELECT sample_pk FROM fts_samples
    WHERE fts_samples MATCH 'tissue:brain'
)
```

### 3.3 Query Plan Analysis

**Add EXPLAIN QUERY PLAN:**
```python
class SQLExecutor:
    def execute_with_analysis(self, sql: str) -> ExecutionResult:
        # Get query plan
        plan = self.conn.execute(f"EXPLAIN QUERY PLAN {sql}").fetchall()

        # Execute
        result = self.conn.execute(sql)

        # Analyze plan for issues
        issues = self._analyze_plan(plan)
        if issues:
            logger.warning(f"Query plan issues: {issues}")

        return result
```

---

## Implementation Timeline

### Week 1: Ontology Engine
- [ ] Download and parse ontologies (UBERON, MONDO, CL, EFO)
- [ ] Create ontology cache database
- [ ] Implement OntologyResolver with 5-step pipeline
- [ ] Pre-compute ontology_value_map
- [ ] Add FTS5 index on ontology terms
- [ ] Unit tests for resolution accuracy

### Week 2: Memory System
- [ ] Implement WorkingMemory (in-process)
- [ ] Implement EpisodicMemory (SQLite)
- [ ] Implement SemanticMemory (SQLite)
- [ ] Add memory integration to Coordinator
- [ ] Multi-turn dialogue tests

### Week 3: Performance & Integration
- [ ] Create composite indexes incrementally
- [ ] Integrate FTS5 into SQL generator
- [ ] Add query plan analysis
- [ ] Integrate ontology resolver into query pipeline
- [ ] End-to-end performance benchmarks

### Week 4: Testing & Documentation
- [ ] 150-question benchmark suite
- [ ] Accuracy metrics (precision, recall)
- [ ] Latency profiling
- [ ] Cost analysis
- [ ] Phase 2 summary document

---

## Success Metrics

### Accuracy
- Ontology resolution precision: >90%
- Query understanding accuracy: >85%
- Multi-turn context retention: >95%

### Performance
- Ontology resolution: <50ms
- Memory lookup: <10ms
- Query execution: <2s for 95th percentile

### User Experience
- Zero-result rate: <5%
- Suggestion relevance: >80% click-through
- Multi-turn success: >70%

---

## Files to Create

```
agent_v2/
├── src/
│   ├── ontology/
│   │   ├── __init__.py
│   │   ├── resolver.py          # OntologyResolver
│   │   ├── cache.py             # OntologyCache (SQLite)
│   │   └── parser.py            # OBO parser
│   ├── memory/
│   │   ├── working.py           # WorkingMemory
│   │   ├── episodic.py          # EpisodicMemory
│   │   └── semantic.py          # SemanticMemory
│   └── optimization/
│       ├── index_builder.py     # Incremental index creation
│       └── query_analyzer.py    # EXPLAIN QUERY PLAN analysis
├── scripts/
│   ├── download_ontologies.sh
│   ├── parse_ontologies.py
│   └── build_value_map.py
├── tests/
│   ├── test_ontology_resolver.py
│   ├── test_memory_system.py
│   └── test_phase2_e2e.py
└── data/
    └── ontologies/
        ├── uberon.obo
        ├── mondo.obo
        ├── cl.obo
        └── efo.obo
```

---

## Next Steps

1. Review this plan with user
2. Start with ontology engine (highest impact)
3. Implement incrementally with tests
4. Integrate with existing Phase 1 code
5. Benchmark and optimize

