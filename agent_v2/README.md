# SCeQTL-Agent V2

**Ontology-aware, cross-database metadata retrieval agent for human single-cell RNA-seq data.**

Unifies **756,579 samples** from **12 databases** (GEO, SRA/NCBI, EBI, CellXGene, HCA, HTAN, ...) into a single searchable platform with natural language query understanding, ontology expansion, cross-database deduplication, and a professional data portal.

## Quick Start

```bash
# 1. Install dependencies
pip install -e ".[dev]"

# 2. Build frontend
cd web && npm install && npm run build && cd ..

# 3. Start the server
python3 run_server.py --port 8000

# 4. Open browser
open http://localhost:8000
```

## Architecture

```
User Input (NL / ID / Faceted Search)
    │
    ▼
┌─────────────┐    ┌──────────────┐    ┌──────────────┐
│ QueryParser  │───▶│ Ontology     │───▶│ SQL Generator│
│ (rule+LLM)  │    │ Resolver     │    │ (3-candidate)│
└─────────────┘    └──────────────┘    └──────────────┘
                                             │
    ┌────────────────────────────────────────┘
    ▼
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│ Parallel SQL │───▶│ Cross-DB     │───▶│ Answer       │
│ Executor     │    │ Fusion       │    │ Synthesizer  │
└──────────────┘    └──────────────┘    └──────────────┘
                                             │
                                             ▼
                                      AgentResponse
                                  (summary + results + charts + provenance)
```

### 6-Stage Pipeline

| Stage | Module | Description |
|-------|--------|-------------|
| Parse | `src/understanding/parser.py` | Rule engine (85%) + LLM fallback, bilingual (中/EN) |
| Ontology | `src/ontology/resolver.py` | 113K terms (UBERON + MONDO + CL + EFO), 5-step resolution |
| Generate | `src/sql/engine.py` | 3-candidate strategy: template + rule + LLM |
| Execute | `src/sql/engine.py` | Parallel execution, first-valid-wins |
| Fuse | `src/fusion/engine.py` | UnionFind grouping + identity hash dedup |
| Synthesize | `src/synthesis/answer.py` | Summary + suggestions + charts + quality assessment |

### Key Features

- **Bilingual**: Chinese and English queries both supported
- **Ontology-aware**: "brain" expands to "cerebral cortex", "hippocampus", etc.
- **Cross-database dedup**: Same sample across GEO + SRA merged automatically
- **Zero LLM for 85% of queries**: Cost-efficient rule-based processing
- **3-layer memory**: Session + user history + system knowledge
- **Protocol-based DI**: All modules independently testable

## Web Portal (6 Pages)

| Route | Page | Description |
|-------|------|-------------|
| `/` | Landing | Hero section, quick stats, database cards, featured datasets |
| `/explore` | Explore | Faceted search sidebar + results table + pagination + URL state |
| `/explore/:id` | Detail | Dataset metadata, samples, cross-links, download options |
| `/stats` | Statistics | 6+ interactive Recharts charts, data availability cards |
| `/chat` | Chat | Natural language search with WebSocket streaming |
| `/downloads` | Downloads | Bulk download script generator (TSV/Bash/aria2) |

**Design System**: Professional portal design (inspired by Vercel/Linear/CellXGene/NCBI)
- Single accent color, full gray scale (50-950), 4px spacing grid
- Button/input/badge/card/code-block component system
- Build: 813KB JS (246KB gzip), 36KB CSS (8KB gzip), 0 TypeScript errors

## API Endpoints

### Core Agent API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/health` | GET | Component status |
| `/api/v1/query` | POST | Natural language query |
| `/api/v1/query/stream` | WS | WebSocket streaming |
| `/api/v1/entity/{id}` | GET | Entity lookup (auto ID detection) |
| `/api/v1/autocomplete` | GET | Field value autocomplete |
| `/api/v1/ontology/resolve` | GET | Ontology term resolution |
| `/api/v1/export` | POST | CSV / JSON / BibTeX export |
| `/api/v1/schema` | GET | Database schema summary |

### Portal API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/stats` | GET | Database statistics overview |
| `/api/v1/stats/dashboard` | GET | Comprehensive dashboard statistics |
| `/api/v1/explore` | POST | Faceted search with filters + facet counts |
| `/api/v1/explore/facets` | POST | Lightweight facet counts only |
| `/api/v1/dataset/{id}` | GET | Full dataset detail + downloads |
| `/api/v1/downloads/{id}` | GET | Download options for an entity |
| `/api/v1/downloads/manifest` | POST | Bulk download manifest generation |

### Performance (after optimization)

| Metric | Time |
|--------|------|
| Dashboard load | 5ms (precomputed stats, cached) |
| Health check | 0.5ms |
| Explore (unfiltered) | 22ms (precomputed facets) |
| Explore (filtered) | 60-500ms |
| NL query | 600-2000ms |

## Project Structure

```
agent_v2/
├── src/                    # Core Python modules (33 files)
│   ├── core/               # Models, interfaces, exceptions (26 dataclasses)
│   ├── understanding/      # Query parser (rule 85% + LLM 15%)
│   ├── sql/                # SQL generation + execution (3-candidate)
│   ├── ontology/           # Ontology resolution (113K terms)
│   ├── fusion/             # Cross-DB deduplication (UnionFind)
│   ├── synthesis/          # Answer generation (template + LLM)
│   ├── memory/             # 3-layer memory (working + episodic + semantic)
│   ├── dal/                # Database abstraction + connection pool
│   └── infra/              # LLM clients, cost control, circuit breaker
│
├── api/                    # FastAPI backend (17 files)
│   ├── main.py             # App entry, middleware, rate limiting
│   ├── schemas.py          # Pydantic request/response models
│   ├── routes/             # 9 route modules
│   │   ├── query.py        #   NL query endpoint
│   │   ├── explore.py      #   Faceted search (optimized)
│   │   ├── stats.py        #   Statistics (precomputed)
│   │   ├── dataset.py      #   Dataset detail + downloads
│   │   ├── downloads.py    #   Bulk download manifest
│   │   ├── entity.py       #   Entity lookup
│   │   ├── ontology.py     #   Ontology resolution
│   │   ├── export.py       #   Data export
│   │   └── session.py      #   Session management
│   └── services/
│       └── download_resolver.py  # URL pattern resolver per database
│
├── web/                    # React + TypeScript + TailwindCSS (32 files)
│   ├── src/
│   │   ├── pages/          # 6 page components
│   │   ├── components/     # UI component library
│   │   ├── hooks/          # useFacetedSearch, useDebounce, useWebSocket
│   │   ├── services/       # API client with stale-while-revalidate cache
│   │   └── types/          # TypeScript interfaces
│   └── dist/               # Production build
│
├── tests/                  # Testing (19 files)
│   ├── unit/               # 134 unit tests (6 modules)
│   ├── benchmark/          # 154-question evaluation suite
│   └── test_phase*.py      # Integration tests
│
└── data/                   # Runtime data
    ├── ontologies/         # 4 OBO files + ontology_cache.db (103MB)
    └── memory/             # episodic.db + semantic.db
```

## Testing

```bash
# Unit tests (134 tests, ~2s)
python3 -m pytest tests/unit/ -v

# E2E integration tests
python3 tests/test_phase1_e2e.py    # 10/10
python3 tests/test_phase2_e2e.py    # 13/13

# Benchmark evaluation (154 questions)
python3 tests/benchmark/run_benchmark.py
```

## Benchmark Results (154 questions)

| Category | Pass Rate |
|----------|-----------|
| Simple Search | 30/30 (100%) |
| Ontology Expansion | 19/25 (76%) |
| Cross-DB Fusion | 25/25 (100%) |
| Complex Queries | 25/25 (100%) |
| Statistics | 20/25 (80%) |
| Multi-turn | 19/19 (100%) |
| **Overall** | **142/154 (92.2%)** |

Resolution method: Rule 68.6%, Template 16.3%, LLM 0% → 84.9% zero-LLM-cost queries.

## Data Sources

| Source | Projects | Series | Samples | Key IDs |
|--------|----------|--------|---------|---------|
| GEO | 5,406 | 5,406 | 342,368 | GSE*, GSM* |
| NCBI/SRA | 8,156 | 7,622 | 217,513 | PRJNA*, SRS* |
| EBI | 1,019 | — | 160,135 | E-MTAB*, SAMEA* |
| CellXGene | 269 | 1,086 | 33,984 | UUID-based |
| Others (3) | — | — | 2,579 | Various |
| **Total** | **23,123** | **15,968** | **756,579** | |

Cross-links: 4,142 PRJNA↔GSE + 5,756 PMID + 68 DOI = 9,966 total

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SCEQTL_DB_PATH` | Auto-detect | Path to unified_metadata.db |
| `ANTHROPIC_API_KEY` | — | Claude API key (optional, for LLM mode) |
| `SCEQTL_RATE_LIMIT` | 60 | API rate limit (requests/minute/IP) |
| `SCEQTL_CORS_ORIGINS` | `*` | Comma-separated allowed origins |
| `SCEQTL_DEBUG` | — | Show detailed errors in API responses |

## Development Phases

| Phase | Scope | Status |
|-------|-------|--------|
| 0 | Infrastructure (DI, models, protocols, LLM clients) | Done |
| 1 | Core pipeline (parser, SQL gen, fusion, coordinator) | Done |
| 2 | Ontology (113K terms) + memory (3-layer) + DB optimization | Done |
| 3 | Web app (FastAPI + React + WebSocket) | Done |
| 4 | Evaluation framework (154 questions, 92.2% pass) | Done |
| 5 | Engineering quality (exceptions, DI, connection pool, 134 unit tests) | Done |
| 6 | Web enhancement (streaming, markdown, export, responsive) | Done |
| 7 | API hardening (rate limit, logging, RFC 7807 errors) | Done |
| 8 | Portal upgrade (6 pages, faceted search, downloads, design system) | Done |
| 9 | Performance optimization (precomputed stats, 16,657x dashboard speedup) | Done |

## License

MIT
