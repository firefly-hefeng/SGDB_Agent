# SCeQTL Portal — UI 优化设计方案

> 日期: 2026-03-18
> 版本: v2.1
> 参考: CellxGene Discover, UCSC Cell Browser, Human Cell Atlas, Vercel, Linear

---

## 一、已知问题修复

### 1. 搜索框图标与文字重叠
- **位置**: `TopNav.tsx` 全局搜索框、`SearchBar.tsx` Explore搜索框
- **原因**: TopNav 搜索框 icon `left-2.5` + input `pl-8`，在小屏幕下数字/文字与放大镜图标重叠
- **修复**: 统一所有搜索框 icon `left-3`，input `pl-9`，确保 36px 左内边距

### 2. App.tsx 背景变量缺失
- **问题**: `bg-[var(--bg-secondary)]` 未在 CSS 中定义
- **修复**: 改为 `bg-[var(--bg-page)]`

---

## 二、配色方案优化

### 设计理念
参考 CellxGene 的科学感配色 + Linear 的精致感。从纯灰色系升级为带有科学蓝调的冷色系。

### 新配色 (CSS Variables 更新)

```
主色调: 从 #2563eb (标准蓝) → #1e6bb8 (科学蓝，更沉稳专业)
辅助色: #0ea5e9 (天蓝，用于交互高亮)
背景色: #f8fafc (微蓝灰，替代纯灰 #f9fafb)
卡片色: #ffffff (保持白色)
导航栏: #0f172a (深蓝黑，替代白色，增加专业感)
```

### 语义色调整
```
success: #10b981 (翡翠绿，更现代)
warning: #f59e0b (琥珀，保持)
error:   #ef4444 (红色，稍亮)
info:    #06b6d4 (青色，新增)
```

### Badge 配色微调
保持现有 10 色系，但统一降低饱和度 10%，使整体更协调：
- badge-blue: #dbeafe/#1e40af → #e0f0ff/#1a5490
- badge-green: #dcfce7/#166534 → #e0f5e8/#14713a
- 其余类推，整体更柔和

---

## 三、导航栏 (TopNav) 重设计

### 当前问题
- 白色背景缺乏辨识度，与内容区分不明显
- 搜索框太窄 (220px)

### 新设计
- **深色导航栏**: 背景 `#0f172a` (slate-900)，文字白色
- **Logo 区域**: 左侧放置 SVG logo 占位 + "SCeQTL" 文字，字体 Inter/系统字体
- **导航项**: 白色文字，active 状态底部 2px accent 线
- **搜索框**: 宽度 280px，半透明背景 `rgba(255,255,255,0.08)`，白色文字
- **右侧**: 数据库统计 badge "756K samples"

### 占位 Logo
生成一个简明的 SVG 占位 logo：DNA 双螺旋 + 数据节点的抽象图形

---

## 四、Landing Page 优化

### Hero Section
- **背景**: 从纯白改为微妙渐变 `linear-gradient(135deg, #0f172a 0%, #1e3a5f 50%, #0f172a 100%)`
- **文字**: 白色标题，浅灰副标题
- **搜索框**: 白色背景，更大的圆角 (12px)，更明显的阴影
- **分类标签**: 半透明白色背景 `rgba(255,255,255,0.15)`，白色文字
- **装饰**: 背景添加抽象的细胞/数据点 SVG 图案 (低透明度)

### QuickStats 卡片
- 添加左侧彩色竖线 (4px) 区分每个指标
- 数字使用 tabular-nums + 更大字号
- 添加微妙的图标 (Database, FlaskConical, Dna, Microscope)

### DatabaseCards
- 左侧彩色竖线替代圆点
- hover 时左侧竖线扩展为全边框
- 添加数据库 logo 占位图 (24x24 SVG)

### RecentHighlights
- 添加缩略图占位 (组织类型对应的简笔画 SVG)
- 卡片底部添加 "View Details →" 链接

---

## 五、Explore Page 优化

### FacetSidebar
- 顶部添加 "Filters" 标题 + 折叠按钮
- 每个 facet 组添加对应图标 (Microscope→tissue, Bug→disease 等)
- 选中项数量 badge
- 底部 "Reset All" 按钮

### ResultsTable
- 行 hover 效果: 左侧 3px accent 线
- 选中行: 浅蓝背景
- source_database 列: 彩色圆点 + 文字 (参考 DatabaseCards 配色)
- 数字列右对齐 + tabular-nums

### SearchBar
- 模式切换按钮添加 tooltip
- NL 模式添加 sparkle/AI 图标替代 MessageSquare

---

## 六、Advanced Search Page 优化

### NL 输入框
- 更大的输入框 (py-3)
- 左侧 Sparkles 图标 (替代 Search，表示 AI 功能)
- 右侧显示 "Powered by Kimi" 小标签

### Condition Cards
- 每个 card 添加对应字段图标
- 拖拽排序 (未来)
- 编辑模式: 点击 card 展开编辑

### SqlPreview
- 使用 code-block 样式 (深色背景)
- SQL 语法高亮 (关键字蓝色，字符串绿色，数字橙色)

---

## 七、Statistics Page 优化

### 图表配色
统一使用科学配色方案 (参考 Nature/Science 论文配色):
```
palette: ['#1e6bb8', '#10b981', '#f59e0b', '#8b5cf6', '#ef4444',
          '#ec4899', '#06b6d4', '#84cc16', '#f97316', '#6366f1']
```

### 图表样式
- 圆角柱状图 (已有)
- 网格线: 虚线 + 更浅颜色
- Tooltip: 添加阴影，更圆润
- 饼图: 改为环形图 (donut)，中心显示总数

---

## 八、全局样式优化

### 字体
- 标题: Inter (如可用) 或系统字体
- 正文: 系统字体栈 (保持)
- 代码: "JetBrains Mono", "SF Mono", monospace

### 间距
- 页面最大宽度: 1200px → 1120px (更紧凑)
- 卡片内边距: 统一 p-5 (20px)
- 组件间距: 统一 gap-4 (16px)

### 动效
- 页面切换: fade-in 200ms
- 卡片 hover: translateY(-1px) + shadow 提升
- 按钮 hover: 微妙的亮度变化
- 加载状态: 骨架屏 shimmer (已有)

### 无障碍
- 所有交互元素 focus-visible 样式 (已有)
- 颜色对比度 ≥ 4.5:1 (WCAG AA)
- 按钮最小点击区域 44x44px

---

## 九、需要生成的占位图片

| 编号 | 用途 | 规格 | 描述 |
|------|------|------|------|
| 1 | Logo | 32x32 SVG | DNA双螺旋+数据节点抽象图 |
| 2 | Hero 背景图案 | 全宽 SVG pattern | 抽象细胞/数据点网络 |
| 3 | 数据库图标 x8 | 24x24 SVG each | GEO/NCBI/EBI/CellxGene/HCA/HTAN/PanglaoDB/SCEA |
| 4 | 组织图标 x6 | 20x20 SVG each | brain/liver/lung/blood/kidney/heart |
| 5 | 空状态插图 | 200x160 SVG | 搜索无结果时的友好插图 |
| 6 | Facet 图标 x7 | 16x16 SVG each | tissue/disease/assay/organism/source/cell_type/sex |

---

## 十、实施优先级

| 优先级 | 任务 | 影响范围 |
|--------|------|----------|
| P0 | 搜索框重叠修复 | TopNav, SearchBar |
| P0 | App.tsx 背景变量修复 | 全局 |
| P1 | 配色方案更新 (index.css) | 全局 |
| P1 | 深色导航栏 | TopNav |
| P1 | Hero Section 深色背景 | LandingPage |
| P2 | 占位 SVG 图标生成 | Logo, DB icons, facet icons |
| P2 | QuickStats 图标+竖线 | LandingPage |
| P2 | ResultsTable 行效果 | ExplorePage, AdvancedSearchPage |
| P3 | 图表配色统一 | StatsPage |
| P3 | SqlPreview 语法高亮 | AdvancedSearchPage |
| P3 | 空状态插图 | 多页面 |
