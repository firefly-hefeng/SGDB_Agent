#!/usr/bin/env Rscript
#
# R可视化脚本 - 生成高质量的科学图表
# R Visualization Script for Scientific Figures
#
# 使用说明:
#   Rscript 04_visualization_r.R
#
# 依赖包:
#   tidyverse, ggplot2, patchwork, RColorBrewer, viridis, 
#   ggrepel, treemapify, ggridges, plotly (可选)

# ============================================================
# 设置和加载包
# ============================================================

suppressPackageStartupMessages({
  library(tidyverse)
  library(ggplot2)
  library(patchwork)
  library(RColorBrewer)
  library(viridis)
  library(ggrepel)
  library(scales)
})

# 设置主题
theme_scientific <- function() {
  theme_minimal(base_family = "Helvetica", base_size = 10) +
    theme(
      plot.title = element_text(face = "bold", size = 12, hjust = 0.5),
      plot.subtitle = element_text(size = 9, color = "gray40"),
      axis.title = element_text(face = "bold", size = 9),
      axis.text = element_text(size = 8),
      legend.title = element_text(face = "bold", size = 9),
      legend.text = element_text(size = 8),
      panel.grid.minor = element_blank(),
      panel.grid.major = element_line(color = "gray90", size = 0.2),
      strip.text = element_text(face = "bold", size = 9),
      plot.margin = margin(10, 10, 10, 10)
    )
}

# 科学配色方案
colors_sci <- c(
  "#2E86AB", "#A23B72", "#F18F01", "#C73E1D", "#06A77D",
  "#8B5CF6", "#EC4899", "#14B8A6", "#F59E0B", "#6366F1"
)

# 路径设置
DATA_DIR <- "../02_data"
RESULTS_DIR <- "../04_results"
FIGURES_DIR <- "../05_figures"

# 确保输出目录存在
dir.create(FIGURES_DIR, showWarnings = FALSE, recursive = TRUE)

# ============================================================
# 数据加载函数
# ============================================================

load_data <- function() {
  message("[R] 加载数据...")
  
  samples <- read_csv(file.path(DATA_DIR, "03_samples.csv"), show_col_types = FALSE)
  projects <- read_csv(file.path(DATA_DIR, "01_projects.csv"), show_col_types = FALSE)
  series <- read_csv(file.path(DATA_DIR, "02_series.csv"), show_col_types = FALSE)
  
  # 加载JSON结果
  quality_results <- jsonlite::fromJSON(file.path(RESULTS_DIR, "data_quality_assessment_results.json"))
  meta_results <- jsonlite::fromJSON(file.path(RESULTS_DIR, "meta_analysis_results.json"))
  
  message("[R] 数据加载完成")
  
  list(samples = samples, projects = projects, series = series, 
       quality = quality_results, meta = meta_results)
}

# ============================================================
# Figure 1: 数据质量评估
# ============================================================

create_figure1_r <- function(data) {
  message("[R] 创建 Figure 1: 数据质量评估...")
  
  # A. 数据源分布（饼图）
  p1 <- data$samples %>%
    count(source_database) %>%
    slice_max(n, n = 6) %>%
    mutate(percentage = n / sum(n) * 100) %>%
    ggplot(aes(x = "", y = n, fill = source_database)) +
    geom_bar(stat = "identity", width = 1, color = "white") +
    coord_polar("y") +
    scale_fill_manual(values = colors_sci) +
    labs(title = "A. Data Source Distribution", fill = "Source") +
    theme_void() +
    theme(legend.position = "right", legend.text = element_text(size = 8))
  
  # B. 字段填充率（条形图）
  completeness_data <- data$quality$completeness$field_completeness$samples %>%
    bind_rows() %>%
    mutate(field = names(data$quality$completeness$field_completeness$samples)) %>%
    filter(field %in% c("organism", "tissue", "cell_type", "disease", "sex", "age", 
                        "development_stage", "individual_id", "n_cells"))
  
  p2 <- completeness_data %>%
    mutate(color = case_when(
      rate >= 70 ~ "#06A77D",
      rate >= 50 ~ "#F18F01",
      TRUE ~ "#C73E1D"
    )) %>%
    ggplot(aes(x = reorder(field, rate), y = rate, fill = color)) +
    geom_bar(stat = "identity", show.legend = FALSE) +
    geom_text(aes(label = sprintf("%.1f%%", rate)), hjust = -0.1, size = 3) +
    scale_fill_identity() +
    coord_flip() +
    scale_y_continuous(limits = c(0, 105), expand = c(0, 0)) +
    geom_vline(xintercept = 70, linetype = "dashed", color = "gray50") +
    labs(title = "B. Metadata Field Completeness",
         x = NULL, y = "Completeness (%)") +
    theme_scientific()
  
  # C. 年度数据产量
  year_data <- data$projects %>%
    mutate(year = as.numeric(format(as.Date(publication_date, format = "%Y-%m-%d"), "%Y"))) %>%
    filter(year >= 2015, year <= 2024) %>%
    count(year)
  
  p3 <- year_data %>%
    ggplot(aes(x = year, y = n)) +
    geom_area(fill = colors_sci[1], alpha = 0.3) +
    geom_line(color = colors_sci[1], size = 1) +
    geom_point(color = colors_sci[1], size = 2) +
    labs(title = "C. Project Publication Timeline",
         x = "Year", y = "Number of Projects") +
    theme_scientific()
  
  # D. 质量评分（仪表盘风格）
  scores <- data$quality$quality_scores
  score_data <- data.frame(
    category = c("Completeness", "Consistency", "Accuracy"),
    score = c(scores$completeness, scores$consistency, scores$accuracy)
  )
  
  p4 <- score_data %>%
    ggplot(aes(x = category, y = score, fill = category)) +
    geom_bar(stat = "identity", show.legend = FALSE) +
    geom_text(aes(label = sprintf("%.0f", score)), vjust = -0.5, size = 4, fontface = "bold") +
    scale_fill_manual(values = colors_sci[1:3]) +
    scale_y_continuous(limits = c(0, 100)) +
    labs(title = sprintf("D. Quality Score (Total: %.1f)", scores$total),
         x = NULL, y = "Score") +
    theme_scientific() +
    theme(axis.text.x = element_text(angle = 30, hjust = 1))
  
  # 组合
  fig1 <- (p1 + p2) / (p3 + p4) +
    plot_annotation(
      title = "Figure 1: Data Quality Assessment and Global Overview",
      theme = theme(plot.title = element_text(face = "bold", size = 14, hjust = 0.5))
    )
  
  ggsave(file.path(FIGURES_DIR, "Figure1_Quality_Assessment_R.png"), 
         fig1, width = 14, height = 10, dpi = 300)
  message("[R] Figure 1 已保存")
}

# ============================================================
# Figure 2: 数据共享与影响力
# ============================================================

create_figure2_r <- function(data) {
  message("[R] 创建 Figure 2: 数据共享与影响力...")
  
  # 模拟引用数据（基于实际统计）
  set.seed(42)
  citation_data <- data$samples %>%
    left_join(
      data$projects %>% select(pk, citation_count, publication_date),
      by = c("project_pk" = "pk")
    ) %>%
    mutate(
      citation_count = as.numeric(citation_count),
      year = as.numeric(format(as.Date(publication_date), "%Y")),
      access_type = ifelse(source_database == "cellxgene", "Open", "Controlled")
    ) %>%
    filter(!is.na(citation_count), year >= 2017, year <= 2024)
  
  # A. 引用分布对比（小提琴图）
  p1 <- citation_data %>%
    ggplot(aes(x = access_type, y = citation_count, fill = access_type)) +
    geom_violin(alpha = 0.7, show.legend = FALSE) +
    geom_boxplot(width = 0.1, fill = "white", outlier.size = 0.5) +
    scale_y_log10(labels = comma_format()) +
    scale_fill_manual(values = c("Open" = colors_sci[5], "Controlled" = colors_sci[3])) +
    labs(title = "A. Citation Distribution by Access Type",
         x = NULL, y = "Citation Count (log scale)") +
    theme_scientific()
  
  # B. 年度引用趋势
  year_citation <- citation_data %>%
    group_by(year) %>%
    summarise(mean_cit = mean(citation_count, na.rm = TRUE),
              median_cit = median(citation_count, na.rm = TRUE))
  
  p2 <- year_citation %>%
    ggplot(aes(x = year)) +
    geom_line(aes(y = mean_cit, color = "Mean"), size = 1) +
    geom_point(aes(y = mean_cit, color = "Mean"), size = 2) +
    geom_line(aes(y = median_cit, color = "Median"), size = 1, linetype = "dashed") +
    geom_point(aes(y = median_cit, color = "Median"), size = 2) +
    scale_color_manual(values = c("Mean" = colors_sci[1], "Median" = colors_sci[2])) +
    labs(title = "B. Citation Trends Over Time",
         x = "Year", y = "Citation Count", color = NULL) +
    theme_scientific()
  
  # C. 数据源引用比较
  db_citation <- citation_data %>%
    filter(!is.na(source_database)) %>%
    group_by(source_database) %>%
    summarise(mean_cit = mean(citation_count, na.rm = TRUE),
              n = n()) %>%
    filter(n >= 100) %>%
    slice_max(mean_cit, n = 5)
  
  p3 <- db_citation %>%
    ggplot(aes(x = reorder(source_database, mean_cit), y = mean_cit, fill = source_database)) +
    geom_bar(stat = "identity", show.legend = FALSE) +
    geom_text(aes(label = sprintf("n=%s", format(n, big.mark = ","))), 
              hjust = -0.1, size = 3) +
    coord_flip() +
    scale_fill_manual(values = colors_sci) +
    labs(title = "C. Citations by Data Source",
         x = NULL, y = "Mean Citation Count") +
    theme_scientific()
  
  # D. 累积数据增长
  cumulative_data <- data$samples %>%
    left_join(
      data$projects %>% select(pk, publication_date),
      by = c("project_pk" = "pk")
    ) %>%
    mutate(year = as.numeric(format(as.Date(publication_date), "%Y"))) %>%
    filter(year >= 2017, year <= 2024) %>%
    count(year) %>%
    mutate(cumulative = cumsum(n))
  
  p4 <- cumulative_data %>%
    ggplot(aes(x = year, y = cumulative)) +
    geom_area(fill = colors_sci[1], alpha = 0.3) +
    geom_line(color = colors_sci[1], size = 1) +
    geom_point(color = colors_sci[1], size = 3) +
    scale_y_continuous(labels = comma_format()) +
    labs(title = "D. Data Accumulation Over Time",
         x = "Year", y = "Cumulative Sample Count") +
    theme_scientific()
  
  # 组合
  fig2 <- (p1 + p2) / (p3 + p4) +
    plot_annotation(
      title = "Figure 2: Data Sharing and Scientific Impact",
      theme = theme(plot.title = element_text(face = "bold", size = 14, hjust = 0.5))
    )
  
  ggsave(file.path(FIGURES_DIR, "Figure2_Data_Sharing_Impact_R.png"), 
         fig2, width = 14, height = 10, dpi = 300)
  message("[R] Figure 2 已保存")
}

# ============================================================
# Figure 3: 技术演进
# ============================================================

create_figure3_r <- function(data) {
  message("[R] 创建 Figure 3: 技术演进...")
  
  # 准备数据
  tech_data <- data$samples %>%
    left_join(
      data$series %>% select(pk, assay),
      by = c("series_pk" = "pk")
    ) %>%
    left_join(
      data$projects %>% select(pk, publication_date),
      by = c("project_pk" = "pk")
    ) %>%
    mutate(
      year = as.numeric(format(as.Date(publication_date), "%Y")),
      assay_category = case_when(
        str_detect(tolower(assay), "10x|chromium") ~ "10x Genomics",
        str_detect(tolower(assay), "smart-seq") ~ "Smart-seq",
        TRUE ~ "Other"
      )
    ) %>%
    filter(year >= 2017, year <= 2024)
  
  # A. 技术平台分布（环形图）
  p1 <- tech_data %>%
    count(assay_category) %>%
    ggplot(aes(x = "", y = n, fill = assay_category)) +
    geom_bar(stat = "identity", width = 1, color = "white") +
    coord_polar("y") +
    scale_fill_manual(values = colors_sci) +
    labs(title = "A. Technology Platform Distribution", fill = "Platform") +
    theme_void() +
    theme(legend.position = "right")
  
  # B. 细胞产出分布（小提琴图）
  p2 <- tech_data %>%
    filter(assay_category %in% c("10x Genomics", "Smart-seq", "Other"),
           !is.na(n_cells), n_cells > 0, n_cells < 100000) %>%
    ggplot(aes(x = assay_category, y = n_cells, fill = assay_category)) +
    geom_violin(alpha = 0.7, show.legend = FALSE) +
    geom_boxplot(width = 0.1, fill = "white", outlier.size = 0.5) +
    scale_y_log10(labels = comma_format()) +
    scale_fill_manual(values = colors_sci) +
    labs(title = "B. Cell Yield by Platform",
         x = NULL, y = "Number of Cells (log scale)") +
    theme_scientific()
  
  # C. 技术采纳趋势（堆叠面积图）
  trend_data <- tech_data %>%
    count(year, assay_category) %>%
    group_by(year) %>%
    mutate(percentage = n / sum(n) * 100)
  
  p3 <- trend_data %>%
    ggplot(aes(x = year, y = percentage, fill = assay_category)) +
    geom_area(alpha = 0.8) +
    scale_fill_manual(values = colors_sci) +
    labs(title = "C. Technology Adoption Trends",
         x = "Year", y = "Percentage (%)", fill = "Platform") +
    theme_scientific()
  
  # 组合
  fig3 <- (p1 + p2) / p3 +
    plot_annotation(
      title = "Figure 3: Technology Evolution and Data Characteristics",
      theme = theme(plot.title = element_text(face = "bold", size = 14, hjust = 0.5))
    )
  
  ggsave(file.path(FIGURES_DIR, "Figure3_Technology_Evolution_R.png"), 
         fig3, width = 14, height = 10, dpi = 300)
  message("[R] Figure 3 已保存")
}

# ============================================================
# Figure 4: 疾病与样本特征
# ============================================================

create_figure4_r <- function(data) {
  message("[R] 创建 Figure 4: 疾病景观与样本特征...")
  
  # 疾病分类
  disease_data <- data$samples %>%
    mutate(
      disease_category = case_when(
        is.na(disease) ~ "Not specified",
        str_detect(tolower(disease), "normal|healthy|control") ~ "Normal/Healthy",
        str_detect(tolower(disease), "cancer|carcinoma|tumor|melanoma|leukemia") ~ "Cancer",
        str_detect(tolower(disease), "covid|sars-cov") ~ "COVID-19",
        str_detect(tolower(disease), "diabetes|t1d|t2d") ~ "Diabetes",
        str_detect(tolower(disease), "alzheimer|parkinson|dementia|epilepsy") ~ "Neurological",
        TRUE ~ "Other Disease"
      )
    )
  
  # A. 疾病分布（水平条形图）
  p1 <- disease_data %>%
    count(disease_category) %>%
    mutate(pct = n / sum(n) * 100) %>%
    ggplot(aes(x = reorder(disease_category, n), y = n, fill = disease_category)) +
    geom_bar(stat = "identity", show.legend = FALSE) +
    geom_text(aes(label = sprintf("%.1f%%", pct)), hjust = -0.1, size = 3) +
    coord_flip() +
    scale_fill_manual(values = colors_sci) +
    labs(title = "A. Disease Category Distribution",
         x = NULL, y = "Sample Count") +
    theme_scientific()
  
  # B. 性别分布（环形图）
  p2 <- data$samples %>%
    mutate(sex_clean = ifelse(sex %in% c("male", "female"), sex, "unknown")) %>%
    count(sex_clean) %>%
    ggplot(aes(x = "", y = n, fill = sex_clean)) +
    geom_bar(stat = "identity", width = 1, color = "white") +
    coord_polar("y") +
    scale_fill_manual(values = c("female" = colors_sci[2], 
                                  "male" = colors_sci[1], 
                                  "unknown" = colors_sci[5])) +
    labs(title = "B. Sex Distribution", fill = "Sex") +
    theme_void()
  
  # C. 年龄分布（直方图）
  p3 <- data$samples %>%
    mutate(age_num = as.numeric(age)) %>%
    filter(age_num >= 0, age_num <= 120, !is.na(age_num)) %>%
    ggplot(aes(x = age_num)) +
    geom_histogram(bins = 30, fill = colors_sci[1], alpha = 0.7, color = "white") +
    geom_vline(aes(xintercept = median(age_num)), color = colors_sci[4], 
               linetype = "dashed", size = 1) +
    annotate("text", x = median(as.numeric(data$samples$age), na.rm = TRUE) + 5, 
             y = Inf, label = sprintf("Median: %.0f", median(as.numeric(data$samples$age), na.rm = TRUE)),
             vjust = 2, size = 3, color = colors_sci[4]) +
    labs(title = "C. Age Distribution",
         x = "Age (years)", y = "Count") +
    theme_scientific()
  
  # D. 组织分布（Top 10）
  p4 <- data$samples %>%
    filter(!is.na(tissue)) %>%
    count(tissue) %>%
    slice_max(n, n = 10) %>%
    ggplot(aes(x = reorder(tissue, n), y = n)) +
    geom_bar(stat = "identity", fill = colors_sci[3], color = "white") +
    coord_flip() +
    labs(title = "D. Top 10 Tissues",
         x = NULL, y = "Sample Count") +
    theme_scientific()
  
  # 组合
  fig4 <- (p1 + p2) / (p3 + p4) +
    plot_annotation(
      title = "Figure 4: Disease Landscape and Sample Characteristics",
      theme = theme(plot.title = element_text(face = "bold", size = 14, hjust = 0.5))
    )
  
  ggsave(file.path(FIGURES_DIR, "Figure4_Disease_Sample_Characteristics_R.png"), 
         fig4, width = 14, height = 10, dpi = 300)
  message("[R] Figure 4 已保存")
}

# ============================================================
# Figure 5: 时间动态
# ============================================================

create_figure5_r <- function(data) {
  message("[R] 创建 Figure 5: 时间动态...")
  
  # 准备数据
  temporal_data <- data$samples %>%
    left_join(
      data$projects %>% select(pk, publication_date),
      by = c("project_pk" = "pk")
    ) %>%
    mutate(year = as.numeric(format(as.Date(publication_date), "%Y"))) %>%
    filter(year >= 2015, year <= 2024)
  
  # A. 年度样本产量
  p1 <- temporal_data %>%
    count(year) %>%
    ggplot(aes(x = year, y = n)) +
    geom_bar(stat = "identity", fill = colors_sci[1], alpha = 0.7, color = "white") +
    geom_smooth(method = "loess", color = colors_sci[4], se = FALSE, size = 1) +
    labs(title = "A. Annual Sample Production",
         x = "Year", y = "Sample Count") +
    theme_scientific()
  
  # B. 累积数据增长
  p2 <- temporal_data %>%
    count(year) %>%
    mutate(cumulative = cumsum(n)) %>%
    ggplot(aes(x = year, y = cumulative)) +
    geom_area(fill = colors_sci[2], alpha = 0.3) +
    geom_line(color = colors_sci[2], size = 1) +
    geom_point(color = colors_sci[2], size = 3) +
    scale_y_continuous(labels = comma_format()) +
    labs(title = "B. Cumulative Data Growth",
         x = "Year", y = "Cumulative Samples") +
    theme_scientific()
  
  # C. COVID-19影响
  covid_data <- temporal_data %>%
    mutate(
      is_respiratory = str_detect(tolower(tissue), "lung|respiratory|bronchial"),
      period = case_when(
        year %in% c(2018, 2019) ~ "Pre-COVID",
        year %in% c(2020, 2021) ~ "COVID Period",
        TRUE ~ "Other"
      )
    ) %>%
    filter(period != "Other", is_respiratory) %>%
    count(year, period)
  
  p3 <- covid_data %>%
    ggplot(aes(x = factor(year), y = n, fill = period)) +
    geom_bar(stat = "identity", show.legend = FALSE) +
    scale_fill_manual(values = c("Pre-COVID" = colors_sci[5], 
                                  "COVID Period" = colors_sci[4])) +
    labs(title = "C. COVID-19 Impact on Respiratory Research",
         x = "Year", y = "Sample Count") +
    theme_scientific()
  
  # D. 元数据质量趋势
  quality_trend <- temporal_data %>%
    mutate(
      completeness = (
        !is.na(tissue) + !is.na(cell_type) + !is.na(disease) + 
        !is.na(sex) + !is.na(age)
      ) / 5 * 100
    ) %>%
    group_by(year) %>%
    summarise(mean_completeness = mean(completeness, na.rm = TRUE))
  
  p4 <- quality_trend %>%
    ggplot(aes(x = year, y = mean_completeness)) +
    geom_line(color = colors_sci[5], size = 1) +
    geom_point(color = colors_sci[5], size = 3) +
    geom_hline(yintercept = 70, linetype = "dashed", color = "gray50") +
    scale_y_continuous(limits = c(0, 100)) +
    labs(title = "D. Data Quality Trend",
         x = "Year", y = "Metadata Completeness (%)") +
    theme_scientific()
  
  # 组合
  fig5 <- (p1 + p2) / (p3 + p4) +
    plot_annotation(
      title = "Figure 5: Temporal Dynamics and Data Growth",
      theme = theme(plot.title = element_text(face = "bold", size = 14, hjust = 0.5))
    )
  
  ggsave(file.path(FIGURES_DIR, "Figure5_Temporal_Dynamics_R.png"), 
         fig5, width = 14, height = 10, dpi = 300)
  message("[R] Figure 5 已保存")
}

# ============================================================
# 主函数
# ============================================================

main <- function() {
  message("=" %>% rep(60) %>% paste(collapse = ""))
  message("R 可视化生成")
  message("=" %>% rep(60) %>% paste(collapse = ""))
  
  # 加载数据
  data <- load_data()
  
  # 生成所有图表
  create_figure1_r(data)
  create_figure2_r(data)
  create_figure3_r(data)
  create_figure4_r(data)
  create_figure5_r(data)
  
  message("=" %>% rep(60) %>% paste(collapse = ""))
  message("所有R图表已生成！保存位置:")
  list.files(FIGURES_DIR, pattern = "_R\\.png$", full.names = FALSE) %>% 
    sapply(function(f) {
      size <- file.size(file.path(FIGURES_DIR, f)) / 1024 / 1024
      message(sprintf("  - %s (%.2f MB)", f, size))
    })
  message("=" %>% rep(60) %>% paste(collapse = ""))
}

# 运行
main()
