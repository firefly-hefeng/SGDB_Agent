# SCeQTL Portal (SGDB)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Backend: 797 tests](https://img.shields.io/badge/backend-797%20pass-brightgreen)]()
[![Frontend: 45 tests](https://img.shields.io/badge/frontend-45%20pass-brightgreen)]()
[![Lighthouse: 96-100](https://img.shields.io/badge/lighthouse-96--100-brightgreen)]()

> Status: **🚀 publication-grade** — Phase 39 in progress (dual-agent hardening:
> Discover eval + frontend usability + agent interface). 11/11 routes render
> with 0 console errors, all empty-filter endpoints sub-10 ms warm, axe-core
> a11y clean, Lighthouse ≥ 96 on every audited page.

## What is it

A unified search-and-discovery portal for single-cell RNA-seq metadata. It
brings together **943,732 human single-cell samples from 8 curated sources** —
GEO, EGA, NCBI, EBI, CellxGene, PsychAD, HTAN, HCA — into one ontology-aligned
catalog you can search by tissue, disease, assay, organism, cell type, or free
text. When the curated catalog falls short, the same query streams out live to
**6 federated databases** — GEO, SRA, EBI BioStudies, Single-Cell Expression
Atlas (SCEA), CellxGene, HCA — in parallel (Server-Sent Events) for live
cross-database discovery. (SRA and SCEA are queryable live via Discover but are
not part of the curated catalog.)

## Who is it for

- **Biologists & clinicians** searching for relevant scRNA-seq datasets
  by phenotype rather than archive-specific accession numbers.
- **Computational biologists** running unified meta-analyses; the
  `/scdbAPI/explore` endpoint paginates the entire catalog as JSON.
- **Curators & data stewards** validating coverage against the live
  archives via the Discover stream.

## How to run (60 seconds)

```bash
# 1. One-shot install
pip install -e ".[dev]"

# 2. Build frontend
( cd web && npm install && npm run build )

# 3. Launch
python3 run_server.py --port 8000

# 4. Open
open http://localhost:8000/singledb/
```

The first launch takes ~110 s to warm caches (ontology + featured + explore +
projects/series). After that every empty-filter endpoint serves in <10 ms.

---

## Headline metrics (frontend baseline: Phase 27, 2026-05-15; counts current as of Phase 39)

| Axis | Result |
|---|---:|
| Routes that render without console errors | **11 / 11** (headless browser walkthrough) |
| End-to-end user flows verified | **7 / 7** (interaction walkthrough) |
| Lighthouse — performance / a11y / best-practices / SEO | **99-100 / 96-100 / 100 / 100** |
| axe-core a11y violations | **0** across 9 audited routes |
| Web Vitals — LCP / TBT / CLS (production build) | **≤ 736 ms / ≤ 37 ms / ≤ 0.082** |
| `POST /scdbAPI/explore` (empty filter) cold→warm | **36.8 s → 4 ms** (9000× faster) |
| `POST /scdbAPI/projects/search` cold→warm | **3.5 s → 6 ms** |
| `POST /scdbAPI/series/search` cold→warm | **1.5 s → 3 ms** |
| `GET /scdbAPI/collections/featured` cold→warm | **30 s → 3 ms** (10000× faster) |
| Backend unit tests | **797 pass + 1 skipped** |
| Frontend unit tests | **45 pass** (7 files) |
| Frontend build | ✅ clean (vite ~30 s, 227 kB main + 49 kB vendor, 394 kB charts lazy) |
| ESLint | ✅ 0 errors, 3 advisory HMR warnings |
| Discovery deployment | **integrated** (no iframe, single process) |

---

## Quick start

```bash
# 1. Install
pip install -e ".[dev]"

# 2. Build frontend
cd web && npm install && npm run build && cd ..

# 3. Configure (copy .env.example → .env; KIMI_API_KEY optional for rule mode)
cp .env.example .env

# 4. Launch
python3 run_server.py --host 0.0.0.0 --port 8000

# 5. Verify
curl http://localhost:8000/scdbAPI/health
# expected: {"status": "healthy", "components": {"database": ..., "agent": ...,
#            "ontology": ..., "memory": ..., "discovery": ...}}

# 6. Open the web UI (served by FastAPI at /, or via nginx pointing to web/dist/)
```

See [`docs/DEPLOYMENT_CHECKLIST.md`](docs/DEPLOYMENT_CHECKLIST.md) for the
production deployment + homepage integration guide.

---

## Architecture

```
NL query (EN / CN / mixed)
    ↓
QueryParser (rule, ID extraction, negation scope, temporal,
             strict-mode, treatment / diseased / iPSC hooks)
    + V1QueryParser (LLM, schema-aware, optional)
    ↓
OntologyResolver (UBERON / MONDO / CL / EFO ontology cache; 113 K terms)
    ↓
ContextualSQLGenerator → SQLGenerator (3 strategies)
    ├── Template (ID lookup, statistics)
    ├── Rule (indexed equality + ontology IN() expansion,
    │         same-type entity OR, umbrella exclusion)
    └── LLM (complex / ambiguous queries)
    ↓
ParallelSQLExecutor (asyncio + 30 s timeout + true COUNT(*))
    ↓
Self-correction loop (drop strict_mode + LLM rewrite;
                      broaden suggestions for honest zero-results)
    ↓
CrossDBFusionEngine (hash dedup + round-robin source interleave)
    ↓
AnswerSynthesizer (summary + chart specs + provenance + suggestions)
```

Pipeline stages emit a `ReasoningTrace` carried through `ProvenanceInfo` so
the frontend can show every step.

---

## Key features

| Feature | Status | Notes |
|---|---|---|
| Bilingual NL (EN + 中文) | ✅ | parser + ontology both bilingual |
| Ontology expansion | ✅ | 113 K UBERON / MONDO / CL / EFO terms |
| Cross-database dedup | ✅ | biological identity hash |
| Indexed fast-path | ✅ | tissue_standard / disease_category / *_common |
| Honest zero-result | ✅ | broaden suggestions instead of silent widening |
| GROUP BY aggregation | ✅ | sum-of-counts as `total_count` |
| Multi-turn refinement | ✅ | replace / add / keep semantics |
| Self-correction | ✅ | drop strict_mode → LLM rewrite → broaden suggestions |
| Treatment / iPSC / diseased shorthand | ✅ Phase 19-G | parser hooks |
| Pancreatic islet / brain regions / CD8+ T cell etc. | ✅ Phase 20-A | specific cell type & sub-tissue detection |
| In-process cross-DB discovery | ✅ Phase 27 | GEO/SRA/EBI/SCEA/CellxGene/HCA via `/scdbAPI/discover/*` SSE |
| Native React Discover page | ✅ Phase 27 | streaming UI, mirror detection, intent chips, LLM synth |
| Global download manifest | ✅ Phase 27 | localStorage-backed cart with curl / Python export |
| Lazy-loaded React routes | ✅ Phase 27 | initial JS 435 kB → 225 kB (-48 %) |
| Live stats in TopNav / Landing | ✅ Phase 27 | no more drift-prone hard-coded literals |
| Modal / Toast UI primitives | ✅ Phase 27 | replaced all native `prompt()` / `confirm()` |

---

## Repository layout

```
agent_v3/
├── src/                           Core agent code
│   ├── agent/coordinator.py       Pipeline orchestrator
│   ├── understanding/             Parsers (rule + V1 LLM)
│   ├── ontology/                  UBERON/MONDO/CL/EFO resolver + cache
│   ├── sql/                       SQL generation (engine + contextual + subquery + aggregation builders)
│   ├── fusion/                    Cross-DB dedup
│   ├── synthesis/                 Answer composer
│   ├── memory/                    Session + episodic + semantic memory
│   ├── knowledge/                 DataStatsAnalyzer + CardinalityEstimator
│   ├── dal/                       SQLite read-only pool
│   └── discovery/                 Phase 27 — in-process cross-DB agent
│                                  (vendored from api-routing-agent v0.5.2)
├── api/                           FastAPI routes (~46 endpoints)
│   ├── main.py                    App entry
│   ├── routes/                    query, projects, advanced_search, workspace,
│   │                              downloads, discover (Phase 27), ...
│   └── schemas.py                 Pydantic schemas
├── web/                           React + Vite frontend
│   ├── src/                       components, pages, hooks, services, types
│   └── dist/                      Built static assets (after `npm run build`)
├── tests/
│   ├── unit/                      441 unit tests
│   └── benchmark_v2/              NL2SQL gold + real-scenarios + evaluators
│       ├── ground_truth/          gold dataset (v2 + verified)
│       ├── real_scenarios/        30 researcher-realistic queries
│       ├── evaluators/            12 axis evaluators
│       └── scoring/               bootstrap CI + composite + stratified
├── data/                          Memory DBs + ontology cache + schema YAML
├── config/                        config.yaml + v3.json
├── scripts/                       install_human_db.py
├── docs/                          Active design + phase reports (see docs/README.md)
│   └── archive/                   Historical phases 1-16 (rotated out)
├── run_server.py                  Server launcher
├── PROJECT_STATUS.md              Top-level status index
└── README.md                      This file
```

---

## Documentation map

The full doc index is at [`docs/README.md`](docs/README.md). Top-level
entry points:

| For… | Read |
|---|---|
| Deploying to homepage | [`docs/DEPLOYMENT_CHECKLIST.md`](docs/DEPLOYMENT_CHECKLIST.md) |
| Handing tasks to biologists | [`docs/HUMAN_ANNOTATION_DELIVERABLES.md`](docs/HUMAN_ANNOTATION_DELIVERABLES.md) |
| Latest phase summary | [`docs/PHASE26_PROGRESS.md`](docs/PHASE26_PROGRESS.md) |
| Benchmark design | [`docs/BENCHMARK_V2_DESIGN.md`](docs/BENCHMARK_V2_DESIGN.md) |
| Annotation theoretical brief | [`docs/ANNOTATION_REQUIREMENTS.md`](docs/ANNOTATION_REQUIREMENTS.md) |
| Project status (developer index) | [`PROJECT_STATUS.md`](PROJECT_STATUS.md) |
| Architecture history | `docs/archive/` |

---

## Running benchmarks

```bash
# Real-scenarios v2 (30 queries, ~5 min)
python3 -m tests.benchmark_v2.real_scenarios.run_scenarios_v2

# NL2SQL Gold v2 (29 useful, 11 min, rule mode)
python3 -m tests.benchmark_v2.run_nl2sql_v2 \
    --parser-mode rule \
    --out tests/benchmark_v2/results/your_run

# Peer-tool comparison (Kimi-K2.6 pure-LLM baseline, on first 5)
python3 -m tests.benchmark_v2.peer_compare.pure_llm_runner \
    --gold tests/benchmark_v2/ground_truth/nl2sql_gold_v2_ontology.json \
    --out tests/benchmark_v2/peer_compare/results/your_run.json \
    --limit 5
```

Results land in `tests/benchmark_v2/results/` (small JSON files) or
`tests/benchmark_v2/real_scenarios/results_v2.json`. Bootstrap CI is computed
with seed=42 for reproducibility.

---

## DB & config

- **Database**: `../database_development/unified_db/human_metadata.db`
  (~1.6 GB, content fingerprint `f88b2025eda755b1` — the snapshot all evals pin to)
- **Ontology cache**: `data/ontologies/ontology_cache.db` (113 K terms)
- **Memory DBs**: `data/memory/` (episodic + semantic + feedback)
- **Schema knowledge**: `data/schema_knowledge.yaml`
- **Server config**: `config/config.yaml` + `config/v3.json`

---

## What's next

1. **Biologist user testing** — agent quality is publication-grade
   (rule `cr_target` 94.76 %, LLM 95.72 %, RS v2 30/30, RS v3 hard 20/20).
   Hand `docs/HUMAN_ANNOTATION_DELIVERABLES.md` to ≥3 biologists.
2. **Review 31 Phase 25 v3 gold candidates** —
   `tests/benchmark_v2/ground_truth/nl2sql_gold_v3_candidates.json`.
   Verified candidates lift useful-question count 22 → ~53.
3. **Peer-tool comparison full run** — Vanna, DIN-SQL on gold v2
   (scaffold ready in `tests/benchmark_v2/peer_compare/`).
4. **Phase 27 candidates** (deferred until real-user data): histogram
   per-bucket tolerance (22.15 %), port umbrella/strict/negation prompt
   to `--parser-mode reasoning/auto`.

See [`PROJECT_STATUS.md`](PROJECT_STATUS.md) §6 for the recommended cadence.

---

## Repository

Source: **[github.com/firefly-hefeng/SGDB_Agent](https://github.com/firefly-hefeng/SGDB_Agent)**

## License

MIT. See [`LICENSE`](LICENSE).

A peer-reviewed publication describing the portal is planned; author and
acknowledgement lists will be finalised at submission time.
