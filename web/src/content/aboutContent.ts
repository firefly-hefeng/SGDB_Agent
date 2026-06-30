// AUTO-ASSEMBLED from the Singligent thesis (chapters distilled by an agent pass).
// Bilingual content for the About documentation sections; figures in /public/about/.

export interface Bi { en: string; zh: string }
export interface AboutSection {
  key: string;
  icon: string;
  title: Bi;
  lede: Bi;
  points: Bi[];
  figure: string | null;
  figureExtra: string | null;
  caption: Bi;
}

export const ABOUT_SECTIONS: AboutSection[] = [
  {
    "key": "architecture",
    "icon": "Layers",
    "title": {
      "en": "System architecture",
      "zh": "系统总体架构"
    },
    "lede": {
      "en": "Singligent is a dual-agent system built in five horizontal layers — Application, Agent, Service, Storage, and Data-source — with clean interfaces between them and a single responsibility within each. Everything starts from one natural-language query (English or 中文) and flows through a Discover → Select → Acquire pipeline: find candidate datasets, refine and pin them across pages, then export a ready-to-run download script.",
      "zh": "Singligent 是一套双智能体系统，按应用层、Agent 层、服务层、存储层、数据源层五个水平层组织，层间以明确接口对接、层内单一职责。一切始于一句中英文自然语言查询，沿\"发现 → 选择 → 获取\"全链路推进：先找到候选数据集，再跨页面精筛并固定，最终一键导出可执行的下载脚本。"
    },
    "points": [
      {
        "en": "Application layer: four entry points — Web UI, REST API (FastAPI/OpenAPI), WebSocket, Python SDK — plus the download manager.",
        "zh": "应用层：Web UI、REST API（FastAPI 自动生成 OpenAPI）、WebSocket、Python SDK 四种入口，外加智能下载管理器。"
      },
      {
        "en": "Agent layer: two peer agents run side by side — the NL→SQL agent (Explore) and the api-routing agent (Discover) — switchable or combined.",
        "zh": "Agent 层：NL→SQL 智能体（Explore）与 api-routing 智能体（Discover）对等并联，可一键切换或同时启用。"
      },
      {
        "en": "Service layer: shared dependencies — a 103 MB FTS5 ontology cache, a Schema Inspector, and a SQLite connection/WAL abstraction.",
        "zh": "服务层：两 Agent 共享依赖——约 103 MB FTS5 本体缓存、Schema Inspector、屏蔽连接池与 WAL 的数据访问抽象层。"
      },
      {
        "en": "Storage layer: the harmonized human_metadata.db (~1.6 GB, 8 main + 5 auxiliary tables), plus ontology and memory databases.",
        "zh": "存储层：统一库 human_metadata.db（约 1.6 GB，8 主表 + 5 辅助表），以及本体缓存与记忆数据库。"
      },
      {
        "en": "Data-source layer: 8+ sources flow in via offline ETL adapters, while Discover keeps a runtime channel for live federated queries.",
        "zh": "数据源层：8 个以上数据源经离线 ETL 适配器入库，同时保留 Discover 的运行时直调通道服务实时查询。"
      },
      {
        "en": "Engineering choices: a local harmonized catalog for fast, controllable depth; live federation for breadth; SSE/WebSocket streaming and caching throughout.",
        "zh": "工程取舍：本地统一目录保证深度查询的性能与可控，实时联邦保证广度，全程辅以 SSE/WebSocket 流式输出与缓存。"
      }
    ],
    "figure": "arch_system.png",
    "figureExtra": "arch_pipeline.png",
    "caption": {
      "en": "Five-layer architecture — Application, Agent, Service, Storage, and Data-source — with the two agents as peers and the downloader as a first-class component; solid lines show runtime data flow, dashed lines offline ETL and runtime APIs.",
      "zh": "五层架构——应用、Agent、服务、存储、数据源——双 Agent 对等并存，下载器作为一等公民；实线为运行期数据流，虚线为离线 ETL 与运行时 API。"
    }
  },
  {
    "key": "data",
    "icon": "Database",
    "title": {
      "en": "Curated Metadata & Data Engineering",
      "zh": "元数据策展与数据工程"
    },
    "lede": {
      "en": "The catalog behind Explore is built, not scraped. We ingest human scRNA-seq metadata from eight curated and several federated archives, then run a five-stage pipeline — collect, normalize, ontology-map, deduplicate, index — to produce one harmonized store: 943,732 samples across 16,376 projects, 378,029 cell-type annotations, ontology-aligned and queryable in milliseconds.",
      "zh": "Explore 背后的元数据库是工程化构建的，而非简单抓取。我们从八个精选主库与若干联邦档案系统采集人源 scRNA-seq 元数据，经\"采集→归一化→本体映射→去重→索引\"五阶段流水线，整理为一份协调统一的数据资产：覆盖 16,376 个项目、943,732 个样本、378,029 条细胞类型注释，全程本体对齐，毫秒级可查。"
    },
    "points": [
      {
        "en": "Sources: GEO, SRA, EBI BioStudies/SCEA, CellXGene, HCA, EGA, plus PsychAD/HTAN atlases and Zenodo-class repositories — four major archives supply ~96% of samples.",
        "zh": "数据源：GEO、SRA、EBI BioStudies/SCEA、CellXGene、HCA、EGA，以及 PsychAD/HTAN 等专项图谱与 Zenodo 类通用仓库——四大主库贡献约 96% 样本。"
      },
      {
        "en": "Schema: a four-tier ER model — project → series → sample → cell-type — across eight core tables, the million-row sample table carrying 14 ontology-aligned _standard fields.",
        "zh": "Schema：项目→系列→样本→细胞类型的四级 ER 模型，共八张核心表；百万行样本表含 14 个本体对齐的 _standard 标准化字段。"
      },
      {
        "en": "Five-stage ETL: import + species/technique filtering, cross-archive hard-linking, iterative ontology normalization, ten targeted cleaning rounds, then quality gating and service-layer views.",
        "zh": "五阶段 ETL：导入与物种/技术过滤、跨库硬链接、迭代收敛的本体标准化、十轮专项清洗，再到质量门控与服务化视图层。"
      },
      {
        "en": "Ontology alignment: 113,000+ UBERON/CL/MONDO/EFO terms in a full-text cache, ~6,000 hand-curated term-to-variant mappings, via a five-step cascade matcher.",
        "zh": "本体对齐：UBERON/CL/MONDO/EFO 共 11.3 万+ 术语进入全文索引缓存，约 6,000 条人工策展的术语→变体映射，由五步级联匹配器驱动。"
      },
      {
        "en": "Deduplication: shared-identifier hard links (PRJNA↔GSE, PMID, DOI) — 19,513 evidence-tagged entity links, after a hash-based heuristic was rejected at 86% collision.",
        "zh": "去重：基于共享外部标识的硬链接（PRJNA↔GSE、PMID、DOI）——19,513 条带证据的实体链接；早期哈希启发式方案因 86% 碰撞率被弃用。"
      },
      {
        "en": "Coverage & speed: 100% base-ID fill, disease lifted to 56.9% by ontology matching; 43 indexes, FTS5 and 9 precomputed tables cut dashboard loads from ~90s to ~5ms.",
        "zh": "覆盖与性能：基础标识 100% 填充，疾病字段经本体匹配提升至 56.9%；43 个索引、FTS5 与 9 张预计算表将仪表盘加载从约 90 秒压至约 5 毫秒。"
      }
    ],
    "figure": "data_schema.png",
    "figureExtra": "data_etl.png",
    "caption": {
      "en": "Four-tier ER schema (project → series → sample → cell-type) and the five-stage ETL pipeline from raw source records to the harmonized, ontology-aligned catalog.",
      "zh": "四级 ER schema（项目→系列→样本→细胞类型）与五阶段 ETL 流水线：从源原生记录到协调统一、本体对齐的元数据库。"
    }
  },
  {
    "key": "nlsql",
    "icon": "SearchCode",
    "title": {
      "en": "The NL→SQL Agent (Explore / Advanced)",
      "zh": "自然语言转 SQL 智能体（Explore / 高级检索）"
    },
    "lede": {
      "en": "Ask in plain English or 中文 — Explore turns your question into validated SQL over the curated catalog of 943,732 harmonized human scRNA-seq samples, then returns datasets, facets, and an auditable answer.",
      "zh": "用中文或英文一句话提问，Explore 即可将其翻译为可执行 SQL，在 943,732 条规范化人源单细胞样本的统一目录上检索，返回数据集、多维分面与可审查的应答。"
    },
    "points": [
      {
        "en": "Query understanding: parses intent (search / count / browse / download) plus 19 entity types and 7 filter modifiers into a structured ParsedQuery.",
        "zh": "查询理解：解析意图（检索 / 统计 / 浏览 / 下载）及 19 类生物医学实体、7 类过滤修饰符，产出结构化 ParsedQuery。"
      },
      {
        "en": "Rule-first with LLM fallback and query caching: ~85% of queries hit fast rules; hot queries drop from a 30–60s round-trip to ~5ms.",
        "zh": "规则为主、LLM 兜底、缓存外置：约 85% 查询命中快路径；热门查询从 30–60 秒往返压缩至约 5 毫秒。"
      },
      {
        "en": "Ontology-aware expansion: a five-step pipeline over 113,461 UBERON/MONDO/CL/EFO terms maps 'AD'→Alzheimer disease and 'brain'→its subregions.",
        "zh": "本体感知扩展：基于 113,461 条 UBERON/MONDO/CL/EFO 术语的五步解析，将 'AD' 对齐至阿尔茨海默病、'brain' 下展至各脑区。"
      },
      {
        "en": "Recall rescue via 51 curated umbrella terms: 'fetal brain' goes from 0 to 31,048 samples; 'pancreatic islet diabetes' from 0 to 2,088.",
        "zh": "伞形扩展挽救召回（51 个人工 curate 词条）：'fetal brain' 从 0 扩到 31,048 个样本，'pancreatic islet diabetes' 从 0 扩到 2,088 个。"
      },
      {
        "en": "Three-candidate SQL generation (template / rule / LLM): most queries return under 100ms, with a three-step self-repair loop on zero results.",
        "zh": "三候选并行 SQL 生成（模板 / 规则 / LLM）：多数查询 100 毫秒内返回；零结果时进入三步自纠错回路，绝不陷入无限重写。"
      },
      {
        "en": "Execution with multi-facet results and bilingual EN/中文 support throughout — same ParsedQuery contract regardless of parsing source.",
        "zh": "执行返回多维分面结果，全流程支持中英双语；无论解析来自规则或 LLM，下游均共享同一 ParsedQuery 契约。"
      }
    ],
    "figure": "nlsql_pipeline.png",
    "figureExtra": "nlsql_ontology.png",
    "caption": {
      "en": "The NL→SQL pipeline: query understanding → ontology expansion → multi-candidate SQL generation → validated execution → faceted, auditable answer.",
      "zh": "自然语言转 SQL 流水线：查询理解 → 本体扩展 → 多候选 SQL 生成 → 校验执行 → 多分面、可审查的应答。"
    }
  },
  {
    "key": "apirouting",
    "icon": "Radio",
    "title": {
      "en": "Discover — the api-routing agent",
      "zh": "Discover —— API 路由智能体"
    },
    "lede": {
      "en": "One query, fired live and in parallel across six federated public archives — GEO, SRA, EBI BioStudies, EBI SCEA, CellXGene, and HCA. Discover extends Explore beyond the curated human catalog to other species, other omics (scATAC-seq, spatial, multimodal), and the very newest releases. A four-stage pipeline — intent parsing, concurrent adapter dispatch, cross-source fusion with mirror detection, then synthesis — replaces hours of per-archive manual search with a single, unified view.",
      "zh": "一次输入，实时并发命中六个联邦公共档案库 —— GEO、SRA、EBI BioStudies、EBI SCEA、CellXGene 与 HCA。Discover 将 Explore 的视野从人源精选目录扩展到其他物种、其他组学（scATAC-seq、空间转录组、多模态）以及最新发布。意图解析 → 并发分发 → 跨源融合与镜像识别 → 答案合成的四阶段流水线，把过去逐库手检的数小时压缩为一次统一视角的检索。"
    },
    "points": [
      {
        "en": "Intent parsing structures each query into eight fields — disease, tissue, tech, species, keywords, time, negative terms, source restriction.",
        "zh": "意图解析将每次查询拆为八个字段：疾病、组织、技术、物种、关键词、时间、否定词与源限制。"
      },
      {
        "en": "Per-archive adapters translate one intent into each API's native syntax — GEO Title/Abstract predicates, HCA Azul filters, CellXGene ontology fields.",
        "zh": "各源适配器将同一意图翻译为各 API 原生语法：GEO 的 Title/Abstract 谓词、HCA Azul 过滤、CellXGene 本体字段。"
      },
      {
        "en": "Concurrent dispatch via asyncio.gather with per-adapter timeouts, retries, and rate-limit semaphores; results stream back live over SSE.",
        "zh": "基于 asyncio.gather 的并发分发，每适配器独立超时、重试与限速信号量；结果经 SSE 实时逐源回推。"
      },
      {
        "en": "Bilingual input via three-layer fallback — Simplified, then Traditional Chinese term mapping, then LLM translation — with answers returned in 中文.",
        "zh": "双语输入采用三层 fallback：简体、繁体词映射，再到 LLM 翻译，并以中文回应。"
      },
      {
        "en": "Mirror detection labels cross-archive copies by verifiable ID rules (GSE ↔ E-GEOD ↔ S-GEOD) — flagged, never silently merged.",
        "zh": "镜像识别基于可验证 ID 规则（GSE ↔ E-GEOD ↔ S-GEOD）标注跨库副本——只标注，绝不隐性归并。"
      },
      {
        "en": "Graceful partial results: any adapter failure is isolated, reported honestly, and never blocks the other sources from delivering.",
        "zh": "优雅降级：任一适配器失败被局部隔离、如实告知，绝不阻塞其余源的交付。"
      }
    ],
    "figure": "api_routing.png",
    "figureExtra": "api_dispatch.png",
    "caption": {
      "en": "The api-routing agent: one query fans out to six federated archives in parallel, with mirror-aware fusion and live SSE streaming.",
      "zh": "API 路由智能体：一次查询并发扇出至六个联邦档案库，含镜像感知融合与 SSE 实时流式输出。"
    }
  },
  {
    "key": "downloads",
    "icon": "Download",
    "title": {
      "en": "Reproducible downloads",
      "zh": "可复现的数据下载"
    },
    "lede": {
      "en": "A result set is not the finish line — data you can re-analyze is. Singligent turns any selection into an exact, verifiable file manifest plus a ready-to-run download script, closing the long-overlooked gap between finding data and actually getting it.",
      "zh": "检索的终点不该是一份\"找到了什么\"的清单，而是能直接二次分析的数据。Singligent 把任意勾选的数据集转化为精确、可校验的文件清单与开箱即用的下载脚本，打通\"找到数据\"到\"拿到数据\"之间长期被忽视的环节。"
    },
    "points": [
      {
        "en": "Per-dataset file resolution: a resolver fixes each dataset's source, then exact paths, file sizes and md5 checksums.",
        "zh": "逐数据集解析：自动定位每条数据的源库，给出精确文件路径、体积与 md5 校验和。"
      },
      {
        "en": "Manifest assembly: items ticked across Explore, Advanced or Discover persist in one cross-page Manifest, no lost context.",
        "zh": "Manifest 清单：在 Explore、Advanced 或 Discover 各页勾选的项汇入同一份跨页持久化清单，切换不丢上下文。"
      },
      {
        "en": "Script generation over a 6×6 source-protocol matrix — bash/wget, prefetch+fasterq-dump, pyega3, aria2c, Snakemake, Python.",
        "zh": "依据 6×6 源-协议能力矩阵生成脚本——bash/wget、prefetch+fasterq-dump、pyega3、aria2c、Snakemake、Python。"
      },
      {
        "en": "Resumable, parallel transfers: ASPERA for large SRA files (10–100× throughput), aria2c parallel lists, S3 mirrors.",
        "zh": "可断点续传、并行传输：大文件 SRA 优选 ASPERA（吞吐提升 10–100 倍），支持 aria2c 并行列表与 S3 镜像。"
      },
      {
        "en": "Metadata export in CSV/TSV and JSON, scripted with checksums, directory layout and scanpy/Seurat load snippets.",
        "zh": "元数据可导出为 CSV/TSV 与 JSON，脚本内置校验、目录组织建议与 scanpy/Seurat 加载示例。"
      },
      {
        "en": "Audit-grade provenance: every script header carries timestamp, version, query trace, source IDs and disk-space checks.",
        "zh": "可审计溯源：每份脚本头部附带时间戳、版本、查询 trace、源标识与本地容量预估提示。"
      }
    ],
    "figure": "download_manifest.png",
    "figureExtra": "download_matrix.png",
    "caption": {
      "en": "From Manifest selection through the download-option resolver to exact file manifests and ready-to-run scripts (TSV / Bash / aria2c / JSON).",
      "zh": "从 Manifest 勾选，经下载选项 resolver，到精确文件清单与可执行脚本（TSV / Bash / aria2c / JSON）。"
    }
  },
  {
    "key": "eval",
    "icon": "BarChart3",
    "title": {
      "en": "Evaluation & Engineering Rigor",
      "zh": "评测体系与工程化严谨性"
    },
    "lede": {
      "en": "Both agents are held to a reproducible benchmark suite, scored against gold-standard oracles with bootstrapped confidence intervals, and improved through a closed eval-driven loop — so every gain is traceable to a specific module and fix.",
      "zh": "两个智能体都接受可复现的基准测试套件检验：以黄金标准 oracle 评分、报告 bootstrap 置信区间，并通过评测驱动的闭环持续改进——每一处提升都可追溯到具体模块与修复。"
    },
    "points": [
      {
        "en": "NL→SQL (Explore) benchmarked on NL2SQL Gold v2 — 29 oracle-labeled questions scored on component, execution, and composite recall.",
        "zh": "NL→SQL（Explore）以 NL2SQL Gold v2 为基准——29 道 oracle 标注题，按组件、执行与复合召回评分。"
      },
      {
        "en": "Discover graded on a 50-query, 754-positive retrieval set using Hit@10, MRR, and nDCG@10 with 1,000-sample bootstrap CIs.",
        "zh": "Discover 在 50 题、754 个标注正例的检索集上以 Hit@10、MRR、nDCG@10 评测，置信区间由 1,000 次 bootstrap 重采样给出。"
      },
      {
        "en": "A 9-variant ablation isolates each layer: the default config beats a single-source baseline 2.2–3.0× across all three metrics, CIs fully separated.",
        "zh": "9 变体消融分离各层贡献：默认配置在三项指标上较单库基线提升 2.2–3.0 倍，置信区间完全分离。"
      },
      {
        "en": "Ablation proves gains come from structure (intent parsing, parallel dispatch, mirror dedup), not the LLM — and that rerankers can hurt MRR.",
        "zh": "消融证明性能来自结构化层（意图解析、并发分发、镜像去重），而非 LLM 本身——且重排序器可能拉低 MRR。"
      },
      {
        "en": "A 14-family × 14-axis coverage matrix localizes every failure to a concrete axis instead of one opaque aggregate score.",
        "zh": "14 类场景 × 14 评测轴的覆盖矩阵，将每个失败定位到具体评测轴，而非笼统的单一总分。"
      },
      {
        "en": "Every LLM-judge run is anchored to a human pilot: Cohen's weighted κ reached 0.885, validating large-scale automated grading.",
        "zh": "每次 LLM 评判前都以人工 pilot 锚定：Cohen 加权 κ 达 0.885，为大规模自动评分提供可信底盘。"
      }
    ],
    "figure": "eval.png",
    "figureExtra": null,
    "caption": {
      "en": "Evaluation overview: parser comparison, ablations, release-over-release trends, capability matrix, and human–LLM annotation agreement.",
      "zh": "评测全景：解析器对照、消融实验、跨版本趋势、能力矩阵与人工–LLM 标注一致性。"
    }
  },
  {
    "key": "value",
    "icon": "Sparkles",
    "title": {
      "en": "Applications & Value",
      "zh": "应用与价值"
    },
    "lede": {
      "en": "Researchers use Singligent to go from a question to analysis-ready data in minutes, not hours. The NL→SQL agent pinpoints cohorts in the curated human catalog while the api-routing agent discovers the newest and cross-species data live — both feeding one manifest and one reproducible download script.",
      "zh": "研究者借助 Singligent，把\"提出问题到拿到可分析数据\"从数小时压缩到几分钟。Explore 的 NL→SQL 智能体在精选人源目录中精确锁定队列，Discover 的 api-routing 智能体并发拉取最新及跨物种数据——两者汇入同一份 Manifest 与一键可复现的下载脚本。"
    },
    "points": [
      {
        "en": "Cohort discovery: one plain-English or Chinese question returns usable samples across 943,732 harmonized human scRNA-seq records.",
        "zh": "队列发现：一句中英文提问，即可在 943,732 条统一人源 scRNA-seq 记录中返回可用样本。"
      },
      {
        "en": "Cross-study aggregation: dedup and roll up results across 16,376 projects and 8 sources without site-hopping.",
        "zh": "跨研究聚合：横跨 16,376 个项目、8 个数据源去重汇总，无需在多个数据库网站间反复切换。"
      },
      {
        "en": "Ontology-aware recall turns zero-result queries into hits — e.g. \"fetal brain\" 0→31,048, \"pancreatic islet diabetes\" 0→2,088 samples.",
        "zh": "本体感知扩展把零结果查询变为命中——如\"胎儿脑\"由 0 扩为 31,048、\"胰岛糖尿病\"由 0 扩为 2,088 个样本。"
      },
      {
        "en": "Time saved: early-stage data prep drops from 2–4 hours to under 6 minutes; non-analysis time falls from ~50% to ~2%.",
        "zh": "节省时间：项目早期数据准备从 2–4 小时降至 6 分钟内；非分析时间占比由约 50% 降至约 2%。"
      },
      {
        "en": "Reproducible acquisition: every search resolves to exact files, md5s and a one-step script — a citable, repeatable record.",
        "zh": "可复现获取：每次检索都解析到确切文件、md5 与一步到位脚本——形成可引用、可重复的获取记录。"
      },
      {
        "en": "Open & FAIR: the harmonized catalog is published CC-BY-4.0 (Zenodo + Hugging Face), a reusable resource beyond the portal.",
        "zh": "开放与 FAIR：统一目录以 CC-BY-4.0 公开发布（Zenodo + Hugging Face），是超越门户本身的可复用资源。"
      }
    ],
    "figure": "cases.png",
    "figureExtra": null,
    "caption": {
      "en": "Two real dual-agent workflows: cross-species comparison (human AD hippocampus + mouse/zebrafish brain atlases) and multi-omics integration (AD hippocampus scRNA + scATAC + spatial), each merged into a single manifest.",
      "zh": "两个真实的双智能体工作流：跨物种比较（人 AD 海马体 + 小鼠/斑马鱼脑发育图谱）与多组学整合（AD 海马体 scRNA + scATAC + 空间转录组），均汇入同一份 Manifest。"
    }
  }
];
