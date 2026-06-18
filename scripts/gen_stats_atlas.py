#!/usr/bin/env python3
"""Generate the Singligent "Catalog Atlas" — a publication-grade multi-panel
figure of the live catalog, in a top-journal (Nature/Cell) visual register.

Data: live /scdbAPI/stats/dashboard (real catalog, no synthetic data).
Style: clean left/bottom spines, dotted axis grid, restrained blue palette
matching the site accent, panel letters, no in-figure value clutter.
Output: web/public/stats/atlas.png (+ atlas_dark.png) at 200 DPI.
"""
from __future__ import annotations
import sys, json, urllib.request
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

API = "http://localhost:8000/scdbAPI/stats/dashboard"
OUT = "web/public/stats/atlas.png"

# ── Palette (site accent family + journal neutrals) ──
INK = "#1f2a37"; MUTE = "#5b6b7b"; GRID = "#b9c4d0"
BLUE = "#1B6FA8"; BLUE_D = "#13507c"; CYAN = "#38BDF8"; CORAL = "#e2683f"
SEQ = ["#0E3F63", "#15577F", "#1B6FA8", "#3E8AC0", "#69A8D4", "#9BC6E4"]

def fmt_k(x, _=None):
    x = float(x)
    if x >= 1e6: return f"{x/1e6:.1f}M".replace(".0M", "M")
    if x >= 1e3: return f"{x/1e3:.0f}K"
    return f"{x:.0f}"

def pretty(s: str) -> str:
    m = {"geo":"GEO","ega":"EGA","ncbi":"NCBI","ebi":"EBI","cellxgene":"CellxGene",
         "hca":"HCA","scea":"SCEA","htan":"HTAN","psychad":"PsychAD","sra":"SRA"}
    k = str(s).lower()
    if k in m: return m[k]
    s = str(s).replace("_", " ")
    return s[:1].upper() + s[1:]

def set_style():
    plt.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": 9,
        "axes.edgecolor": INK, "axes.linewidth": 0.8,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.titlesize": 10.5, "axes.titleweight": "bold", "axes.titlecolor": INK,
        "axes.labelsize": 8.5, "axes.labelcolor": MUTE,
        "xtick.color": MUTE, "ytick.color": INK, "xtick.labelsize": 7.5, "ytick.labelsize": 8,
        "xtick.major.size": 2.5, "ytick.major.size": 0, "xtick.major.width": 0.7,
        "figure.facecolor": "white", "axes.facecolor": "white", "savefig.facecolor": "white",
    })

def hbar(ax, labels, values, colors, log=False, title="", xlabel=""):
    y = range(len(labels))
    ax.barh(y, values, color=colors, height=0.72, zorder=3)
    ax.set_yticks(list(y)); ax.set_yticklabels(labels)
    ax.invert_yaxis()
    if log: ax.set_xscale("log")
    ax.xaxis.set_major_formatter(FuncFormatter(fmt_k))
    ax.grid(axis="x", linestyle=":", linewidth=0.7, color=GRID, alpha=0.6, zorder=0)
    ax.set_axisbelow(True)
    if title: ax.set_title(title, loc="left", pad=8)
    if xlabel: ax.set_xlabel(xlabel)
    ax.tick_params(left=False)

def panel_letter(ax, c):
    ax.text(-0.02, 1.06, c, transform=ax.transAxes, fontsize=13, fontweight="bold",
            color=INK, va="bottom", ha="right")

def main():
    raw = urllib.request.urlopen(API, timeout=15).read()
    d = json.loads(raw)
    set_style()
    fig, axes = plt.subplots(2, 3, figsize=(13.2, 7.4))
    (a, b, c), (e, f, g) = axes

    # (a) Samples by source
    src = sorted(d["by_source"], key=lambda x: x["samples"], reverse=True)
    labs = [pretty(s["name"]) for s in src]; vals = [s["samples"] for s in src]
    cols = [CYAN if i == 0 else BLUE for i in range(len(labs))]
    hbar(a, labs, vals, cols, title="Samples by source", xlabel="samples")
    panel_letter(a, "a")

    # (b) Organ-system coverage (log)
    ts = sorted(d["by_tissue_system"], key=lambda x: x["count"], reverse=True)[:12]
    labs = [pretty(s["value"]) for s in ts]; vals = [s["count"] for s in ts]
    hbar(b, labs, vals, [BLUE] * len(labs), log=True,
         title="Biological coverage — organ system", xlabel="samples (log scale)")
    panel_letter(b, "b")

    # (c) Disease category
    dc = sorted(d["by_disease_category"], key=lambda x: x["count"], reverse=True)[:12]
    labs = [pretty(s["value"]) for s in dc]; vals = [s["count"] for s in dc]
    cols = [CORAL if i == 0 else BLUE for i in range(len(labs))]
    hbar(c, labs, vals, cols, title="Disease category", xlabel="samples")
    panel_letter(c, "c")

    # (e) Assay / modality (top 12)
    asy = sorted(d["by_assay"], key=lambda x: x["count"], reverse=True)[:12]
    labs = [pretty(s["value"]) for s in asy]; vals = [s["count"] for s in asy]
    hbar(e, labs, vals, [BLUE] * len(labs), title="Assay / platform", xlabel="samples")
    panel_letter(e, "e")

    # (f) Cumulative growth over time
    yrs = sorted([x for x in d["submissions_by_year"] if str(x["year"]).isdigit()],
                 key=lambda x: int(x["year"]))
    years = [int(x["year"]) for x in yrs]
    cum = []
    s = 0
    for x in yrs:
        s += x["count"]; cum.append(s)
    f.fill_between(years, cum, color=BLUE, alpha=0.18, zorder=2)
    f.plot(years, cum, color=BLUE_D, linewidth=2.0, zorder=3)
    f.scatter([years[-1]], [cum[-1]], color=CYAN, s=22, zorder=4)
    f.yaxis.set_major_formatter(FuncFormatter(fmt_k))
    f.grid(axis="y", linestyle=":", linewidth=0.7, color=GRID, alpha=0.6, zorder=0)
    f.set_axisbelow(True)
    f.set_title("Cumulative projects over time", loc="left", pad=8)
    f.set_xlabel("submission year"); f.set_ylabel("projects (cumulative)")
    panel_letter(f, "f")

    # (g) Literature & cross-archive linkage (FAIR) — project-level %
    proj = d["total_projects"] or 1
    items = [("PMID-linked", d.get("with_pmid", 0) / proj * 100),
             ("DOI-linked", d.get("with_doi", 0) / proj * 100)]
    labs = [i[0] for i in items]; vals = [i[1] for i in items]
    yy = range(len(labs))
    g.barh(yy, vals, color=[BLUE, CYAN], height=0.55, zorder=3)
    g.set_yticks(list(yy)); g.set_yticklabels(labs); g.invert_yaxis()
    g.set_xlim(0, 100)
    g.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.0f}%"))
    g.grid(axis="x", linestyle=":", linewidth=0.7, color=GRID, alpha=0.6, zorder=0)
    g.set_axisbelow(True); g.tick_params(left=False)
    for i, v in enumerate(vals):
        g.text(v + 2, i, f"{v:.0f}%", va="center", ha="left", fontsize=8, color=MUTE)
    g.set_title("Literature linkage (per project)", loc="left", pad=8)
    g.set_xlabel("% of projects")
    panel_letter(g, "g")

    fig.tight_layout(w_pad=2.4, h_pad=3.0)
    import os
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    fig.savefig(OUT, dpi=200, bbox_inches="tight", pad_inches=0.15)
    print("wrote", OUT)

if __name__ == "__main__":
    sys.exit(main())
