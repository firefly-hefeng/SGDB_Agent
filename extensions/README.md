# extensions/

Side-car agents that historically ran alongside the main SCeQTL-Agent V3
as separate processes, integrated only at the HTTP layer.

## Current inventory

| Subfolder | Status |
|---|---|
| _empty_ | (no active extensions) |

## History

The cross-database discovery agent (formerly `api_routing_agent`) was
**integrated into the main agent** in Phase 27 (2026-05-14). Its code now
lives at `src/discovery/` as a first-class sub-package and its endpoints
are mounted at `/scdbAPI/discover/*` by the main FastAPI app. The old
side-car copy has been archived to
`docs/archive/extensions_v1/api_routing_agent/` for reference.

If you need to add a new side-car (something that genuinely cannot be
embedded — for example because of incompatible Python deps or because it
runs a different language), place it here, each with its own
`pyproject.toml`, `requirements*.txt`, Dockerfile, `data/`, `prompts/`,
and `tests/`. The host frontend must integrate via a reverse-proxy
route, not via an iframe.
