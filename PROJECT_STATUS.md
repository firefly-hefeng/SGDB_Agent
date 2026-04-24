# SCeQTL Portal (SGDB) — Project status

> Last update: **2026-06-04** (Phase 36 — **downloader overhaul**: integrated the ENA Portal API + GEO suppl listing as a universal *deep* resolver, turning the downloader from directory/page *pointers* into **exact, byte-sized, MD5-checksummed files** with high-speed Aspera paths. `POST /downloads/estimate` previews total size before a pull; all 5 script generators (bash/aria2/Snakemake/Python/TSV) carry sizes + checksum verification. Unlocked **EBI** (E-MTAB→PRJEB study mapping → BAM, was 0%) and fixed two real pre-existing bugs (**CellXGene h5ad downloads were silently broken**; NULL-`project_id` crash). New offline `download_resolution_bench.py`: **open-access resolution 100%** (geo/ncbi/ebi/cellxgene), 99% sized, 95.5% checksummed (only controlled-access EGA unresolvable, by design). 39 new unit tests; `tsc`/`vite build`/eslint/vitest clean. See [`docs/phases/PHASE36_DOWNLOADER_OVERHAUL.md`](docs/phases/PHASE36_DOWNLOADER_OVERHAUL.md). Eval composite holds at **85.45** (agent unchanged). Prior: **2026-05-28** Phase 35 eval consolidation; **2026-05-26** Phase 33 — running-system performance & frontend hardening; cf. [`docs/phases/PHASE33_RUNNING_SYSTEM_HARDENING.md`](docs/phases/PHASE33_RUNNING_SYSTEM_HARDENING.md) and the frontend-audit follow-up [`docs/phases/PHASE33_FRONTEND_AUDIT.md`](docs/phases/PHASE33_FRONTEND_AUDIT.md) — **two rounds, 13 user-reported issues fixed + verified with a real-browser Playwright harness (12 e2e specs).** R1: HCA 400 (Azul size>75), Discover 20→50/source, manifest multi-select, Discover→workspace star, Advanced→workspace bulk-save + shared-cache fix, Advanced state survives hard reload, full SQL render+copy. R2: honest result totals (no fake "deduped to 5000") + narrow/broaden hints, Advanced→manifest add, Featured collections land on exact curated subset (`collection=` param), Explore facets use cleaned `*_standard` columns + show all values (cap 30→800), refine-within-results (AND a 2nd query). Prior: **2026-05-22** Phase 32 v4.)
> **Phase 40 (2026-06-15):** publication-grade Discover eval + system polish.
> **(1) Discover (api-routing-agent) eval credibility — the centerpiece:** built
> the missing **human-expert annotation/IAA layer** (`tests/benchmark_discovery/expert/`)
> — 181-pair stratified sample blind-graded by 3 independent expert agents
> (曹广硕/何锋/吕同轩); first **real** human↔LLM calibration (ordinal κ=0.477,
> **binary AC1=0.670**) replacing the circular Kimi-vs-Kimi 0.537/0.894;
> Krippendorff α=0.574; per-source κ; key finding that the LLM annotator grades
> literally (≈strict expert κ=0.74) not biologically (≈0.37-0.40) and over-uses
> grade-1. Fixed a metric bug (mirror dups → recall/nDCG>1.0), **activated
> distractor_rate@k** (39 expert-confirmed hard-negatives), shipped **GT v2.1**
> (expert-corrected), and committed the benchmark to git. **Agent:** async-
> offloaded blocking LLM calls; **reverted reranker default to no-rerank** on
> evidence (intent_feature gave MRR −0.044, p=0.97 on GT v2.1). See
> [`docs/phases/PHASE40_MASTER_PLAN.md`](docs/phases/PHASE40_MASTER_PLAN.md) +
> `tests/benchmark_discovery/expert/EXPERT_REVIEW_吕同轩.md`.
> **(2) Usability:** project facets 3→5 / series 4→6 (+year, data_availability,
> assay_modality, data_format) + filters; CellTypes HowToUse; cellxgene download
> sizing; agent manifest error-contract + self-locating base_url + MCP contract
> test + `limit` fix + 429 Retry-After. Version reconciled to **3.0.0**.
> Verified live: endpoint sweep 0 × 5xx, **859 unit tests**, vitest 87/87, vite
> build clean, Playwright e2e 10/10.
> **(3) Optimal LLM participation policy (closed-loop) — resolves the k2.6
> latency problem by changing _when_ the LLM runs, not _which_ model.** Built an
> eval-grounded **LLM-on-demand cascade** (`GatedCascadeParser`, now the `auto`/
> default `parser_mode="cascade"`): rule-first, escalate to the V1 LLM parser
> only on a calibrated confidence+structural gate (strict/negation/complex/
> aggregation). On the cr_target gold (kimi-k2.6, clean two-arm run): cascade
> **92.4** vs always-LLM `v1` **70.7** vs always-rule **86.1** — captures 91% of
> the oracle ceiling (93.0) while calling the LLM on only **~30%** of queries.
> Live: an easy query is now **0.85 s** (rule path) vs ~25 s under the old
> always-LLM mode; structural queries still escalate (~11 s). So the portal is
> **both more accurate and ~30× faster on the common case**. Method + harness:
> [`docs/phases/PHASE40_LLM_PARTICIPATION.md`](docs/phases/PHASE40_LLM_PARTICIPATION.md),
> `tests/benchmark_v2/llm_participation/`.
>
> **Phase 39:** dual-agent hardening — Discover (live federated
> search) evaluation, frontend usability, and agent-interface polish. Catalog
> counts reconciled to ground truth: **943,732 samples from 8 curated sources**
> (GEO, EGA, NCBI, EBI, CellxGene, PsychAD, HTAN, HCA) plus **6 federated
> databases** searchable live via Discover (GEO, SRA, EBI BioStudies, SCEA,
> CellxGene, HCA). **797 unit tests pass (+1 skip)**, ~46 API routes.
>
> Current: **🏁 publication-grade NL→SQL agent + redesigned portal — now FAST: model k2.6→turbo (advanced-search 180s timeout→~3–6s), DB on ext4 (explore 27.7s→0.4s, startup 240s→3s), full execution-trace panel + final SQL surfaced, leave-page state persistence, production-grade multi-format downloader (bash/aria2/Snakemake/Python) incl. external Discover datasets, workspace save verified**
> Next: Phase 34 — see [`docs/phases/PHASE34_BACKLOG.md`](docs/phases/PHASE34_BACKLOG.md): GEO/modality `assay` ETL annotation (D5/D6), tissue-standardisation fixes (D7: kidney `Glomerulus`→`neural glomerulus`), comparison-intent, age-range filters, hermetic `tests/unit`.
>
> Gold cr_target note: the **95.72%** below was the offline `kimi-k2.6` benchmark. The **live portal now runs `kimi-k2-turbo-preview`** (k2.6 timed out at 90–180s/query, unusable). Turbo-validated gold cr_target = **92.29%** [CI 84.68–97.20], honest-zero 100% — the best usable-model score (0905-preview = 88.60%, slower). The ~3 ppt gap is the price of a 2–6s usable portal vs an unusable one; the residual gap is the D5 GEO-assay-NULL ETL gap, not agent logic (Phase-33-verified).

**Repository**: [github.com/firefly-hefeng/SGDB_Agent](https://github.com/firefly-hefeng/SGDB_Agent)

---

## 1. Headline (Phase 24)

| Metric | Value | Status |
|---|---:|:---:|
| Real-scenarios v2 (30 researcher queries) | **30/30 (100 %)** | ✅ |
| Real-scenarios v3 hard (20 stress probes) | **20/20 (100 %)** | ✅ |
| RS v3 hard P0 | **7/7 (100 %)** | ✅ |
| RS v3 hard honest-zero | **2/2 (100 %)** | ✅ |
| RS v3 hard aggregation | **3/3 (100 %)** | ✅ |
| NL2SQL Gold v2 `cr_target` — rule mode | **94.76 %** [95 % CI 92.12, 96.97] | ✅ |
| NL2SQL Gold v2 `cr_target` — LLM (v1) mode | **95.72 %** [95 % CI 93.63, 97.66] | ✅ |
| NL2SQL Gold v2 `cr_full` useful (n=22) | **93.00 %** [95 % CI 89.59, 95.99] | ✅ |
| NL2SQL Gold v2 `cr_full_all` (29 questions) | **91.49 %** (up from 70.78 % Phase 22 baseline) | ✅ |
| Honest-zero rate (gold) | **100 %** (5/5) | ✅ |
| Gold reviewer-verified | **27/29** + 2 honest-zero | ✅ |
| Unit tests | **797 pass + 1 skipped** (current, as of Phase 39) | ✅ |
| Frontend tests (vitest) | **45 pass** (7 files; Phase 28 unchanged) | ✅ |
| Gold v3 candidates staged (pending biologist review) | **31** | 🟡 |
| Frontend build | ✅ vite clean — **225 kB main** + 49 kB vendor (charts lazy 387 kB) | ✅ |
| Frontend lint | ✅ 0 errors / 13 advisory warnings | ✅ |
| Frontend type-check | ✅ clean | ✅ |
| API server | ✅ ~46 routes loaded (incl. `/scdbAPI/discover/*`) | ✅ |
| Cross-DB discovery deployment | ✅ **in-process** (no iframe / second uvicorn) | ✅ |
| Audit Blockers closed | **6 / 6** (Phase 27) | ✅ |
| Curated catalog | **943,732 human single-cell samples from 8 sources** (GEO 342,328 · EGA 253,073 · NCBI 217,513 · EBI 94,255 · CellxGene 33,984 · PsychAD 1,494 · HTAN 942 · HCA 143); plus 6 federated databases searchable live via Discover | ✅ |

---

## 2. Quick navigation

| If you want to… | Read |
|---|---|
| Get the agent running in 5 minutes | [`QUICKSTART.md`](QUICKSTART.md) |
| Deploy to the homepage | [`docs/DEPLOYMENT_CHECKLIST.md`](docs/DEPLOYMENT_CHECKLIST.md) |
| Hand off to biologist annotators | [`docs/HUMAN_ANNOTATION_DELIVERABLES.md`](docs/HUMAN_ANNOTATION_DELIVERABLES.md) |
| Understand the architecture | [`README.md`](README.md) |
| See the latest phase report | [`docs/PHASE26_PROGRESS.md`](docs/PHASE26_PROGRESS.md) |
| Read about benchmark design | [`docs/BENCHMARK_V2_DESIGN.md`](docs/BENCHMARK_V2_DESIGN.md) |
| Browse the doc index | [`docs/README.md`](docs/README.md) |
| Explore history | [`docs/archive/`](docs/archive/) |

---

## 3. Architecture (Phase 20 final)

```
NL query  (EN / 中文 / mixed)
    ↓
QueryParser (rule)  +  V1QueryParser (LLM, optional)
    └── 19 entity types: tissue, disease, cell_type, sample_type, organism,
        assay, source, sex, temporal, threshold, asset, …
    └── Filters: positive / negation, strict_mode, treatment_present,
                  require_disease, h5ad_required, min_series_cells, …
    ↓
OntologyResolver (UBERON/MONDO/CL/EFO, 113 K terms, SQLite cache)
    ↓
ContextualSQLGenerator
    ├── Template (ID lookup, statistics)
    ├── Rule (indexed equality fast path, same-type entity OR, umbrella
    │         exclusion, dual cell-type column / table)
    └── LLM (complexity ≥ MODERATE; opt-in)
    ↓
ParallelSQLExecutor (asyncio + 30 s timeout + true COUNT(*))
    ↓
Self-correction (drop strict_mode → LLM rewrite → broaden suggestions)
    ↓
CrossDBFusionEngine (hash dedup + round-robin source interleave)
    ↓
AnswerSynthesizer (summary + charts + provenance + suggestions)
```

---

## 4. Phase trajectory

| Phase | Date | RS pass | NL2SQL cr_full | Key change |
|---|---|---:|---:|---|
| Phase 13 | 2026-05-06 | n/a | 56.97 % | Fusion UNION ALL + count_sql |
| Phase 17 | 2026-05-11 | 5/12 | 83.61 % | Parser r1: PBMC, target_level, multi-tissue OR |
| Phase 18 | 2026-05-11 | 7/12 | 84.20 % | Oracle audit + ontology cache fix |
| Phase 19 | 2026-05-11 | 11/12 (v1) / 24/30 (v2) | 84.58 % | Honest zero, GROUP BY total, parser refinements, 2 new evaluators |
| **Phase 20** | **2026-05-11** | **28/30 (v2 = 93 %)** | **~84.6 %** | Same-type OR, cell_type dual-path off, 10x platform, pancreatic islet, brain regions; release-ready |
| Phase 21 | 2026-05-12 | (no change) | (no change) | File inventory + doc reorganisation; archive 12 docs + 49 MB benchmark intermediates; rewrite README/QUICKSTART/PROJECT_STATUS |
| Phase 22 | 2026-05-12 | 30/30 (v2 = 100 %) | (no change) | api_routing_agent merged into extensions/; CD8/pancreatic islet engine fixes; facet_match per-record; two-agent deployment |
| **Phase 23** | **2026-05-13** | **30/30 (v2) + 20/20 (v3 hard)** | **89.04 % cr_target** | Eval correctness (zero/zero fix, honest_zero_rate, cr_target headline, target_oracle); 20-probe RS v3 hard stress suite; agent fixes for specific-disease routing, umbrella-negation, exclude_assays, source word-boundary, before-year semantics, target=series SQL, hierarchical-tissue LIKE |
| **Phase 24** | **2026-05-14** | **30/30 + 20/20 maintained** | **94.76 % cr_target** | Annotation-driven polish: applied 2 rejected oracle fixes (complex-multi-01/03); biologist accept bands wired into both RS runners; new histogram-oracle evaluator + 6 unit tests; aligned 4 RS v2 oracles with umbrella_terms_v1.yaml "broad" semantics. 27/29 gold reviewer-verified, 5/5 honest-zero |
| **Phase 25** | **2026-05-14** | **30/30 + 20/20 maintained** | **94.76 % rule / 93.67 % LLM** | Robust LLM JSON extractor (3-strategy fallback) + 4 lock-in tests (451 total). LLM-mode `cr_target` **89.04 → 93.67 %** (+4.63 ppt); GOLD-aggregation-05 LLM-only **17.6 → 83.5 %** (+65.9 ppt); LLM parse warnings collapse from many-per-Q to 2 total. 31 v3 gold candidates staged across 10 sub-types. Rule-mode cr_target & hist_composite identical to Phase 24. Phase 26: route LLM-mode aggregation to GROUP BY plan |
| **Phase 26** | **2026-05-14** | **30/30 + 20/20 maintained** | **94.76 % rule / 95.72 % LLM** | Discovered the bench uses V1QueryParser (different from QueryParser). Ported robust JSON to V1; surfaced umbrella `disease_categories`, `strict_mode`, `exclude_*`, and `aggregation` in the V1 prompt + `_convert_to_parsed_query`. **LLM mode now beats rule** (95.72 % vs 94.76 %). GOLD-negation-01: 61.8 → 97.6 % (+35.8 ppt); GOLD-strict-mode-04: 80.5 → 100 %; hist_composite in LLM mode 0 → 38.55 (matches rule). 463 unit tests (+12 V1 robustness/wiring lock-in). |
| **Phase 27** | **2026-05-14** | **30/30 + 20/20 maintained** | (no change) | Frontend redesign + in-process cross-DB discovery. Vendored `api-routing-agent v0.5.2` into `src/discovery/`; added `/scdbAPI/discover/{sources,health,search,stream}` (SSE). Replaced iframe `CrossApiLivePage` with native React `DiscoverPage`. Global manifest store (localStorage + curl / Python export). Calm design tokens (`#1B6FA8` accent, Inter / JetBrains Mono). Lazy routing — initial JS 435→225 kB (-48 %). Killed 7 dead Phase-1 components + native `prompt()` / `confirm()` everywhere. **All 6 audit Blockers closed.** 471 unit tests + 29 vitest tests. |
| **Phase 28** | **2026-05-16** | **30/30 + 20/20 maintained** | (no change) | **Biologist (hefeng) audit round 1 + 4 critical/high bug fixes + theme curation + repo rebrand.** Bugs: `discover_router` + `collections_router` were missing from `/singledb` mirror mount → Discover 405 + Featured collections silently empty. Data availability (H5AD/RDS/PMID/DOI) always 0 because `stats_overall` precompute pipeline never wrote those keys. Static-asset middleware skip-list matched `/assets` not the real `/singledb/assets` → page-load 429s. Themes: 6 → 8 with biologist audit (PDAC contradiction fixed, leukemia/solid-tumor clarified, developing-brain sample_type collapsed to canonical `fetal` only, COVID `sars` over-match removed, +kidney-atlas, +heart-cardiac). Rebrand to `firefly-hefeng/SGDB_Agent`. 492 unit tests (+11), 45 vitest. See [`docs/PHASE28_PROGRESS.md`](docs/PHASE28_PROGRESS.md). |
| **Phase 28 R2** | **2026-05-16** | **30/30 + 20/20 maintained** | (no change) | **lvtongxuan biologist audit on live DB + 4 more live bugs fixed.** Round 2 found: Data availability columns lived on the wrong table (`unified_series.asset_h5ad_url`, not `unified_projects`). `stats_by_year` SQL used non-existent `project_count` column. ALL `stats_by_*` precompute tables were empty in this DB build → added live-GROUP-BY-fallback. `developing-brain` theme returned 0 because canonical `sample_type='fetal'` doesn't exist in DB. Themes refined further: `tumor-immune` AND→OR, `heart-cardiac` `atri`→`atrium/atria`, `kidney-atlas` +`tubule`. **501 unit tests** (+9). See [`docs/PHASE28_QA_REPORT.md`](docs/PHASE28_QA_REPORT.md). |
| **Phase 28 R3** | **2026-05-16** | **30/30 + 20/20 maintained** | (no change) | **Agent quality + fuzz hardening.** R7: SQL fallback now relaxes `IN (?, ?, …)` clauses (not just `=`) — multi-entity ontology-expanded queries get the fuzzy second chance they always needed. R8: `docs/umbrella_terms_v1.yaml` (Phase 24 biologist curation, 51 entries) now actually loads into `OntologyResolver` at startup — was dead weight before. R9: `safe_fts5_query` sanitiser added to all 4 FTS5 MATCH call-sites — closes the 500 on punctuation-heavy `text_search`. R10: schema endpoint returns 404 not 500 for nonexistent table/column. **Endpoint fuzz: 39 cases × 0 × 5xx** (was 2 × 5xx in R2). **NL→SQL honest-zero rate on R2 baseline queries: 4/6 (67 %) → 1/6 (17 %)** — Q02 `pancreatic islet diabetes` 0 → 2,088, Q03 `CD8 T cell tumor` 0 → 185, Q04 `fetal brain` 0 → 31,048. **534 unit tests** (+33), 45 vitest. See [`docs/PHASE28_QA_REPORT_R3.md`](docs/PHASE28_QA_REPORT_R3.md). |
| **Phase 28 R4** | **2026-05-17** | **30/30 + 20/20 maintained** | (no change) | **Agent latency + table-routing + cancer-umbrella rescue + FTS5 cold-call fix.** R11 (Phase 28.F): five-layer per-instance cache on `OntologyResolver` hot paths (`lookup_exact`/`lookup_synonym`/`lookup_fuzzy`/`get_db_values`/`_direct_db_lookup`). Umbrella expansion with 24 children now reuses DB results across repeat resolves — second pass adds zero new misses. R16 (Phase 28.I): `JoinPathResolver` performs column-availability check; `target_level=series + tissue` now demotes to `v_sample_with_hierarchy` instead of emitting `WHERE tissue_standard=?` against `unified_series` (the column doesn't exist there). Q06 "heart single-cell atlas" SQL now valid. R12 (Phase 28.G): cancer umbrella was empty (all SQL fragments); now extracts the substring from `disease LIKE '%cancer%'` → 11 children → 24,816 samples. R17: `lookup_synonym` brute-force fallback was firing on every FTS5 miss (113K-row scan × 20 umbrella children = 100s cold cost); fix only falls through when FTS5 errors. **557 unit tests** (+23), 45 vitest. See [`docs/PHASE28_QA_REPORT_R4.md`](docs/PHASE28_QA_REPORT_R4.md). |
| **Phase 30** | **2026-05-17** | **30/30 + 20/20 maintained** | (no change) | **Service-quality polish: parser cache + cold-call UX + provenance badge + workspace post-save UX.** Phase 30.A: `CachingParser` wraps any LLM-backed parser; repeat NL queries hit cache in ~5ms (vs 30-60s LLM round-trip). LRU=256, TTL=1h, case-insensitive key, deep-copy on read. Phase 30.B: `NlProgress` chip walks user through agent's four phases (parsing → resolving → querying → fusing) with live elapsed counter — replaces the static spinner during 50-90s cold calls. aria-live polite. Phase 30.C: `ProvenanceBadge` in TopNav surfaces DB build date, sample/project counts, agent mode, ontology source counts; "Copy cite" button generates Methods-section snippet. Phase 30.D: post-save sticky banner in ManifestPanel with "Open workspace →" link. Phase 30.E: investigated Q5 "COVID-19 lung" — not a regression, R5's 154 is the correct AND-intersection (DB has 128 strict matches); R3's 4,210 was the agent over-broadly returning all COVID-19 samples. **567 unit tests** (+10), **56 vitest** (+11), build clean (+4 KB main). See [`docs/PHASE30_REPORT.md`](docs/PHASE30_REPORT.md). |
| **Phase 29** | **2026-05-17** | **30/30 + 20/20 maintained** | (no change) | **Cleaned-DB roll-in + system-wide audit + manifest⇄workspace bridge + scientific-integrity hardening.** Replaced `human_metadata.db` with v2-cleaned build (1.6 GB, dated 2026-05-17). NEW DB has 17 added standardized columns (`age_unit_normalized`, `tissue_standard_l1/leaf`, `disease_standard_l1`, `cell_type_lineage`, `ancestry_category`, …). Schema-aware code paths unchanged via four `unified_*` view aliases + wide `v_sample_with_hierarchy` rebuild. **B29-1 (CRITICAL)**: precomputed `stats_overall` was 70 % inflated (claimed 1,009,652 samples; live count 943,732). `scripts/rebuild_stats.py` regenerates all 8 `stats_*` tables from live aggregates. **B29-2**: `stats_by_year` stored `'Sep '`, `'Oct '` (month abbreviations) — now 17 year buckets 2001 → 2024. **B29-3**: stats_by_organism/sex stale by 5+ weeks — rebuilt. **B29-4**: 141K samples displayed bare age numbers (no unit) because `v_sample_with_hierarchy.age_unit` skipped the `age_unit_normalized` column — view rebuilt with COALESCE → unit shown for 139,665 of 161,081 samples-with-age. **B29-5**: new `GET /scdbAPI/version` exposes app/DB/ontology provenance. **B29-6**: `ManifestPanel` now has "Save to workspace" picker — closes the longstanding manifest⇄workspace UX gap from Round 1+2. **B29-7**: LandingPage's hardcoded "15 sources" replaced with live count. **557 unit tests** (no regressions), 45 vitest, build clean. Live audit (6/15 NL queries confirmed: Q1-Q6 OK including cancer 3,662 and CD8 T cell tumor 37,420; Q7 timed out at client at 180s but server returned 222s). See [`docs/PHASE29_AUDIT_REPORT.md`](docs/PHASE29_AUDIT_REPORT.md). |

Earlier phases (1-16) live in [`docs/archive/`](docs/archive/).

---

## 5. Repository layout

```
agent_v3/
├── src/                  Core agent code (parser, ontology, sql, fusion, synth, memory)
├── api/                  FastAPI routes (73 endpoints) + Pydantic schemas
├── web/                  React + Vite frontend
├── tests/
│   ├── unit/             441 unit tests
│   └── benchmark_v2/     gold + real-scenarios + 12 evaluators + peer-compare
├── data/                 Memory + ontology + schema YAML
├── config/               config.yaml + v3.json
├── scripts/              install_human_db.py
├── docs/                 Active design + phase reports
│   └── archive/          Phases 1-16 + obsolete docs
├── README.md             Project overview
├── QUICKSTART.md         5-minute launch guide
├── PROJECT_STATUS.md     This file
├── run_server.py         Server launcher
└── pyproject.toml
```

---

## 6. What's next

### 6.1 Immediate

1. **Real-user testing** — agent quality is now > publication-grade
   (rule 94.76 %, LLM 95.72 %, 100 % on both real-scenario suites). Hand
   `docs/HUMAN_ANNOTATION_DELIVERABLES.md` to ≥3 biologists.
2. **Biologist review of 31 v3 gold candidates** —
   `tests/benchmark_v2/ground_truth/nl2sql_gold_v3_candidates.json`.
   Once verified, useful question count rises 22 → ~53 (≈2.4×) and
   confidence intervals tighten.
3. **Deploy** — follow `docs/DEPLOYMENT_CHECKLIST.md`.

### 6.2 Phase 27 candidate work (deferred until real-user data)

| Item | Why deferred |
|---|---|
| Histogram per-bucket tolerance (currently 22.15 %) | Universe sum is correct; per-bucket drift may not matter to users |
| Port umbrella/strict/negation prompt to `--parser-mode reasoning / auto` | Only matters if those modes get production traffic |
| Peer-tool comparison full run (Vanna / DIN-SQL) | Wait until v3 gold finalised |
| Architecture diagram + Phase 13 → 26 ablation summary | Paper-draft activity |

---

## 7. Reproducibility

```bash
# Unit tests (10 s)
python3 -m pytest tests/unit/ -q

# Real-scenarios v2 (5 min)
python3 -m tests.benchmark_v2.real_scenarios.run_scenarios_v2

# NL2SQL Gold v2 (11 min, rule mode)
python3 -m tests.benchmark_v2.run_nl2sql_v2 --parser-mode rule \
    --out tests/benchmark_v2/results/your_run
```

Latest result files:
- `tests/benchmark_v2/real_scenarios/results_v2.json` (30/30)
- `tests/benchmark_v2/real_scenarios/results_v3_hard.json` (20/20)
- `tests/benchmark_v2/results/phase26/gold_v1_llm_v2.json` — LLM-mode headline (95.72 %)
- `tests/benchmark_v2/results/phase25/gold_rule.json` — rule-mode headline (94.76 %)
- Earlier benchmark history: `tests/benchmark_v2/results/archive/` (tgz snapshots + Phase 13-23 JSONs)

DB snapshot fingerprint: `f88b2025eda755b1` (content hash; all evals pin to it). Bootstrap seed: `42`.

---

## 8. Document index

See [`docs/README.md`](docs/README.md) for the full categorised index.
After the Phase 26 archival pass, only the latest three phase reports
plus evergreen docs sit at the top of `docs/`:

| File | Purpose |
|---|---|
| `PHASE30_REPORT.md` | **Latest.** Parser cache + cold-call progress chip + provenance badge + workspace post-save UX, 2026-05-17 |
| `PHASE29_AUDIT_REPORT.md` | v2-cleaned DB roll-in + cross-view integrity audit + manifest⇄workspace bridge + /version endpoint + 7 fixes, 2026-05-17 |
| `PHASE28_QA_REPORT_R4.md` | Agent latency (R11 / Phase 28.F) + table routing (R16 / Phase 28.I) + cancer-umbrella rescue (R12 / Phase 28.G) + FTS5 cold-call fix (R17), 2026-05-17 |
| `PHASE28_QA_REPORT_R3.md` | Agent quality (R7+R8) + fuzz hardening (R9+R10), 2026-05-16 |
| `PHASE28_QA_REPORT.md` | Round 2 — biologist audit live + 4 more bug fixes, 2026-05-16 |
| `PHASE28_PROGRESS.md` | Phase 28 initial: 4 critical bugs + theme curation + repo rebrand (2026-05-16) |
| `PHASE27_PROGRESS.md` | Frontend redesign + in-process discovery |
| `design/PHASE27_FRONTEND_REDESIGN_PLAN.md` | Phase 27 design plan |
| `design/PORTAL_UX_RESEARCH.md` | 14-portal UX research that drove the redesign |
| `design/FRONTEND_AUDIT.md` | Frontend bug / quality punch list |
| `PHASE26_PROGRESS.md` | LLM-mode quality closure (95.72 %) |
| `PHASE25_PROGRESS.md` | Robust LLM JSON extractor + 31 v3 candidates |
| `PHASE24_FINAL_REPORT.md` | Annotation-driven polish |
| `BENCHMARK_V2_DESIGN.md` | Bench v2 design spec |
| `BENCHMARK_V2_CHANGELOG.md` | Bench v2 iteration log Phase 10-13 |
| `DEPLOYMENT_CHECKLIST.md` | Deployment + integration |
| `HUMAN_ANNOTATION_DELIVERABLES.md` | Biologist task checklist |
| `ANNOTATION_REQUIREMENTS.md` | Annotation theory / rationale |
| `umbrella_terms_v1.yaml` | Biologist-curated umbrella semantics (live config) |
| `THESIS_PROGRESS.md` | Publication tracking |

Historical reports (Phase 17 → 23) live in
[`docs/archive/phase17-23_reports/`](docs/archive/phase17-23_reports/);
older archives (`phases_1-5/`, `phase11-15_sessions/`,
`phase14-16_reports/`, `legacy_dirs/`, `old_design/`) sit alongside it.
