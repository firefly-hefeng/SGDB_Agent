/**
 * Lightweight i18n for the portal UI (Phase 37).
 *
 * The NL→SQL agent already understands English, 中文, and mixed queries; this
 * adds a matching bilingual UI chrome so a Chinese-speaking user isn't faced with
 * an English-only interface. Intentionally dependency-free (no i18next) — a small
 * dictionary + a context hook is enough for a static portal and keeps the bundle
 * lean. Extend `DICT` to translate more strings; `t(key, fallback)` returns the
 * fallback (or the key) for anything not yet translated, so partial coverage is
 * always safe.
 */
import { createContext, useContext, useState, useCallback, type ReactNode } from 'react';

export type Lang = 'en' | 'zh';
const STORAGE_KEY = 'sgdb.lang';

// key → { en, zh }. Grouped by surface for readability.
const DICT: Record<string, { en: string; zh: string }> = {
  // ── nav ──
  'nav.home': { en: 'Home', zh: '首页' },
  'nav.explore': { en: 'Explore', zh: '浏览' },
  'nav.discover': { en: 'Discover', zh: '发现' },
  'nav.advanced': { en: 'Advanced', zh: '高级检索' },
  'nav.workspace': { en: 'Workspace', zh: '工作区' },
  'nav.downloads': { en: 'Downloads', zh: '下载' },
  'nav.stats': { en: 'Statistics', zh: '统计' },
  'nav.celltypes': { en: 'Cell types', zh: '细胞类型' },
  'nav.about': { en: 'About', zh: '关于' },
  'nav.search.placeholder': { en: 'Search datasets, tissues, diseases…', zh: '搜索数据集、组织、疾病…' },
  'nav.search.aria': { en: 'Search', zh: '搜索' },
  // ── language toggle ──
  'lang.toggle.aria': { en: 'Switch language', zh: '切换语言' },
  // ── landing hero ──
  'landing.hero.title': {
    en: 'A unified portal for single-cell RNA-seq metadata.',
    zh: '单细胞 RNA-seq 元数据的统一门户。',
  },
  'landing.cta.explore': { en: 'Explore the catalog', zh: '浏览数据目录' },
  'landing.cta.discovery': { en: 'Live discovery', zh: '实时发现' },
  'landing.cta.nl': { en: 'Try a natural-language query →', zh: '试试自然语言检索 →' },
  'landing.eyebrow': { en: 'Single-cell genomics data portal', zh: '单细胞基因组数据门户' },
  'landing.hero.line1': { en: 'Every single-cell dataset,', zh: '汇聚所有单细胞数据集，' },
  'landing.hero.line2': { en: 'one query away.', zh: '一次检索即达。' },
  'landing.hero.sub.a': {
    en: 'Search a curated catalogue of human single-cell studies — GEO, EGA, NCBI, EBI, CellxGene, PsychAD, HTAN and HCA — by tissue, disease, assay, donor or free-text, in plain English or 中文.',
    zh: '检索人类单细胞研究的精选目录——涵盖 GEO、EGA、NCBI、EBI、CellxGene、PsychAD、HTAN 与 HCA——可按组织、疾病、实验技术、供体或自由文本，支持中文或英文。',
  },
  'landing.hero.sub.b': {
    en: 'curated human scRNA-seq samples in plain English — then reach live across GEO, EBI, CellxGene, HCA and more for the very latest submissions.',
    zh: '个精选人源 scRNA-seq 样本——用自然语言即可检索；需要最新数据时，还能实时联检 GEO、EBI、CellxGene、HCA 等公开数据库，获取最新提交。',
  },
  'landing.featured.title': { en: 'Featured collections', zh: '特色数据集合' },
  'landing.featured.sub': { en: 'Curated, ready-to-explore subsets.', zh: '精选、可直接浏览的数据子集。' },
  'landing.sources.title': { en: 'Source databases', zh: '数据来源' },
  'landing.sources.sub': { en: 'Browse by where the data came from. Counts are live.', zh: '按数据来源浏览。计数为实时数据。' },
  'landing.do.title': { en: 'What you can do here', zh: '你可以做什么' },
  'landing.do.explore.title': { en: 'Explore the catalog', zh: '浏览数据目录' },
  'landing.do.explore.body': {
    en: 'Faceted browse across the unified sources. Filter by tissue, disease, assay, sample type, cell count.',
    zh: '在统一来源中分面浏览。可按组织、疾病、实验技术、样本类型、细胞数筛选。',
  },
  'landing.do.nl.title': { en: 'Natural-language search', zh: '自然语言检索' },
  'landing.do.nl.body': {
    en: 'Ask in plain English or 中文. The NL→SQL agent parses your intent, expands ontologies and runs SQL across the curated human catalog — then save results to a workspace and export download scripts.',
    zh: '用中文或英文提问。NL→SQL 智能体解析意图、扩展本体、在精选人源目录上执行 SQL——结果可存入工作区并导出下载脚本。',
  },
  'landing.do.discover.title': { en: 'Live cross-DB discovery', zh: '实时跨库发现' },
  'landing.do.discover.body': {
    en: 'The api-routing agent turns your query into live API calls across GEO, EBI BioStudies, SCEA, CellxGene and HCA in parallel (SRA on demand) — centralized, fast discovery spanning multi-species / multi-omics data. Mirrors and dedup included.',
    zh: 'api-routing 智能体把查询转成实时 API 调用，并行检索 GEO、EBI BioStudies、SCEA、CellxGene 与 HCA(SRA 可按需启用)——跨多物种 / 多组学的集中快速发现，含镜像与去重。',
  },
  'landing.open': { en: 'Open', zh: '打开' },
  // ── landing: how the portal is organized ──
  'landing.org.title': { en: 'How this portal is organized', zh: '本门户的组成' },
  'landing.org.sub': {
    en: 'We curate the metadata of mainstream human single-cell RNA-seq datasets, served by two complementary agents. The NL→SQL agent turns a researcher’s natural-language question into SQL over the curated human scRNA-seq catalog — with a workspace for organizing results and one-click downloads. The api-routing agent turns a query directly into live API calls across federated archives, for centralized, fast discovery of multi-species / multi-omics sequencing data.',
    zh: '我们收集并整理了主流人源单细胞 RNA-seq 数据的 metadata,由两个互补的智能体提供服务。NL→SQL 智能体把研究人员的自然语言翻译成 SQL 查询语言,在精选的人源 scRNA-seq 目录上检索,并提供数据处理空间与便捷下载服务。api-routing 智能体把查询需求直接翻译成 API 调用语句,跨联邦档案实现对多物种 / 多组学各类测序数据的集中、快速查询。',
  },
  'landing.org.curated.title': { en: 'Curated human scRNA-seq — NL→SQL agent', zh: '精选人源 scRNA-seq — NL→SQL 智能体' },
  'landing.org.curated.body': {
    en: 'Mainstream human scRNA-seq metadata, harmonized & ontology-aligned locally. The NL→SQL agent translates plain English / 中文 into SQL for instant faceted + natural-language search, with a workspace and convenient downloads. Four record levels (counts live):',
    zh: '主流人源 scRNA-seq 的 metadata,本地协调并对齐本体。NL→SQL 智能体把中/英文翻译成 SQL,支持即时分面与自然语言检索,并配有数据处理空间与便捷下载。四种记录层级(计数实时):',
  },
  'landing.org.live.title': { en: 'Live discovery — api-routing agent', zh: '实时发现 — api-routing 智能体' },
  'landing.org.live.body': {
    en: 'The api-routing agent translates your query directly into live API calls, fanned out in parallel across federated archives — centralized, fast discovery of multi-species / multi-omics sequencing data (newest submissions and sources beyond the curated human catalog), with mirror detection and cross-source dedup.',
    zh: 'api-routing 智能体把查询需求直接翻译成实时 API 调用,并行发往多个联邦档案——实现对多物种 / 多组学各类测序数据的集中、快速查询(含最新提交与精选人源目录之外的来源),并含镜像识别与跨源去重。',
  },
  'landing.org.rt.samples': { en: 'cell-level metadata', zh: '细胞级元数据' },
  'landing.org.rt.projects': { en: 'study-level (groups)', zh: '研究级(分组)' },
  'landing.org.rt.series': { en: 'assay-level + files', zh: '技术级 + 文件' },
  'landing.org.rt.celltypes': { en: 'standardized (CL)', zh: '标准化(CL)' },
  'landing.org.sources_n': { en: 'sources', zh: '来源' },
  'landing.guide.title': { en: 'What each page does', zh: '各页面的功能' },
  // short one-liners per page
  'guide.explore': { en: 'Faceted + NL browse of the 944K-sample cell-level catalog.', zh: '对 94 万样本细胞级目录的分面 + 自然语言浏览。' },
  'guide.projects': { en: 'Study-level metadata with full-text search + citation/year filters.', zh: '研究级元数据,支持全文检索与引用/年份筛选。' },
  'guide.series': { en: 'Assay-level series with downloadable-object (h5ad/rds) filters.', zh: '技术级系列,支持可下载对象(h5ad/rds)筛选。' },
  'guide.celltypes': { en: 'Enter the catalog by standardized cell type (Cell Ontology).', zh: '按标准化细胞类型(Cell Ontology)进入目录。' },
  'guide.advanced': { en: 'One natural-language box → ontology-expanded SQL + execution trace.', zh: '一个自然语言框 → 本体扩展 SQL + 执行轨迹。' },
  'guide.discover': { en: 'Live parallel search across up to 6 federated public databases.', zh: '对最多 6 个联邦公开数据库的实时并行检索。' },
  'guide.downloads': { en: 'Resolve exact files (size + md5) → bash/aria2/Snakemake/Python scripts.', zh: '解析精确文件(大小 + md5)→ bash/aria2/Snakemake/Python 脚本。' },
  'guide.workspace': { en: 'Save, annotate and export sets of samples/projects/series.', zh: '保存、标注并导出样本/项目/系列集合。' },
  'guide.stats': { en: 'Live charts: tissue/disease/assay/year distributions.', zh: '实时图表:组织/疾病/技术/年份分布。' },
  'guide.about': { en: 'Per-table composition, source provenance, curated-vs-federated split.', zh: '各表组成、来源溯源、精选与联邦的区分。' },
  'guide.agent': { en: 'Machine-readable tool manifest (OpenAI/Anthropic/MCP) for agents.', zh: '面向智能体的机器可读工具清单(OpenAI/Anthropic/MCP)。' },
  // ── how-to-use affordance ──
  'howto.trigger': { en: 'How to use / Examples', zh: '使用说明 / 示例' },
  'howto.examples': { en: 'Try these', zh: '可尝试' },
  // ── per-module intros ──
  'intro.explore.body': {
    en: 'Faceted browse of the curated sample catalog — the cell-level tier. Filter by tissue, disease, assay, sex, donor and cell count. Reach for Projects/Series for study-level metadata, or Discover when you need the very latest public submissions.',
    zh: '对精选样本目录（细胞级）进行分面浏览。可按组织、疾病、实验技术、性别、供体与细胞数筛选。需要研究级元数据时用「项目/系列」，需要最新公开提交时用「发现」。',
  },
  'intro.projects.body': {
    en: 'Study-level (group) metadata with full-text search over title, description and organism. Use this when you want publications and study context; switch to Samples for cell-level filtering.',
    zh: '研究级（分组）元数据，支持对标题、描述与物种的全文检索。需要文献与研究背景时使用；需要细胞级筛选时切换到「样本」。',
  },
  'intro.series.body': {
    en: 'Individual sequencing series — assay-level metadata with file-availability badges (h5ad / rds) and download URLs where catalogued. Use this to find processed objects to download.',
    zh: '单个测序系列——实验技术级元数据，附文件可用性标识（h5ad / rds）及已收录的下载链接。用于查找可下载的处理后对象。',
  },
  'intro.celltypes.body': {
    en: 'Browse the standardized cell types (Cell Ontology, CL) found across the catalog. Each row shows how many samples, projects and series carry that dominant label; click a row to see the studies. Use this to enter the catalog by biology rather than by accession.',
    zh: '浏览目录中标准化的细胞类型（Cell Ontology，CL）。每行显示带该主导标签的样本、项目与系列数量；点击某行可查看相关研究。用于按生物学（而非编号）进入目录。',
  },
  'intro.advanced.body': {
    en: 'One natural-language box over the curated catalog: the agent parses intent, expands ontology terms, generates SQL, runs it and returns a faceted result set. Best when your need spans several facets at once. For keyword or ID lookup, Explore is faster.',
    zh: '面向精选目录的自然语言检索：智能体解析意图、扩展本体词、生成并执行 SQL，返回分面结果集。适合一次涉及多个维度的需求。关键词或编号查找用「浏览」更快。',
  },
  'intro.discover.body': {
    en: 'Live federation: one query is sent in parallel to up to six public archives (GEO, EBI BioStudies, Single-Cell Expression Atlas, CellxGene, HCA by default; SRA on demand) with mirror detection and cross-source dedup. Use this for the newest submissions or sources not yet in the curated catalog (SRA, SCEA).',
    zh: '实时联邦检索：同一查询并行发送至最多六个公开档案（默认 GEO、EBI BioStudies、单细胞表达图谱、CellxGene、HCA；SRA 可按需启用），含镜像识别与跨源去重。用于最新提交或尚未收录的来源（SRA、SCEA）。',
  },
  'intro.downloads.body': {
    en: 'Look up direct download URLs for any catalogued dataset, export a bulk script (TSV / curl / aria2) from your manifest, or pull a slice of unified sample metadata as CSV/JSON. Items added from Explore, Search or Discover flow through here.',
    zh: '查找任意已收录数据集的直接下载链接，从清单导出批量脚本（TSV / curl / aria2），或将统一样本元数据切片导出为 CSV/JSON。从「浏览」「检索」「发现」加入的条目都汇集于此。',
  },
  'intro.workspace.body': {
    en: 'Save samples, projects and series into named workspaces to revisit, annotate and export later. Use the bookmark button anywhere in the catalog to add items; deleted workspaces are recoverable.',
    zh: '将样本、项目与系列保存到命名工作区，便于回访、标注与导出。在目录任意位置用书签按钮加入条目；已删除的工作区可恢复。',
  },
  'intro.stats.body': {
    en: 'A live snapshot of the curated catalog: sample counts, source coverage, tissue and disease distributions, submissions over time. Click any chart bar to filter Explore by that facet.',
    zh: '精选目录的实时快照：样本计数、来源覆盖、组织与疾病分布、历年提交。点击任意图表柱可按该维度筛选「浏览」。',
  },
  // ── cell-types page ──
  'celltypes.eyebrow': { en: 'Curated catalog', zh: '精选目录' },
  'celltypes.title': { en: 'Browse by cell type', zh: '按细胞类型浏览' },
  'celltypes.desc': {
    en: 'Standardized cell types (Cell Ontology, CL) across the unified sample catalog. Click a row to see the studies that report it.',
    zh: '统一样本目录中标准化的细胞类型（Cell Ontology，CL）。点击某行可查看报告该类型的研究。',
  },
  'celltypes.search.placeholder': { en: 'Search cell type names (e.g. T cell, hepatocyte)…', zh: '搜索细胞类型名称（如 T cell、hepatocyte）…' },
  'celltypes.search.aria': { en: 'Search cell types', zh: '搜索细胞类型' },
  'celltypes.count': { en: 'cell types', zh: '种细胞类型' },
  'celltypes.col.celltype': { en: 'Cell type', zh: '细胞类型' },
  'celltypes.col.ontology': { en: 'Ontology', zh: '本体' },
  'celltypes.col.samples': { en: 'Samples', zh: '样本' },
  'celltypes.col.projects': { en: 'Projects', zh: '项目' },
  'celltypes.col.series': { en: 'Series', zh: '系列' },
  'celltypes.col.sources': { en: 'Sources', zh: '来源' },
  'celltypes.sort.label': { en: 'Sort cell types', zh: '排序细胞类型' },
  'celltypes.sort.samples': { en: 'Most samples', zh: '样本最多' },
  'celltypes.sort.projects': { en: 'Most projects', zh: '项目最多' },
  'celltypes.sort.series': { en: 'Most series', zh: '系列最多' },
  'celltypes.sort.name': { en: 'Name A→Z', zh: '名称 A→Z' },
  'celltypes.minsamples': { en: 'Min samples', zh: '最少样本' },
  'celltypes.empty': { en: 'No cell types match your search.', zh: '没有符合的细胞类型。' },
  'celltypes.showing': { en: 'Showing all', zh: '显示全部' },
  'celltypes.of': { en: 'of', zh: '共' },
  'celltypes.retry': { en: 'Retry', zh: '重试' },
  'celltypes.ols.title': { en: 'Open in EBI Ontology Lookup Service', zh: '在 EBI 本体查询服务中打开' },
  'celltypes.close.aria': { en: 'Close', zh: '关闭' },
  // cell-types coverage banner
  'celltypes.coverage.basis': { en: 'Basis', zh: '统计依据' },
  'celltypes.coverage.annotated': { en: 'of samples annotated', zh: '的样本已标注' },
  'celltypes.coverage.across': { en: 'across', zh: '覆盖' },
  'celltypes.coverage.types': { en: 'standardized types.', zh: '种标准化类型。' },
  'celltypes.drill.title': { en: 'Studies reporting', zh: '报告以下类型的研究' },
  'celltypes.drill.loading': { en: 'Loading studies…', zh: '加载研究中…' },
  'celltypes.drill.empty': { en: 'No studies found for this cell type.', zh: '未找到相关研究。' },
  'celltypes.drill.more': { en: 'and more — showing the top studies by sample count.', zh: '及更多——按样本数显示前若干研究。' },
  'celltypes.drill.open': { en: 'Open in Explore', zh: '在浏览中打开' },
  'celltypes.coverage.title': { en: 'How to read these counts', zh: '如何理解这些计数' },
  'celltypes.intro.body': {
    en: 'Browse the standardized cell types (Cell Ontology, CL) found across the catalog. Each row shows how many samples, projects and series carry that dominant label; click a row to see the studies.',
    zh: '浏览目录中标准化的细胞类型（Cell Ontology，CL）。每行显示带该主导标签的样本、项目与系列数量；点击某行可查看研究。',
  },
  // ── about / data-coverage page ──
  'about.eyebrow': { en: 'About the system', zh: '关于系统' },
  'about.title': { en: 'A dual-agent portal for single-cell metadata', zh: '面向单细胞元数据的双智能体门户' },
  'about.desc': {
    en: 'How Singligent is built — its architecture, the harmonized catalog behind it, the two agents that drive search and live discovery, reproducible downloads, and how the system is evaluated. Every catalog figure on this page is fetched live.',
    zh: 'Singligent 的构建之道——系统架构、其背后的统一元数据库、驱动检索与实时发现的两个智能体、可复现的下载流程，以及系统的评测方法。本页所有目录数据均为实时获取。',
  },
  'about.overview.lede': {
    en: 'Singligent unifies mainstream human single-cell RNA-seq metadata and pairs it with two complementary AI agents: a natural-language → SQL agent over a curated, harmonized catalog, and an api-routing agent that fans one query out live across public archives. The result is a single place to discover, refine, and reproducibly acquire single-cell datasets — in plain English or 中文.',
    zh: 'Singligent 汇聚主流人源单细胞 RNA-seq 元数据，并配以两个互补的 AI 智能体：面向精选、统一目录的自然语言→SQL 智能体，以及把一次查询实时分发到各公共档案库的 api-routing 智能体。由此提供一处统一入口，用中文或英文即可发现、精筛并可复现地获取单细胞数据集。',
  },
  'about.docs.label': { en: 'How the system works', zh: '系统如何运作' },
  'about.gallery.title': { en: 'Design figure gallery', zh: '设计图集' },
  'about.gallery.sub': { en: 'Additional design figures — click any to enlarge.', zh: '更多系统设计图——点击任意一张放大查看。' },
  'about.fig.label': { en: 'Figure', zh: '图' },
  'about.fig.enlarge': { en: 'Enlarge figure', zh: '放大图片' },
  'about.fig.overview': {
    en: 'System architecture and catalog at scale — the dual-agent infrastructure (Discover → Select → Acquire), the harmonized data resource, and its biological & disease coverage.',
    zh: '系统架构与数据规模——双智能体基础设施（发现 → 选择 → 获取）、统一的数据资源，及其生物学与疾病覆盖。',
  },
  'about.glance.donors': { en: 'Donors', zh: '供体' },
  'about.glance.sources': { en: 'Sources', zh: '数据源' },
  'about.tiers.title': { en: 'Curated record tiers', zh: '精选记录层级' },
  'about.tiers.sub': {
    en: 'The catalog is browsable at four record levels — counts are live; fine-grained cell-type composition is CellxGene-only.',
    zh: '目录可在四个记录层级浏览——计数为实时；细粒度细胞类型组成目前仅 CellxGene 提供。',
  },
  'about.src.both': { en: 'curated + live', zh: '精选 + 实时' },
  'about.src.live': { en: 'live-only', zh: '仅实时' },
  'common.close': { en: 'Close', zh: '关闭' },
  'stats.atlas.label': { en: 'Catalog atlas', zh: '目录图集' },
  'stats.atlas.sub': {
    en: 'A publication-grade snapshot of the live catalog — source contribution, biological & disease coverage, assay mix, growth over time, and literature linkage. Explore the same data interactively below.',
    zh: '一份出版级的实时目录快照——数据源贡献、生物学与疾病覆盖、实验技术构成、增长趋势与文献关联。下方可对同一数据进行交互式浏览。',
  },
  'stats.atlas.view': { en: 'Open full size', zh: '查看大图' },
  'stats.atlas.alt': { en: 'Catalog atlas: multi-panel overview of the Singligent single-cell catalog', zh: '目录图集：Singligent 单细胞目录的多面板概览' },
  'stats.interactive.label': { en: 'Interactive explorer', zh: '交互式浏览' },
  'about.curated.title': { en: 'Curated catalog (human scRNA-seq) — NL→SQL agent', zh: '精选目录（人源 scRNA-seq）— NL→SQL 智能体' },
  'about.curated.sub': {
    en: 'Mainstream human scRNA-seq metadata, harmonized, deduplicated and indexed locally so the NL→SQL agent can answer instantly. Source counts differ by tier because not every source carries every record type.',
    zh: '主流人源 scRNA-seq 的 metadata，本地协调、去重并建立索引，使 NL→SQL 智能体可即时作答。各层级来源数不同，因为并非每个来源都提供每种记录类型。',
  },
  'about.tier.samples': { en: 'Samples', zh: '样本' },
  'about.tier.projects': { en: 'Projects', zh: '项目' },
  'about.tier.series': { en: 'Series', zh: '系列' },
  'about.tier.celltypes': { en: 'Cell-type tier', zh: '细胞类型层' },
  'about.tier.from': { en: 'from', zh: '来自' },
  'about.tier.sources': { en: 'sources', zh: '个来源' },
  'about.tier.source': { en: 'source', zh: '个来源' },
  'about.celltypes.note': {
    en: 'Fine-grained cell-type composition is available for CellxGene samples only; other sources contribute a single dominant label per sample.',
    zh: '细粒度细胞类型组成仅 CellxGene 样本可用；其他来源每个样本提供单一主导标签。',
  },
  'about.bysource.title': { en: 'Curated sources by sample count', zh: '各来源样本计数' },
  'about.live.title': { en: 'Live discovery — api-routing agent (multi-species / multi-omics)', zh: '实时发现 — api-routing 智能体（多物种 / 多组学）' },
  'about.live.sub': {
    en: 'The api-routing agent turns your query into live API calls, fanned out in parallel on demand — reaching multi-species / multi-omics sequencing data beyond the curated human catalog. SRA and the Single-Cell Expression Atlas are live-only.',
    zh: 'api-routing 智能体把查询翻译成实时 API 调用，按需并行发出——可触及精选人源目录之外的多物种 / 多组学测序数据。SRA 与单细胞表达图谱仅限实时检索。',
  },
  'about.why.title': { en: 'Why source counts differ across tiers', zh: '为何各层级来源数不同' },
  'about.why.body': {
    en: 'A repository is counted in a tier only when it publishes that record type. Sample-level metadata is the broadest; far fewer repositories expose stable project or series identifiers, and fine-grained cell-type composition is currently CellxGene-only. The number above each tier is computed live, so it always reflects the database as built.',
    zh: '只有当某仓库发布了某种记录类型时，才计入对应层级。样本级元数据覆盖最广；提供稳定项目或系列标识符的仓库要少得多，而细粒度细胞类型组成目前仅 CellxGene 提供。每个层级上方的数字均实时计算，始终反映当前数据库构建情况。',
  },
  'about.error': { en: 'Could not load live data coverage.', zh: '无法加载实时数据覆盖信息。' },
  // ── footer ──
  'footer.browse': { en: 'Browse', zh: '浏览' },
  'footer.tools': { en: 'Tools', zh: '工具' },
  'footer.docs': { en: 'Docs', zh: '文档' },
  'footer.about': { en: 'About', zh: '关于' },
  'footer.lab': { en: 'Lab — compbio.nju.edu.cn', zh: '实验室 — compbio.nju.edu.cn' },
  'footer.opendata': { en: 'Open data (Hugging Face)', zh: '开放数据（Hugging Face）' },
  'footer.tagline': { en: 'Built for biologists, by biologists.', zh: '为生物学家打造，由生物学家打造。' },
  // ── nav extras ──
  'nav.manifest': { en: 'Manifest', zh: '下载清单' },
  'nav.stats.projects': { en: 'projects', zh: '项目' },
  'nav.stats.sources': { en: 'sources', zh: '来源' },
  // ── target-level tabs (sample / series / project / cell type) ──
  'tabs.targetlevel': { en: 'Target level', zh: '查询层级' },
  'tabs.sample': { en: 'Sample', zh: '样本' },
  'tabs.series': { en: 'Series', zh: '系列' },
  'tabs.project': { en: 'Project', zh: '项目' },
  'tabs.celltype': { en: 'Cell type', zh: '细胞类型' },
  // ── explore-family sidebar facets ──
  'facet.source': { en: 'Source', zh: '来源' },
  'facet.organism': { en: 'Organism', zh: '物种' },
  'facet.assay': { en: 'Assay', zh: '实验技术' },
  // facet group titles (FacetSidebar)
  'facet.tissue_system': { en: 'Tissue System', zh: '组织系统' },
  'facet.disease_category': { en: 'Disease Category', zh: '疾病分类' },
  'facet.sample_type': { en: 'Sample Type', zh: '样本类型' },
  'facet.tissue': { en: 'Tissue', zh: '组织' },
  'facet.disease': { en: 'Disease', zh: '疾病' },
  'facet.database': { en: 'Database', zh: '数据库' },
  'facet.cell_type': { en: 'Cell Type', zh: '细胞类型' },
  'facet.sex': { en: 'Sex', zh: '性别' },
  // facet sidebar controls
  'facet.filter_ph': { en: 'Filter...', zh: '筛选…' },
  'facet.no_matches': { en: 'No matches', zh: '无匹配' },
  'facet.show_less': { en: 'Show less', zh: '收起' },
  'facet.show_all': { en: 'Show all', zh: '显示全部' },
  'facet.header': { en: 'Filters', zh: '筛选' },
  'facet.reset': { en: 'Reset', zh: '重置' },
  'facet.close_aria': { en: 'Close filters', zh: '关闭筛选' },
  'facet.assay_modality': { en: 'Assay modality', zh: '检测模态' },
  'facet.platform': { en: 'Platform', zh: '测序平台' },
  'facet.data_format': { en: 'Data format', zh: '数据格式' },
  'facet.has_pmid': { en: 'Has PMID', zh: '有 PMID' },
  'facet.data_availability': { en: 'Data availability', zh: '获取方式' },
  'facet.year': { en: 'Year published', zh: '发表年份' },
  'facet.journals': { en: 'Top journals', zh: '主要期刊' },
  'facet.h5ad': { en: 'h5ad available', zh: '有 h5ad' },
  'facet.sort': { en: 'Sort', zh: '排序' },
  'facet.open': { en: 'open', zh: '开放获取' },
  'facet.controlled': { en: 'controlled', zh: '受控获取' },
  // ── sort options (projects / series) ──
  'sort.newest': { en: 'Newest first', zh: '最新优先' },
  'sort.oldest': { en: 'Oldest first', zh: '最早优先' },
  'sort.most_cited': { en: 'Most cited', zh: '引用最多' },
  'sort.most_samples': { en: 'Most samples', zh: '样本最多' },
  'sort.most_cells': { en: 'Most cells', zh: '细胞最多' },
  'sort.title_az': { en: 'Title A→Z', zh: '标题 A→Z' },
  'ph.projects.search': { en: 'Search project titles, descriptions, organisms…', zh: '搜索项目标题、描述、物种…' },
  'ph.series.search': { en: 'Search series titles, assays, platforms…', zh: '搜索系列标题、技术、平台…' },
  // ── results table (ResultsTable) ──
  'results.col.sample_id': { en: 'Sample ID', zh: '样本编号' },
  'results.col.organism': { en: 'Organism', zh: '物种' },
  'results.col.tissue': { en: 'Tissue', zh: '组织' },
  'results.col.system': { en: 'System', zh: '系统' },
  'results.col.disease': { en: 'Disease', zh: '疾病' },
  'results.col.category': { en: 'Category', zh: '分类' },
  'results.col.sample_type': { en: 'Sample Type', zh: '样本类型' },
  'results.col.cell_type': { en: 'Cell Type', zh: '细胞类型' },
  'results.col.assay': { en: 'Assay', zh: '实验技术' },
  'results.col.cells': { en: 'Cells', zh: '细胞数' },
  'results.col.source': { en: 'Source', zh: '来源' },
  'results.col.project': { en: 'Project', zh: '项目' },
  'results.selectall.aria': { en: 'Select all rows on this page', zh: '选择本页所有行' },
  'results.select.aria': { en: 'Select sample', zh: '选择样本' },
  'results.empty.title': { en: 'No samples match this search', zh: '没有样本符合此次检索' },
  'results.empty.searched': { en: 'Searched:', zh: '检索内容：' },
  'results.empty.dropfilter': {
    en: 'Several filters are active — try removing one (e.g. drop the most specific tissue or cell type).',
    zh: '当前启用了多个筛选——可尝试移除其一(如去掉最具体的组织或细胞类型)。',
  },
  'results.empty.broaden': {
    en: 'Try a broader term — “lung adenocarcinoma” is narrower than “lung cancer”.',
    zh: '尝试更宽泛的词——“lung adenocarcinoma”比“lung cancer”更窄。',
  },
  'results.empty.spelling': {
    en: 'Check the spelling and case (ontology labels are case-insensitive but typos won’t match).',
    zh: '检查拼写与大小写(本体标签不区分大小写,但拼写错误无法匹配)。',
  },
  'results.empty.coverage': {
    en: 'The curated catalogue covers GEO/SRA/ArrayExpress + CellxGene/HCA. Live source databases may have more.',
    zh: '精选目录涵盖 GEO/SRA/ArrayExpress + CellxGene/HCA。实时数据来源可能有更多。',
  },
  'results.empty.clearfilters': { en: 'Clear filters', zh: '清除筛选' },
  'results.empty.trydiscover': { en: 'Try Discover live', zh: '试试实时发现' },
  'results.empty.adjust': {
    en: 'Adjust filters in the sidebar or refine your query',
    zh: '在侧栏调整筛选,或细化你的查询',
  },
  'results.selected': { en: 'selected', zh: '已选' },
  'results.download_selected': { en: 'Download Selected', zh: '下载所选' },
  'results.add_manifest': { en: 'Add to manifest', zh: '加入下载清单' },
  'results.clear': { en: 'Clear', zh: '清除' },
  'results.toast.added_1': { en: 'Added', zh: '已添加' },
  'results.toast.dataset': { en: 'dataset', zh: '个数据集' },
  'results.toast.datasets': { en: 'datasets', zh: '个数据集' },
  'results.toast.to_manifest': { en: 'to manifest', zh: '到下载清单' },
  'results.toast.already': { en: 'Those datasets are already in the manifest', zh: '这些数据集已在下载清单中' },
  // ── active filters (ActiveFilters) ──
  'activefilters.tissue': { en: 'Tissue', zh: '组织' },
  'activefilters.disease': { en: 'Disease', zh: '疾病' },
  'activefilters.assay': { en: 'Assay', zh: '实验技术' },
  'activefilters.organism': { en: 'Organism', zh: '物种' },
  'activefilters.db': { en: 'DB', zh: '数据库' },
  'activefilters.cell': { en: 'Cell', zh: '细胞' },
  'activefilters.clearall': { en: 'Clear all', zh: '全部清除' },
  'activefilters.remove.aria': { en: 'Remove filter', zh: '移除筛选' },
  // ── pagination ──
  'pagination.aria': { en: 'Pagination', zh: '分页' },
  'pagination.of': { en: 'of', zh: '共' },
  'pagination.prev.aria': { en: 'Previous page', zh: '上一页' },
  'pagination.next.aria': { en: 'Next page', zh: '下一页' },
  'pagination.goto.aria': { en: 'Go to page', zh: '前往第' },
  // ── search bar (SearchBar) ──
  'searchbar.nl.placeholder': { en: 'Ask in natural language...', zh: '用自然语言提问…' },
  'searchbar.keyword.placeholder': { en: 'Search by keyword...', zh: '按关键词搜索…' },
  'searchbar.submit': { en: 'Search', zh: '搜索' },
  'searchbar.mode.keyword': { en: 'Keyword', zh: '关键词' },
  'searchbar.mode.ai': { en: 'AI', zh: '智能' },
  // ── explore page chrome ──
  'explore.eyebrow': { en: 'Curated catalog', zh: '精选目录' },
  'explore.title': { en: 'Explore datasets', zh: '浏览数据集' },
  'explore.advanced': { en: 'Advanced', zh: '高级检索' },
  'explore.discover_live': { en: 'Discover live', zh: '实时发现' },
  'explore.results': { en: 'results', zh: '条结果' },
  'explore.collection.label': { en: 'Curated collection:', zh: '精选集合：' },
  'explore.collection.browse_full': { en: 'Browse full catalog', zh: '浏览完整目录' },
  'explore.filters': { en: 'Filters', zh: '筛选' },
  'explore.show_filters': { en: 'Show filters', zh: '显示筛选' },
  'explore.advanced.title': { en: 'Open in Advanced Search with the current filters', zh: '以当前筛选在高级检索中打开' },
  'explore.discover.title': { en: 'Run the same query live against public source databases', zh: '对公开数据来源实时运行同一查询' },
  // ── advanced search page chrome ──
  'advanced.eyebrow': { en: 'Advanced search', zh: '高级检索' },
  'advanced.title': { en: 'Build a query in natural language', zh: '用自然语言构建查询' },
  'advanced.desc': {
    en: 'The agent parses your query, expands ontology terms, generates SQL, runs it, and returns a faceted result set. Refine using the sidebar.',
    zh: '智能体解析你的查询、扩展本体词、生成并执行 SQL,返回分面结果集。可通过侧栏进一步细化。',
  },
  'advanced.filters': { en: 'Filters', zh: '筛选' },
  'advanced.input.placeholder': {
    en: 'e.g. "human liver cancer 10x datasets" or "pancreatic islet from healthy donors"',
    zh: '例如 “human liver cancer 10x datasets” 或 “pancreatic islet from healthy donors”',
  },
  'advanced.input.aria': { en: 'Natural-language search input', zh: '自然语言检索输入框' },
  'advanced.searching': { en: 'Searching', zh: '检索中' },
  'advanced.refine': { en: 'Refine', zh: '细化' },
  'advanced.search': { en: 'Search', zh: '搜索' },
  'advanced.idle': { en: 'Enter a natural-language query above to search the curated catalog.', zh: '在上方输入自然语言查询以检索精选目录。' },
  'common.back': { en: 'Back', zh: '返回' },
  // ── data availability ──
  'data.title': { en: 'Data availability', zh: '数据获取' },
  'data.body': { en: 'The full curated catalog is openly downloadable as bulk tables (Parquet + CSV) and a complete SQLite snapshot.', zh: '完整的精选目录可作为批量数据表（Parquet + CSV）与完整 SQLite 快照公开下载。' },
  'data.note': { en: 'This bundle is the harmonized metadata (sample / project / series / cell-type descriptions), not the raw sequencing data — count matrices and FASTQ/BAM remain at the source archives, and the portal resolves exact per-dataset download links to them.', zh: '该数据包为协调后的元数据（样本 / 项目 / 系列 / 细胞类型描述），并非原始测序数据——表达矩阵与 FASTQ/BAM 仍位于来源档案，门户会为每个数据集解析精确的下载链接。' },
  'data.rows': { en: 'rows', zh: '行' },
  'data.zenodo': { en: 'Download (Zenodo)', zh: '下载（Zenodo）' },
  'data.hf': { en: 'Browse on Hugging Face', zh: '在 Hugging Face 浏览' },
  'data.pending': { en: 'Public deposition pending — the bundle is being archived to Zenodo (DOI) and Hugging Face.', zh: '公开存档进行中——数据包正在归档至 Zenodo（DOI）与 Hugging Face。' },
  'data.license': { en: 'License', zh: '许可' },
  'data.snapshot': { en: 'snapshot', zh: '快照' },
  'data.ega': { en: 'EGA: metadata-only; data access requires DAC approval.', zh: 'EGA：仅含元数据；数据访问需经 DAC 批准。' },
  'data.tier.unified_samples': { en: 'Sample tier — cell-level metadata', zh: '样本层级——细胞级元数据' },
  'data.tier.unified_projects': { en: 'Project tier — study-level groupings', zh: '项目层级——研究级分组' },
  'data.tier.unified_series': { en: 'Series tier — assay-level + file pointers', zh: '系列层级——技术级 + 文件指针' },
  'data.tier.unified_celltypes': { en: 'Cell-type annotations (Cell Ontology)', zh: '细胞类型标注（Cell Ontology）' },
  'about.project': { en: 'Singligent is built and maintained at Nanjing University. Public portal:', zh: 'Singligent 由南京大学构建与维护。公开门户：' },
  'about.lab': { en: 'Lab', zh: '实验室' },
  'dataset.notfound.title': { en: 'Not in the curated catalog', zh: '不在精选目录中' },
  'dataset.notfound.hint': { en: 'This identifier was not found in the curated human catalog. It may exist in a live public archive — search for it with the Discover agent.', zh: '该标识符不在精选人源目录中。它可能存在于某个实时公共档案中——可用 Discover 智能体检索。' },
  'dataset.notfound.discover': { en: 'Search Discover', zh: '用 Discover 检索' },
  'advanced.refine_within': { en: 'Refine within current results', zh: '在当前结果内细化' },
  'advanced.refine_and_1': { en: '(AND onto the', zh: '(与当前' },
  'advanced.refine_and_condition': { en: 'active condition', zh: '个生效条件取交集' },
  'advanced.refine_and_conditions': { en: 'active conditions', zh: '个生效条件取交集' },
  'advanced.refine.suffix': { en: ')', zh: ')' },
  'advanced.refine_label': { en: 'Refine:', zh: '细化：' },
  'advanced.toast.downloaded_1': { en: 'Downloaded', zh: '已下载' },
  'advanced.toast.downloaded_2': { en: 'samples as', zh: '个样本(格式' },
  'advanced.toast.downloaded_3': { en: '', zh: ')' },
  'advanced.toast.download_failed': { en: 'Metadata download failed:', zh: '元数据下载失败：' },
  'advanced.toast.no_ids': { en: 'No dataset IDs in the current results', zh: '当前结果中没有数据集 ID' },
  // ── discover page chrome ──
  'discover.eyebrow': { en: 'Live cross-database', zh: '实时跨库' },
  'discover.title': {
    en: 'Discover datasets across public scRNA-seq archives',
    zh: '在公开 scRNA-seq 档案中发现数据集',
  },
  'discover.sub': {
    en: 'One natural-language query, up to six public databases — GEO, EBI BioStudies, EBI Single-Cell Atlas, CellxGene, HCA (and SRA on demand) — queried in parallel with mirror detection and cross-source dedup.',
    zh: '一次自然语言查询，最多六个公开数据库——GEO、EBI BioStudies、EBI 单细胞表达图谱、CellxGene、HCA（SRA 可按需启用）——并行检索，含镜像识别与跨源去重。',
  },
  'discover.searching': { en: 'Searching…', zh: '检索中…' },
  'discover.done_count': { en: 'done', zh: '已完成' },
  'discover.hits_across_1': { en: 'hits across', zh: '条命中,跨' },
  'discover.hits_across_2': { en: 'sources', zh: '个来源' },
  'discover.retry': { en: 'Retry', zh: '重试' },
  'discover.intent_json': { en: 'Parsed intent JSON', zh: '解析意图 JSON' },
  'discover.searching_short': { en: 'searching…', zh: '检索中…' },
  'discover.llm_summary': { en: 'LLM summary', zh: 'LLM 摘要' },
  'discover.synth.generated': { en: 'generated from streaming results', zh: '基于流式结果生成' },
  'discover.synth.cached': { en: 'cached', zh: '缓存' },
  'discover.empty.title': {
    en: 'Type a query to fan out across all selected databases.',
    zh: '输入查询,即可并行检索所有所选数据库。',
  },
  'discover.empty.sub_1': {
    en: 'Results stream in as each source responds. Same query already catalogued internally?',
    zh: '各来源响应时,结果将逐步流入。同样的查询已被内部收录?',
  },
  'discover.empty.try_explore': { en: 'Try Explore', zh: '试试浏览' },
  'discover.empty.sub_2': { en: 'for instant results.', zh: '可即时获得结果。' },
  'discover.nohits_1': { en: 'No live hits across', zh: '未在' },
  'discover.nohits_2': { en: 'sources.', zh: '个来源中找到实时命中。' },
  'discover.nohits.sub': {
    en: 'Try broadening the terms, removing the year restriction, or running the same query against the curated catalog —',
    zh: '可尝试放宽词条、移除年份限制,或对精选目录运行同样的查询——',
  },
  'discover.nohits.explore': { en: 'Explore →', zh: '浏览 →' },
  // ── discover: search bar (DiscoverSearchBar) ──
  'discover.bar.placeholder': {
    en: "Describe the datasets you're looking for — e.g. Alzheimer hippocampus scRNA-seq",
    zh: '描述你想找的数据集——例如 Alzheimer hippocampus scRNA-seq',
  },
  'discover.bar.clear.aria': { en: 'Clear query', zh: '清空查询' },
  'discover.bar.sources': { en: 'Sources', zh: '数据库' },
  'discover.bar.search_across': { en: 'Search across…', zh: '检索范围…' },
  'discover.bar.llm_summary': { en: 'LLM summary', zh: 'LLM 摘要' },
  'discover.bar.per_source': { en: 'Per source', zh: '每库上限' },
  'discover.bar.per_source.title': { en: 'Max results fetched from each source (1–100)', zh: '每个数据库的最大返回结果数(1–100)' },
  'discover.bar.stop': { en: 'Stop', zh: '停止' },
  'discover.bar.discover': { en: 'Discover', zh: '发现' },
  'discover.bar.try': { en: 'Try:', zh: '可尝试:' },
  // ── discover: intent chips (DiscoverIntentChips) ──
  'discover.intent.parsed': { en: 'Parsed intent', zh: '解析意图' },
  'discover.intent.disease': { en: 'Disease', zh: '疾病' },
  'discover.intent.tissue': { en: 'Tissue', zh: '组织' },
  'discover.intent.tech': { en: 'Tech', zh: '技术' },
  'discover.intent.species': { en: 'Species', zh: '物种' },
  'discover.intent.keywords': { en: 'Keywords', zh: '关键词' },
  'discover.intent.excluded': { en: 'Excluded', zh: '排除' },
  'discover.intent.time': { en: 'Time', zh: '时间' },
  'discover.intent.restrict': { en: 'Sources', zh: '限定来源' },
  // ── discover: source tabs (DiscoverSourceTabs) ──
  'discover.tabs.aria': { en: 'Filter results by source', zh: '按来源筛选结果' },
  'discover.tabs.all': { en: 'All', zh: '全部' },
  'discover.tabs.source_error': { en: 'Source error', zh: '来源出错' },
  'discover.tabs.loading': { en: 'Loading', zh: '加载中' },
  // ── discover: source section (DiscoverSourceSection) ──
  'discover.sec.found': { en: 'found', zh: '条命中' },
  'discover.sec.add_manifest': { en: 'Add to manifest', zh: '加入下载清单' },
  'discover.sec.add_manifest.title': { en: 'Add all visible rows to manifest', zh: '将所有可见行加入下载清单' },
  'discover.sec.csv.title': { en: 'Download these rows as CSV', zh: '将这些行导出为 CSV' },
  'discover.sec.empty': { en: 'No matching datasets.', zh: '没有匹配的数据集。' },
  'discover.sec.col.title': { en: 'Title', zh: '标题' },
  'discover.sec.col.organism': { en: 'Organism', zh: '物种' },
  'discover.sec.col.samples': { en: 'Samples', zh: '样本' },
  'discover.sec.col.date': { en: 'Date', zh: '日期' },
  'discover.sec.col.actions': { en: 'Actions', zh: '操作' },
  'discover.sec.of': { en: 'of', zh: '共' },
  'discover.sec.prev': { en: 'Prev', zh: '上一页' },
  'discover.sec.next': { en: 'Next', zh: '下一页' },
  'discover.sec.mirror.title': { en: 'Same study in', zh: '同一研究见于' },
  'discover.sec.add_row.title': { en: 'Add to manifest', zh: '加入下载清单' },
  'discover.sec.remove_row.title': { en: 'Remove from manifest', zh: '从下载清单移除' },
  'discover.sec.toast.added_rows_1': { en: 'Added', zh: '已添加' },
  'discover.sec.toast.row': { en: 'row', zh: '行' },
  'discover.sec.toast.rows': { en: 'rows', zh: '行' },
  'discover.sec.toast.to_manifest': { en: 'to manifest', zh: '到下载清单' },
  'discover.sec.toast.added_row': { en: 'Added', zh: '已添加' },
  'discover.sec.toast.removed_row': { en: 'Removed', zh: '已移除' },
  'discover.sec.toast.from_manifest': { en: 'from manifest', zh: '从下载清单' },
  // ── advanced search: execution trace (ExecutionTrace) ──
  'trace.toast.copied': { en: 'SQL copied to clipboard', zh: 'SQL 已复制到剪贴板' },
  'trace.toast.copy_failed': { en: 'Copy failed — select the SQL manually', zh: '复制失败——请手动选择 SQL' },
  'trace.stage.parse': { en: 'Parse query', zh: '解析查询' },
  'trace.stage.reason': { en: 'Reason', zh: '推理' },
  'trace.stage.ontology': { en: 'Resolve ontology', zh: '解析本体' },
  'trace.stage.schema': { en: 'Schema lookup', zh: '查找表结构' },
  'trace.stage.sql_gen': { en: 'Generate SQL', zh: '生成 SQL' },
  'trace.stage.validate': { en: 'Validate SQL', zh: '校验 SQL' },
  'trace.stage.execute': { en: 'Execute SQL', zh: '执行 SQL' },
  'trace.stage.correct': { en: 'Self-correction', zh: '自我修正' },
  'trace.stage.fuse': { en: 'Cross-DB fusion', zh: '跨库融合' },
  'trace.stage.synthesize': { en: 'Synthesize answer', zh: '综合答案' },
  'trace.details': { en: 'Execution details', zh: '执行详情' },
  'trace.steps': { en: 'steps', zh: '个步骤' },
  'trace.selfcorrection': { en: 'self-correction', zh: '次自我修正' },
  'trace.selfcorrections': { en: 'self-corrections', zh: '次自我修正' },
  'trace.intent': { en: 'intent', zh: '意图' },
  'trace.method': { en: 'method', zh: '方法' },
  'trace.superseded': { en: 'superseded', zh: '已被取代' },
  'trace.db_terms': { en: 'db terms', zh: '个数据库词项' },
  'trace.fastpath': {
    en: 'Structured fast-path (no LLM trace). Filters were applied directly.',
    zh: '结构化快速通道(无 LLM 轨迹)。筛选条件已直接应用。',
  },
  'trace.final_sql': { en: 'Final SQL executed', zh: '最终执行的 SQL' },
  'trace.chars': { en: 'chars', zh: '字符' },
  'trace.copy': { en: 'Copy', zh: '复制' },
  'trace.copied': { en: 'Copied', zh: '已复制' },
  'trace.copy.aria': { en: 'Copy SQL to clipboard', zh: '复制 SQL 到剪贴板' },
  // ── advanced search: NL progress (NlProgress) ──
  'nlp.parsing.label': { en: 'Parsing your query', zh: '正在解析查询' },
  'nlp.parsing.hint': { en: 'The agent is reading your intent and picking out entities (~10-15 s).', zh: '智能体正在理解你的意图并提取实体(约 10–15 秒)。' },
  'nlp.resolving.label': { en: 'Resolving ontologies', zh: '正在解析本体' },
  'nlp.resolving.hint': { en: 'Expanding terms via UBERON / MONDO / CL / EFO.', zh: '通过 UBERON / MONDO / CL / EFO 扩展词项。' },
  'nlp.querying.label': { en: 'Running SQL against 943 K samples', zh: '正在对 94.3 万样本执行 SQL' },
  'nlp.querying.hint': { en: 'Generating + executing the candidate query plans.', zh: '正在生成并执行候选查询计划。' },
  'nlp.fusing.label': { en: 'De-duplicating across sources', zh: '正在跨来源去重' },
  'nlp.fusing.hint': { en: 'Cross-source rollup — almost done.', zh: '跨来源汇总——即将完成。' },
  'nlp.elapsed.aria': { en: 'elapsed seconds', zh: '已用秒数' },
  // ── advanced search: condition cards (ConditionCards) ──
  'cond.tissue': { en: 'Tissue', zh: '组织' },
  'cond.disease': { en: 'Disease', zh: '疾病' },
  'cond.assay': { en: 'Assay', zh: '实验技术' },
  'cond.organism': { en: 'Organism', zh: '物种' },
  'cond.db': { en: 'DB', zh: '数据库' },
  'cond.cell': { en: 'Cell', zh: '细胞' },
  'cond.sex': { en: 'Sex', zh: '性别' },
  'cond.min_cells': { en: 'Min Cells', zh: '最少细胞' },
  'cond.h5ad': { en: 'H5AD', zh: 'H5AD' },
  'cond.text': { en: 'Text', zh: '文本' },
  'cond.project': { en: 'Project', zh: '项目' },
  'cond.sample': { en: 'Sample', zh: '样本' },
  'cond.pmid': { en: 'PMID', zh: 'PMID' },
  'cond.clearall': { en: 'Clear all', zh: '全部清除' },
  'cond.remove.aria': { en: 'Remove filter', zh: '移除筛选' },
  // ── advanced search: aggregation result (AggregationResult) ──
  'agg.heading_1': { en: 'Aggregation —', zh: '聚合 —' },
  'agg.groups_by': { en: 'groups by', zh: '组,按' },
  'agg.total': { en: 'total', zh: '合计' },
  'agg.unspecified': { en: '(unspecified)', zh: '(未指定)' },
  'agg.samples': { en: 'Samples', zh: '样本' },
  'agg.chart.aria_1': { en: 'Bar chart: sample counts by', zh: '柱状图:样本数按' },
  'agg.chart.aria_groups': { en: 'groups.', zh: '组。' },
  'agg.chart.aria_top': { en: 'Top groups —', zh: '主要分组 —' },
  'agg.table.caption_1': { en: 'Data table for the bar chart above: sample counts by', zh: '上方柱状图的数据表:样本数按' },
  'agg.table.caption_2': { en: 'groups.', zh: '组。' },
  // ── advanced search: error card (SearchErrorCard) ──
  'err.timeout.title': { en: 'The agent didn’t answer in time', zh: '智能体未能及时响应' },
  'err.timeout.hint': {
    en: 'Cold-cache NL queries can take 60–90 s on the first call. Try again — the parser cache should make it instant the second time. If it times out again, simplify the query (one disease + one tissue) and retry.',
    zh: '冷缓存的自然语言查询首次可能需要 60–90 秒。请重试——解析缓存会让第二次几乎瞬时完成。若再次超时,请简化查询(一个疾病 + 一个组织)后重试。',
  },
  'err.server.title': { en: 'The server returned an error', zh: '服务器返回了错误' },
  'err.server.hint': {
    en: 'The backend hit an exception while running your query. Try again; if it persists, simplify the filters or check /scdbAPI/health.',
    zh: '后端在执行查询时发生异常。请重试;若持续出现,请简化筛选或检查 /scdbAPI/health。',
  },
  'err.network.title': { en: 'Could not reach the server', zh: '无法连接服务器' },
  'err.network.hint': {
    en: 'Network or the API process is offline. Check that the server is running and your VPN/tunnel is up, then retry.',
    zh: '网络或 API 进程已离线。请确认服务器正在运行、VPN/隧道已连通,然后重试。',
  },
  'err.parser.title': { en: 'Could not parse the query', zh: '无法解析查询' },
  'err.parser.hint': {
    en: 'The agent didn’t recognise the structure. Try a simpler phrasing — e.g. "lung COVID-19" instead of multi-clause natural language.',
    zh: '智能体未能识别查询结构。请尝试更简单的表述——例如用 “lung COVID-19” 代替多从句的自然语言。',
  },
  'err.unknown.title': { en: 'Search failed', zh: '检索失败' },
  'err.unknown.hint': {
    en: 'Try again; if it persists, simplify the query or check the server logs.',
    zh: '请重试;若持续出现,请简化查询或检查服务器日志。',
  },
  'err.original.aria': { en: 'Original error message', zh: '原始错误信息' },
  'err.tryagain': { en: 'Try again', zh: '重试' },
  'err.tryagain.aria': { en: 'Retry the last search', zh: '重试上一次检索' },
  'err.dismiss.aria': { en: 'Dismiss error banner', zh: '关闭错误提示' },
  // ── stats page (StatsPage) ──
  'stats.eyebrow': { en: 'Database statistics', zh: '数据库统计' },
  'stats.title': { en: 'A live snapshot of the unified catalog', zh: '统一目录的实时快照' },
  'stats.desc': {
    en: 'Sample counts, source coverage, tissue and disease distributions, recent submissions. Click any chart bar to filter Explore by that facet.',
    zh: '样本计数、来源覆盖、组织与疾病分布、近期提交。点击任意图表柱可按该维度筛选「浏览」。',
  },
  'stats.unavailable': { en: 'Statistics unavailable', zh: '统计数据不可用' },
  'stats.nodata': { en: 'No data returned.', zh: '未返回数据。' },
  'stats.load_failed': { en: 'Failed to load statistics:', zh: '加载统计数据失败：' },
  'stats.card.samples': { en: 'Samples', zh: '样本' },
  'stats.card.projects': { en: 'Projects', zh: '项目' },
  'stats.card.series': { en: 'Series', zh: '系列' },
  'stats.card.celltypes': { en: 'Cell types', zh: '细胞类型' },
  'stats.card.crosslinks': { en: 'Cross-links', zh: '交叉链接' },
  'stats.chart.by_source': { en: 'Samples by database', zh: '各数据库样本数' },
  'stats.chart.by_source.hint': { en: 'Click a bar to filter Explore.', zh: '点击柱条可筛选「浏览」。' },
  'stats.chart.tissue_system': { en: 'Tissue system distribution', zh: '组织系统分布' },
  'stats.chart.top_tissues': { en: 'Top 20 tissues', zh: '前 20 组织' },
  'stats.chart.disease_category': { en: 'Disease category distribution', zh: '疾病分类分布' },
  'stats.chart.top_diseases': { en: 'Top 20 diseases', zh: '前 20 疾病' },
  'stats.chart.sample_type': { en: 'Sample type distribution', zh: '样本类型分布' },
  'stats.chart.assay': { en: 'Assay distribution (annotated samples only)', zh: '实验技术分布(仅已标注样本)' },
  'stats.chart.by_year': { en: 'Submissions by year', zh: '历年提交' },
  'stats.quick.by_database': { en: 'Samples by database', zh: '各数据库样本数' },
  'stats.quick.by_database.hint': { en: 'see the curated-vs-live breakdown', zh: '查看精选与实时的对比' },
  'stats.quick.top_tissues': { en: 'Top tissues → Explore', zh: '主要组织 → 浏览' },
  'stats.chart.aria_suffix': { en: '(chart)', zh: '(图表)' },
  // ── projects / series page headers ──
  'projects.eyebrow': { en: 'Curated catalog', zh: '精选目录' },
  'projects.title': { en: 'Explore projects', zh: '浏览项目' },
  'projects.desc': {
    en: 'Browse published studies (full-text search over title / description / organism). Group-level metadata. Use Samples for cell-level filtering.',
    zh: '浏览已发表研究(对标题 / 描述 / 物种的全文检索)。研究级元数据。需要细胞级筛选时请用「样本」。',
  },
  'projects.sort.aria': { en: 'Sort projects', zh: '排序项目' },
  'projects.search.aria': { en: 'Search projects', zh: '搜索项目' },
  'projects.count': { en: 'projects', zh: '项目' },
  'projects.empty.title': { en: 'No projects match your filters.', zh: '没有项目符合当前筛选。' },
  'projects.empty.hint': {
    en: 'Try widening the source or organism filters, or clearing the search box.',
    zh: '尝试放宽来源或物种筛选,或清空搜索框。',
  },
  'projects.retry': { en: 'Retry', zh: '重试' },
  'series.eyebrow': { en: 'Curated catalog', zh: '精选目录' },
  'series.title': { en: 'Explore series', zh: '浏览系列' },
  'series.desc': {
    en: 'Browse individual sequencing series. Assay-level metadata, with file availability badges and download URLs where catalogued.',
    zh: '浏览单个测序系列。实验技术级元数据,附文件可用性标识及已收录的下载链接。',
  },
  'series.sort.aria': { en: 'Sort series', zh: '排序系列' },
  'series.search.aria': { en: 'Search series', zh: '搜索系列' },
  'series.count': { en: 'series', zh: '系列' },
  'series.empty.title': { en: 'No series match your filters.', zh: '没有系列符合当前筛选。' },
  'series.empty.hint': {
    en: 'Try widening the source / organism / assay filters.',
    zh: '尝试放宽来源 / 物种 / 实验技术筛选。',
  },
  'series.retry': { en: 'Retry', zh: '重试' },
  'series.top_platforms': { en: 'Top platforms', zh: '主要平台' },
  'series.project_label': { en: 'project:', zh: '项目：' },
  // ── common ──
  'common.samples': { en: 'samples', zh: '样本' },
  'common.cells': { en: 'cells', zh: '细胞' },
  'common.citations': { en: 'citations', zh: '引用' },
  'common.source': { en: 'Source', zh: '来源' },
  'common.projects': { en: 'projects', zh: '项目' },
  'common.series': { en: 'series', zh: '系列' },
  'common.yes': { en: 'Yes', zh: '是' },
  'common.no': { en: 'No', zh: '否' },
  'common.any': { en: 'Any', zh: '不限' },
  'common.datasets': { en: 'datasets', zh: '数据集' },
  'common.loading': { en: 'Loading…', zh: '加载中…' },
  'common.search': { en: 'Search', zh: '搜索' },
  'common.reset': { en: 'Reset', zh: '重置' },
  'common.filters': { en: 'Filters', zh: '筛选' },
};

interface Ctx {
  lang: Lang;
  setLang: (l: Lang) => void;
  t: (key: string, fallback?: string) => string;
}

const LanguageContext = createContext<Ctx | null>(null);

function detectInitialLang(): Lang {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved === 'en' || saved === 'zh') return saved;
    if (typeof navigator !== 'undefined' && navigator.language?.toLowerCase().startsWith('zh')) {
      return 'zh';
    }
  } catch {
    /* SSR / privacy mode — fall through */
  }
  return 'en';
}

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(detectInitialLang);

  const setLang = useCallback((l: Lang) => {
    setLangState(l);
    try {
      localStorage.setItem(STORAGE_KEY, l);
    } catch {
      /* ignore */
    }
    try {
      document.documentElement.lang = l === 'zh' ? 'zh-CN' : 'en';
    } catch {
      /* ignore */
    }
  }, []);

  const t = useCallback(
    (key: string, fallback?: string) => {
      const entry = DICT[key];
      return entry ? entry[lang] : fallback ?? key;
    },
    [lang],
  );

  return <LanguageContext.Provider value={{ lang, setLang, t }}>{children}</LanguageContext.Provider>;
}

// The provider (a component) and this hook live together by design — the context
// is private to the file. Fast-refresh's components-only rule doesn't apply.
// eslint-disable-next-line react-refresh/only-export-components
export function useT(): Ctx {
  const ctx = useContext(LanguageContext);
  // Safe default so a component used outside the provider (e.g. a test) still renders.
  if (!ctx) {
    return { lang: 'en', setLang: () => {}, t: (k: string, f?: string) => f ?? k };
  }
  return ctx;
}
