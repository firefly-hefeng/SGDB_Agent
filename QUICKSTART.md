# SCeQTL Portal — Quickstart (5 minutes)

> Goal: get the agent running locally and send your first NL query.
> For deployment / homepage integration see [`docs/DEPLOYMENT_CHECKLIST.md`](docs/DEPLOYMENT_CHECKLIST.md).

## 1. Prerequisites

- Python 3.10+
- Node.js 18+ (for frontend build)
- ~3 GB free disk (DB is ~1.9 GB)
- The unified metadata DB at `../database_development/unified_db/human_metadata.db`
  (fingerprint `1d509b0b42ebafb8`)

## 2. Install

```bash
cd /path/to/agent_v3
pip install -e ".[dev]"
```

## 3. (Optional) configure LLM

Rule mode works out of the box. For LLM-augmented reasoning mode:

```bash
cp .env.example .env
# Edit .env, set KIMI_API_KEY=sk-...
```

> **Performance setup (Phase 33+).** Two settings make the difference between an
> unusable and a snappy portal — both already wired in `.env`:
> 1. **Model**: the default is `KIMI_MODEL=kimi-k2.6` (the earlier
>    `kimi-k2-turbo-preview` is retired). `SCEQTL_PARSER_MODE` defaults to `v1`
>    (fast + highest gold score).
> 2. **Database location**: SQLite on a Windows-mounted path (`/mnt/d/…` under
>    WSL) is ~500× slower than Linux-native ext4. Copy the DB to ext4 and point
>    `SCEQTL_DB_PATH` at it:
>    ```bash
>    mkdir -p ~/sceqtl_db && cp ../database_development/unified_db/human_metadata.db ~/sceqtl_db/
>    echo 'SCEQTL_DB_PATH=$HOME/sceqtl_db/human_metadata.db' >> .env   # expand $HOME yourself
>    ```
>    Effect: startup 240 s → 3 s; unfiltered Explore 27 s → 0.4 s; advanced
>    search 180 s-timeout → 2–6 s. Re-copy if the source ETL DB changes.
>
> Frontend dev under WSL: run vite with `CHOKIDAR_USEPOLLING=1` (drvfs has no
> inotify) and only one instance bound to :5173.

## 4. Build frontend (one-time)

```bash
cd web && npm install && npm run build && cd ..
```

Output: `web/dist/` (~870 kB total, gzipped). FastAPI serves it at `/`.

## 5. Launch

```bash
python3 run_server.py --host 0.0.0.0 --port 8000
```

Verify:

```bash
curl http://localhost:8000/scdbAPI/health
# {"status": "healthy", "components": {"database": ..., "agent": ...,
#  "ontology": ..., "memory": ..., "discovery": ...}}
```

Open `http://localhost:8000/` in a browser.

## 6. First NL queries to try

These exercise different agent paths. Each should return non-zero results
and a NL summary.

```
All bone marrow leukemia samples from human.
Brain samples studying Alzheimer.
T cell samples from blood, no PBMC.
Show me all CellXGene PBMC datasets with at least 10,000 cells.  ← expect 0 + suggestions
Show how many samples we have per disease_category in liver.
Find single-cell datasets of pancreatic cancer.
Datasets that have h5ad files available.
Group cell types by count in Alzheimer samples.
```

For **live cross-database discovery**, open `/discover` in the UI or:

```bash
curl -N -X POST http://localhost:8000/scdbAPI/discover/stream \
  -H 'Content-Type: application/json' \
  -d '{"query":"Alzheimer hippocampus scRNA-seq"}'
```

The stream yields SSE events: `intent`, then one `source_complete`
per adapter (GEO / SRA / EBI / SCEA / CellxGene / HCA), then `mirrors`,
then an optional `synth`, then `done`.

## 7. Run tests

```bash
# Unit tests (~10 s, 797 should pass + 1 skip)
python3 -m pytest tests/unit/ -q

# Real-scenario regression (30 queries, ~5 min, 28 should pass)
python3 -m tests.benchmark_v2.real_scenarios.run_scenarios_v2
```

## 8. What's next

- **For deployment**: read [`docs/DEPLOYMENT_CHECKLIST.md`](docs/DEPLOYMENT_CHECKLIST.md)
- **For biologist testing**: read [`docs/HUMAN_ANNOTATION_DELIVERABLES.md`](docs/HUMAN_ANNOTATION_DELIVERABLES.md)
- **For full architecture**: read [`README.md`](README.md) + [`docs/PHASE26_PROGRESS.md`](docs/PHASE26_PROGRESS.md)

## 9. Troubleshooting

| Symptom | Fix |
|---|---|
| `DatabaseAbstractionLayer FileNotFoundError` | Set `SCDB_DB_PATH` env var or symlink the DB into `../database_development/unified_db/` |
| `KIMI_API_KEY not set` warning | Harmless — rule mode keeps working. Set the key only if you want reasoning mode. |
| `npm run build` fails | Delete `web/node_modules` and re-run `npm install`. Node 18+ required. |
| Unit tests hang | WSL-mounted Windows filesystem may be slow on cold cache. Wait 30 s or re-run. |
| Real-scenarios returns timeouts | Bump `--timeout` in `run_scenarios_v2.py` (default 180 s per query); cold DB cache. |

## 10. Layout (5-second overview)

- Code: `src/`, `api/`, `web/src/`
- Tests: `tests/unit/`, `tests/benchmark_v2/`
- Docs: `docs/` (active), `docs/archive/` (history)
- Data: `data/`, `../database_development/unified_db/`
- Launch: `run_server.py`
