# SCGB - Single Cell Gene Expression Metadata Platform

<p align="center">
  <strong>AI-Powered Unified Metadata Query Platform for Human Single-Cell Genomics</strong>
</p>

<p align="center">
  <a href="#overview">Overview</a> •
  <a href="#key-features">Features</a> •
  <a href="#architecture">Architecture</a> •
  <a href="#quick-start">Quick Start</a> •
  <a href="#project-structure">Structure</a> •
  <a href="#documentation">Documentation</a>
</p>

---

## Overview

SCGB (Single Cell Gene Bank) is a unified metadata platform that integrates human single-cell gene expression data from 12 major databases worldwide, including GEO, NCBI/SRA, EBI/ENA, CellXGene, HCA, HTAN, PsychAD, and more. The platform provides:

- **Unified Metadata Database**: 756,579 samples from 23,123 projects across 12 data sources
- **AI Agent System**: Natural language query interface with intelligent retrieval
- **Web Portal**: Modern React-based interface for data exploration
- **Cross-database Linking**: 9,966 cross-references (PRJNA↔GSE, PMID, DOI)
- **Ontology Support**: 113,000+ terms from UBERON, MONDO, CL, and EFO

## Key Features

| Feature | Description |
|---------|-------------|
| **Multi-source Integration** | Unified schema across GEO, NCBI/SRA, EBI, CellXGene, HCA, HTAN, PsychAD |
| **AI-Powered Search** | Natural language to SQL with LLM-powered query understanding |
| **Ontology Resolution** | Automatic cell type, tissue, and disease normalization using Cell Ontology |
| **Faceted Exploration** | Filter by organism, tissue, disease, technology, and more |
| **Real-time WebSocket** | Live query results with streaming support |
| **Data Quality Scoring** | Automated quality assessment for all datasets |

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Web Frontend                              │
│  (React + TypeScript + Vite + Tailwind CSS + Recharts)          │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     FastAPI Backend                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐ │
│  │   Query API │  │ Explore API │  │    WebSocket API        │ │
│  └─────────────┘  └─────────────┘  └─────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Agent Core System                             │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────────┐  │
│  │Understanding│ │ Memory   │ │ Ontology │ │ SQL Generation   │  │
│  │  Layer    │ │ System   │ │ Resolver │ │   Engine         │  │
│  └──────────┘ └──────────┘ └──────────┘ └──────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Unified Database                              │
│         (SQLite with FTS5 Full-Text Search)                     │
└─────────────────────────────────────────────────────────────────┘
```

## Quick Start

### Prerequisites

- Python 3.10+
- Node.js 18+
- SQLite 3.35+

### Installation

```bash
# Clone the repository
git clone https://github.com/firefly-hefeng/SGDB_Agent.git
cd SGDB_Agent

# Install Python dependencies
cd agent_v2
pip install -e ".[dev]"

# Install frontend dependencies
cd web
npm install
npm run build
cd ..

# Run database migrations (if needed)
# See database_development/unified_db/README.md
```

### Running the Application

```bash
# Start the backend server
cd agent_v2
python3 run_server.py --port 8000

# Access the web interface
# Open http://localhost:8000 in your browser
```

### Direct Database Query

```bash
cd database_development/unified_db

sqlite3 unified_metadata.db \
  "SELECT sample_id, tissue, disease, source_database
   FROM unified_samples
   WHERE tissue LIKE '%brain%' AND disease LIKE '%Alzheimer%'
   LIMIT 10;"
```

## Project Structure

```
SGDB_Agent/
│
├── README.md                          # This file
├── PROJECT_STATUS.md                  # Comprehensive project status
├── .gitignore                         # Git ignore rules
│
├── agent_v2/                          # Main Agent + Web Application
│   ├── src/                           # Python core modules (11 modules)
│   │   ├── agent/                     # Multi-agent coordinator
│   │   ├── understanding/             # Query parsing & enrichment
│   │   ├── memory/                    # Working/episodic/semantic/cache
│   │   ├── ontology/                  # Cell Ontology parser/resolver
│   │   ├── knowledge/                 # Schema knowledge base
│   │   ├── sql/                       # SQL generation engine
│   │   ├── fusion/                    # Cross-source data fusion
│   │   ├── synthesis/                 # Answer generation
│   │   ├── dal/                       # Data access layer
│   │   ├── infra/                     # LLM client & cost control
│   │   └── core/                      # Models & exceptions
│   ├── api/                           # FastAPI routes (15 endpoints)
│   ├── web/                           # React frontend (6 pages)
│   ├── tests/                         # Test suite (134 unit + e2e)
│   └── scripts/                       # Utility scripts
│
├── database_development/              # Unified Database
│   ├── unified_db/                    # SQLite DB + ETL pipelines
│   │   ├── schema.sql                 # Database schema
│   │   ├── etl/                       # ETL modules for each source
│   │   └── linker/                    # ID linking & deduplication
│   └── export_data/                   # Export & meta-analysis tools
│
├── agent_v2_design/                   # Design Documentation
│   ├── ARCHITECTURE.md                # System architecture
│   ├── MODULE_DETAIL_PART*.md         # Module detailed design
│   └── *_REVIEW_REPORT.md             # Performance & UX reviews
│
├── agent_analysis/                    # Agent Analysis Documents
├── agent_development/                 # V1 Implementation (legacy)
│
├── cellxgene/                         # CellXGene data collector
├── ebi/                               # EBI/ENA data collector
├── geo/                               # GEO data collector
├── biscp/                             # BISCP data collector
├── ncbi_bioproject_sra_data/          # NCBI data collector
│
├── scgb_deploy/                       # Production Deployment
│   ├── backend/                       # Production backend
│   ├── frontend/                      # Compiled frontend assets
│   └── config/                        # Nginx & systemd configs
│
└── review_report/                     # Code review reports
```

## Data Sources

| Source | Projects | Samples | ID Prefix | Quality |
|--------|----------|---------|-----------|---------|
| **GEO** | 5,406 | 342,368 | GSE*, GSM* | Medium |
| **NCBI/SRA** | 8,156 | 217,513 | PRJNA*, SRS* | Medium |
| **EBI** | 1,019 | 160,135 | E-MTAB*, SAMEA* | Medium |
| **CellXGene** | 269 | 33,984 | UUID | High |
| **PsychAD** | — | 1,494 | — | Good |
| **HTAN** | — | 942 | — | Medium |
| **HCA** | — | 143 | — | Excellent |
| **Total** | **23,123** | **756,579** | | |

## Documentation

| Document | Description |
|----------|-------------|
| [PROJECT_STATUS.md](PROJECT_STATUS.md) | **Complete project status and development history** |
| [agent_v2/README.md](agent_v2/README.md) | Agent technical documentation (architecture/API/tests) |
| [database_development/unified_db/README.md](database_development/unified_db/README.md) | Database usage guide |
| [database_development/01_ARCHITECTURE_DESIGN.md](database_development/01_ARCHITECTURE_DESIGN.md) | System architecture design |
| [database_development/02_DATABASE_SCHEMA.md](database_development/02_DATABASE_SCHEMA.md) | Database schema design |
| [agent_v2_design/ARCHITECTURE.md](agent_v2_design/ARCHITECTURE.md) | V2 architecture specification |
| [DEPLOY_CHANGES_NJU.md](DEPLOY_CHANGES_NJU.md) | Deployment guide for NJU server |
| [OPTIMIZATION_GUIDE.md](OPTIMIZATION_GUIDE.md) | Performance optimization guide |

## Testing

```bash
cd agent_v2

# Run unit tests
python3 -m pytest tests/unit/ -v

# Run integration tests
python3 tests/test_phase1_e2e.py
python3 tests/test_phase2_e2e.py

# Run benchmark
python3 tests/benchmark/run_benchmark.py
```

## Performance Metrics

- **Query Response Time**: < 2s for faceted search
- **NL2SQL Accuracy**: 92.2% (142/154 test cases)
- **Unit Test Coverage**: 134/134 tests passing
- **Ontology Resolution**: 85% cell type coverage

## Deployment

For production deployment instructions, see:
- [DEPLOY_CHANGES_NJU.md](DEPLOY_CHANGES_NJU.md) - NJU server deployment
- [scgb_deploy/README.md](scgb_deploy/README.md) - Production setup

## Contributing

This project is maintained by the Single Cell Genomics team. For questions or contributions, please contact:

- **Author**: firefly-hefeng
- **Email**: fenghe13254@gmail.com

## License

This project is for research purposes. Please cite appropriately when using the data or code.

---

<p align="center">
  <sub>Built with ❤️ for the single-cell genomics community</sub>
</p>
