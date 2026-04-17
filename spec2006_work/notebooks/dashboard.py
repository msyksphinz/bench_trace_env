# %% [markdown]
# # SPEC CPU2006 Sniper SimPoint — Bottleneck Analysis Dashboard
#
# Run this file in VS Code Python Interactive mode.
# Execute each `# %%` cell with Shift+Enter, or use "Run All Cells".
#
# **Requirements**
# - VS Code Python extension + Jupyter extension installed
# - Working directory: `spec2006_work/` (parent of this file's directory)
# - `pip install matplotlib seaborn plotly pandas numpy`

# %% [markdown]
# ## 0. Setup

# %%
import configparser
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots

warnings.filterwarnings("ignore")

plt.rcParams.update({
    "figure.dpi": 130,
    "font.family": "sans-serif",
    "axes.spines.top": False,
    "axes.spines.right": False,
})

# Locate sniper_results/ relative to this script or the working directory
_candidates = [
    Path(__file__).parent.parent / "sniper_results",  # notebooks/../sniper_results
    Path("sniper_results"),                            # spec2006_work/sniper_results
    Path("spec2006_work/sniper_results"),              # repo root
]
RESULTS_DIR = next((p for p in _candidates if p.exists()), None)
assert RESULTS_DIR is not None, (
    "sniper_results/ not found. "
    "Run this script from spec2006_work/ or its parent directory."
)
print("Results dir:", RESULTS_DIR.resolve())

# %% [markdown]
# ## 1. Simulation Configuration
#
# Extract hardware parameters from one of the `sim.cfg` files left by Sniper.
# All simpoints share the same hardware configuration (only `output_dir` and
# `traceinput/thread_0` differ between simpoints), so parsing a single file
# is sufficient.

# %%
def _find_any_simcfg(results_dir: Path) -> Path | None:
    """Return the first sim.cfg found anywhere under results_dir."""
    for p in sorted(results_dir.rglob("sim.cfg")):
        return p
    return None


def parse_simcfg(cfg_path: Path) -> dict:
    """Parse a Sniper sim.cfg and return a flat dict of key parameters."""
    cp = configparser.RawConfigParser()
    # Prepend a dummy [DEFAULT] so bare keys before any section are accepted
    cp.read_string("[DEFAULT]\n" + cfg_path.read_text(errors="replace"))

    def get(section: str, key: str, fallback=None):
        try:
            val = cp.get(section, key, fallback=fallback)
            return val.strip('"') if isinstance(val, str) else val
        except (configparser.NoSectionError, configparser.NoOptionError):
            return fallback

    cfg = {}

    # Processor core
    cfg["arch"]               = get("general",                     "arch",              "?")
    cfg["frequency_ghz"]      = get("perf_model/core",             "frequency",         "?")
    cfg["core_model"]         = get("perf_model/core",             "type",              "?")
    cfg["total_cores"]        = get("general",                     "total_cores",       "?")
    cfg["in_order"]           = get("perf_model/core/rob_timer",   "in_order",          "?")

    # OoO engine
    cfg["rob_size"]           = get("perf_model/core/rob_timer",   "window_size",
                                get("perf_model/core/interval_timer", "window_size",    "?"))
    cfg["rs_entries"]         = get("perf_model/core/rob_timer",   "rs_entries",        "?")
    cfg["commit_width"]       = get("perf_model/core/rob_timer",   "commit_width",      "?")
    cfg["outstanding_loads"]  = get("perf_model/core/rob_timer",   "outstanding_loads", "?")
    cfg["outstanding_stores"] = get("perf_model/core/rob_timer",   "outstanding_stores","?")

    # Branch predictor
    cfg["branch_pred_type"]         = get("perf_model/branch_predictor", "type",              "?")
    cfg["branch_pred_size"]         = get("perf_model/branch_predictor", "size",              "?")
    cfg["branch_mispredict_penalty"]= get("perf_model/branch_predictor", "mispredict_penalty","?")

    # L1-I cache
    cfg["l1i_size_kb"]      = get("perf_model/l1_icache", "cache_size",       "?")
    cfg["l1i_assoc"]        = get("perf_model/l1_icache", "associativity",    "?")
    cfg["l1i_block_b"]      = get("perf_model/l1_icache", "cache_block_size", "?")
    cfg["l1i_latency_cy"]   = get("perf_model/l1_icache", "data_access_time", "?")
    cfg["l1i_prefetcher"]   = get("perf_model/l1_icache", "prefetcher",       "?")

    # L1-D cache
    cfg["l1d_size_kb"]      = get("perf_model/l1_dcache", "cache_size",       "?")
    cfg["l1d_assoc"]        = get("perf_model/l1_dcache", "associativity",    "?")
    cfg["l1d_block_b"]      = get("perf_model/l1_dcache", "cache_block_size", "?")
    cfg["l1d_latency_cy"]   = get("perf_model/l1_dcache", "data_access_time", "?")
    cfg["l1d_prefetcher"]   = get("perf_model/l1_dcache", "prefetcher",       "?")

    # L2 cache (LLC)
    cfg["l2_size_kb"]          = get("perf_model/l2_cache", "cache_size",       "?")
    cfg["l2_assoc"]            = get("perf_model/l2_cache", "associativity",    "?")
    cfg["l2_block_b"]          = get("perf_model/l2_cache", "cache_block_size", "?")
    cfg["l2_tag_latency_cy"]   = get("perf_model/l2_cache", "tags_access_time", "?")
    cfg["l2_data_latency_cy"]  = get("perf_model/l2_cache", "data_access_time", "?")
    cfg["l2_prefetcher"]       = get("perf_model/l2_cache", "prefetcher",       "?")
    cfg["cache_levels"]        = get("perf_model/cache",    "levels",           "?")

    # TLB
    cfg["dtlb_entries"]     = get("perf_model/dtlb", "size",          "?")
    cfg["dtlb_assoc"]       = get("perf_model/dtlb", "associativity", "?")
    cfg["itlb_entries"]     = get("perf_model/itlb", "size",          "?")
    cfg["itlb_assoc"]       = get("perf_model/itlb", "associativity", "?")
    cfg["stlb_entries"]     = get("perf_model/stlb", "size",          "?")
    cfg["stlb_assoc"]       = get("perf_model/stlb", "associativity", "?")
    cfg["tlb_penalty_cy"]   = get("perf_model/tlb",  "penalty",       "?")

    # DRAM
    cfg["dram_type"]            = get("perf_model/dram", "type",                    "?")
    cfg["dram_latency_ns"]      = get("perf_model/dram", "latency",                 "?")
    cfg["dram_bw_gbs"]          = get("perf_model/dram", "per_controller_bandwidth","?")
    cfg["dram_dimms_per_ctrl"]  = get("perf_model/dram", "dimms_per_controller",    "?")
    cfg["dram_chips_per_dimm"]  = get("perf_model/dram", "chips_per_dimm",          "?")

    # Simulation mode
    cfg["sim_mode_init"] = get("general", "inst_mode_init", "?")
    cfg["sim_mode_roi"]  = get("general", "inst_mode_roi",  "?")
    cfg["sim_mode_end"]  = get("general", "inst_mode_end",  "?")

    return cfg


_cfg_path = _find_any_simcfg(RESULTS_DIR)
assert _cfg_path is not None, "No sim.cfg found under sniper_results/"
print(f"Using config: {_cfg_path.relative_to(RESULTS_DIR)}")

hw_cfg = parse_simcfg(_cfg_path)

# Build a DataFrame for display
CFG_TABLE = [
    # (Category, Display name, key, unit)
    ("Processor",       "Architecture",         "arch",                    ""),
    ("Processor",       "Frequency",            "frequency_ghz",           "GHz"),
    ("Processor",       "Core model",           "core_model",              ""),
    ("Processor",       "In-order",             "in_order",                ""),
    ("Processor",       "Num cores",            "total_cores",             ""),
    ("OoO Engine",      "ROB size",             "rob_size",                "entries"),
    ("OoO Engine",      "RS entries",           "rs_entries",              "entries"),
    ("OoO Engine",      "Commit width",         "commit_width",            ""),
    ("OoO Engine",      "Outstanding loads",    "outstanding_loads",       ""),
    ("OoO Engine",      "Outstanding stores",   "outstanding_stores",      ""),
    ("Branch Predictor","Type",                 "branch_pred_type",        ""),
    ("Branch Predictor","Entries",              "branch_pred_size",        "entries"),
    ("Branch Predictor","Mispredict penalty",   "branch_mispredict_penalty","cycles"),
    ("L1-I Cache",      "Size",                 "l1i_size_kb",             "KB"),
    ("L1-I Cache",      "Associativity",        "l1i_assoc",               "-way"),
    ("L1-I Cache",      "Block size",           "l1i_block_b",             "B"),
    ("L1-I Cache",      "Access latency",       "l1i_latency_cy",          "cycles"),
    ("L1-I Cache",      "Prefetcher",           "l1i_prefetcher",          ""),
    ("L1-D Cache",      "Size",                 "l1d_size_kb",             "KB"),
    ("L1-D Cache",      "Associativity",        "l1d_assoc",               "-way"),
    ("L1-D Cache",      "Block size",           "l1d_block_b",             "B"),
    ("L1-D Cache",      "Access latency",       "l1d_latency_cy",          "cycles"),
    ("L1-D Cache",      "Prefetcher",           "l1d_prefetcher",          ""),
    ("L2 Cache (LLC)",  "Size",                 "l2_size_kb",              "KB"),
    ("L2 Cache (LLC)",  "Associativity",        "l2_assoc",                "-way"),
    ("L2 Cache (LLC)",  "Block size",           "l2_block_b",              "B"),
    ("L2 Cache (LLC)",  "Tag latency",          "l2_tag_latency_cy",       "cycles"),
    ("L2 Cache (LLC)",  "Data latency",         "l2_data_latency_cy",      "cycles"),
    ("L2 Cache (LLC)",  "Prefetcher",           "l2_prefetcher",           ""),
    ("L2 Cache (LLC)",  "Cache levels",         "cache_levels",            ""),
    ("TLB",             "D-TLB entries",        "dtlb_entries",            ""),
    ("TLB",             "D-TLB associativity",  "dtlb_assoc",              "-way"),
    ("TLB",             "I-TLB entries",        "itlb_entries",            ""),
    ("TLB",             "I-TLB associativity",  "itlb_assoc",              "-way"),
    ("TLB",             "S-TLB (L2 TLB) entries","stlb_entries",           ""),
    ("TLB",             "S-TLB associativity",  "stlb_assoc",              "-way"),
    ("TLB",             "Page walk penalty",    "tlb_penalty_cy",          "cycles"),
    ("DRAM",            "Model type",           "dram_type",               ""),
    ("DRAM",            "Access latency",       "dram_latency_ns",         "ns"),
    ("DRAM",            "Bandwidth/controller", "dram_bw_gbs",             "GB/s"),
    ("DRAM",            "DIMMs/controller",     "dram_dimms_per_ctrl",     ""),
    ("DRAM",            "Chips/DIMM",           "dram_chips_per_dimm",     ""),
    ("Simulation",      "Init mode",            "sim_mode_init",           ""),
    ("Simulation",      "ROI mode",             "sim_mode_roi",            ""),
    ("Simulation",      "End mode",             "sim_mode_end",            ""),
]

df_cfg = pd.DataFrame([
    {"Category": cat, "Parameter": name,
     "Value": (f"{hw_cfg.get(key,'?')} {unit}".strip() if unit else str(hw_cfg.get(key,"?")))}
    for cat, name, key, unit in CFG_TABLE
])
print(df_cfg.to_string(index=False))

# %% [markdown]
# ### 1a. Configuration — Styled Table

# %%
CAT_COLORS = {
    "Processor":        "#dce9f5",
    "OoO Engine":       "#d5ecd5",
    "Branch Predictor": "#fef3cc",
    "L1-I Cache":       "#f5dce9",
    "L1-D Cache":       "#f5dce9",
    "L2 Cache (LLC)":   "#ecdcf5",
    "TLB":              "#fce8d5",
    "DRAM":             "#f5d5d5",
    "Simulation":       "#e8e8e8",
}

def _highlight_cat(val):
    return f"background-color: {CAT_COLORS.get(val, '#ffffff')}"

styled_cfg = (
    df_cfg.style
    .applymap(_highlight_cat, subset=["Category"])
    .set_properties(subset=["Parameter"], **{"font-weight": "bold"})
    .hide(axis="index")
    .set_caption("Sniper Simulation Configuration — extracted from sim.cfg")
)
styled_cfg

# %% [markdown]
# ### 1b. Configuration — Architecture Block Diagram

# %%
from matplotlib.patches import FancyBboxPatch

fig, ax = plt.subplots(figsize=(11, 8))
ax.set_xlim(0, 11); ax.set_ylim(0, 10)
ax.axis("off")
ax.set_title("Simulated Processor Architecture  (extracted from sim.cfg)",
             fontsize=13, fontweight="bold", pad=12)

def draw_box(ax, x, y, w, h, title, lines, bg, ec="#555"):
    patch = FancyBboxPatch((x, y), w, h,
                           boxstyle="round,pad=0.12", linewidth=1.5,
                           edgecolor=ec, facecolor=bg, zorder=2)
    ax.add_patch(patch)
    ax.text(x + w/2, y + h - 0.22, title,
            ha="center", va="top", fontsize=8.5, fontweight="bold", zorder=3)
    for i, line in enumerate(lines):
        ax.text(x + w/2, y + h - 0.55 - i * 0.30,
                line, ha="center", va="top", fontsize=7.2, zorder=3)

f = hw_cfg  # shorthand

# Core
draw_box(ax, 0.4, 6.8, 4.5, 2.9, "Processor Core",
         [f"ISA: {f['arch'].upper()}  |  {f['frequency_ghz']} GHz  |  In-order: {f['in_order']}",
          f"Core model: {f['core_model'].upper()}  |  Cores: {f['total_cores']}",
          f"ROB: {f['rob_size']} entries   RS: {f['rs_entries']} entries",
          f"Commit width: {f['commit_width']}   Ld: {f['outstanding_loads']}   St: {f['outstanding_stores']}"],
         "#dce9f5")

# Branch predictor
draw_box(ax, 5.3, 7.5, 4.8, 1.9, "Branch Predictor",
         [f"Type: {f['branch_pred_type']}   Entries: {f['branch_pred_size']}",
          f"Mispredict penalty: {f['branch_mispredict_penalty']} cycles"],
         "#fef3cc")

# L1-I
draw_box(ax, 0.4, 4.4, 2.1, 2.1, "L1-I Cache",
         [f"{f['l1i_size_kb']} KB  {f['l1i_assoc']}-way",
          f"Block: {f['l1i_block_b']} B",
          f"Latency: {f['l1i_latency_cy']} cy",
          f"Prefetch: {f['l1i_prefetcher']}"],
         "#f5dce9")

# L1-D
draw_box(ax, 2.8, 4.4, 2.1, 2.1, "L1-D Cache",
         [f"{f['l1d_size_kb']} KB  {f['l1d_assoc']}-way",
          f"Block: {f['l1d_block_b']} B",
          f"Latency: {f['l1d_latency_cy']} cy",
          f"Prefetch: {f['l1d_prefetcher']}"],
         "#f5dce9")

# TLB
draw_box(ax, 5.3, 4.4, 4.8, 2.1, "TLB",
         [f"D-TLB: {f['dtlb_entries']} entries  {f['dtlb_assoc']}-way",
          f"I-TLB: {f['itlb_entries']} entries  {f['itlb_assoc']}-way",
          f"S-TLB: {f['stlb_entries']} entries  {f['stlb_assoc']}-way",
          f"Page walk penalty: {f['tlb_penalty_cy']} cycles"],
         "#fce8d5")

# L2 (LLC)
draw_box(ax, 0.4, 2.2, 9.7, 1.9, "L2 Cache (LLC)",
         [f"{f['l2_size_kb']} KB  {f['l2_assoc']}-way  Block: {f['l2_block_b']} B  "
          f"Tag: {f['l2_tag_latency_cy']} cy  Data: {f['l2_data_latency_cy']} cy  "
          f"Prefetch: {f['l2_prefetcher']}"],
         "#ecdcf5")

# DRAM
draw_box(ax, 0.4, 0.3, 9.7, 1.65, "DRAM",
         [f"Model: {f['dram_type']}   Latency: {f['dram_latency_ns']} ns   "
          f"BW: {f['dram_bw_gbs']} GB/s / controller",
          f"DIMMs/ctrl: {f['dram_dimms_per_ctrl']}   Chips/DIMM: {f['dram_chips_per_dimm']}"],
         "#f5d5d5")

# Arrows
ap = dict(arrowstyle="<->", color="#777", lw=1.3)
# Core ↔ L1-I / L1-D
ax.annotate("", xy=(1.5, 6.8), xytext=(1.5, 6.5), arrowprops=ap)
ax.annotate("", xy=(3.85, 6.8), xytext=(3.85, 6.5), arrowprops=ap)
# L1-I/D ↔ L2
ax.annotate("", xy=(1.5, 4.4), xytext=(1.5, 4.1), arrowprops=ap)
ax.annotate("", xy=(3.85, 4.4), xytext=(3.85, 4.1), arrowprops=ap)
# L2 ↔ DRAM
ax.annotate("", xy=(5.25, 2.2), xytext=(5.25, 1.95), arrowprops=ap)

plt.tight_layout()
plt.show()

# %% [markdown]
# ## 2. Data Collection
#
# Parse every `sim.out` under `sniper_results/`, weight each simpoint by its
# SimPoint weight, and compute a weighted average per benchmark.

# %%
def parse_simout(path: Path) -> dict:
    """Parse key statistics from a Sniper sim.out file."""
    lines = path.read_text(errors="replace").splitlines()
    result = {}
    section = sub_section = None

    for line in lines:
        s = line.strip()
        if   s.startswith("Branch predictor"): section, sub_section = "branch", None
        elif s.startswith("TLB Summary"):      section, sub_section = "tlb",    None
        elif s.startswith("I-TLB"):            sub_section = "itlb"
        elif s.startswith("D-TLB"):            sub_section = "dtlb"
        elif s.startswith("L2 TLB"):           sub_section = "l2tlb"
        elif s.startswith("Cache Summary"):    section, sub_section = "cache",  None
        elif s.startswith("Cache L1-I"):       sub_section = "l1i"
        elif s.startswith("Cache L1-D"):       sub_section = "l1d"
        elif s.startswith("Cache L2"):         sub_section = "l2"
        elif s.startswith("DRAM summary"):     section, sub_section = "dram",   None

        if "|" not in line:
            continue
        kp = line.split("|")[0].strip()
        vp = line.split("|", 1)[1].strip().rstrip("%")
        try:
            v = float(vp)
        except (ValueError, TypeError):
            continue

        if   "Instructions" in kp and section is None:  result["instructions"] = v
        elif "Cycles"       in kp and section is None:  result["cycles"]       = v
        elif kp == "IPC"        and section is None:    result["ipc"]          = v
        elif "Idle time (%)" in kp:                     result["idle_pct"]     = v
        elif section == "branch":
            if   "misprediction rate" in kp: result["branch_mispredict_pct"] = v
            elif kp == "mpki":               result["branch_mpki"]           = v
        elif section == "tlb":
            if sub_section == "dtlb":
                if   "miss rate" in kp: result["dtlb_miss_pct"] = v
                elif kp == "mpki":      result["dtlb_mpki"]     = v
            elif sub_section == "l2tlb":
                if   "miss rate" in kp: result["l2tlb_miss_pct"] = v
                elif kp == "mpki":      result["l2tlb_mpki"]     = v
        elif section == "cache":
            if sub_section == "l1i":
                if   "miss rate" in kp: result["l1i_miss_pct"] = v
                elif kp == "mpki":      result["l1i_mpki"]     = v
            elif sub_section == "l1d":
                if   "miss rate" in kp: result["l1d_miss_pct"] = v
                elif kp == "mpki":      result["l1d_mpki"]     = v
            elif sub_section == "l2":
                if   "miss rate" in kp: result["l2_miss_pct"] = v
                elif kp == "mpki":      result["l2_mpki"]     = v
        elif section == "dram":
            if   "num dram accesses"           in kp: result["dram_accesses"]   = v
            elif "average dram access latency" in kp: result["dram_latency_ns"] = v
            elif "average dram bandwidth"      in kp: result["dram_bw_pct"]     = v

    if result.get("instructions") and result.get("dram_accesses"):
        result["dram_mpki"] = result["dram_accesses"] / (result["instructions"] / 1000)

    return result


def load_weights(csv_path: Path, subcmd_id: int) -> dict[int, float]:
    """Return {simpoint_id: weight} for the given subcmd from ipc_estimation.csv."""
    weights = {}
    for line in csv_path.read_text().splitlines():
        if not line or line.startswith("#"):
            continue
        parts = line.split(",")
        if len(parts) < 3:
            continue
        try:
            if int(parts[0]) == subcmd_id:
                weights[int(parts[1])] = float(parts[2])
        except ValueError:
            pass
    return weights


METRICS = [
    "ipc", "idle_pct",
    "branch_mispredict_pct", "branch_mpki",
    "dtlb_miss_pct", "dtlb_mpki",
    "l2tlb_miss_pct", "l2tlb_mpki",
    "l1i_miss_pct", "l1i_mpki",
    "l1d_miss_pct", "l1d_mpki",
    "l2_miss_pct",  "l2_mpki",
    "dram_mpki", "dram_latency_ns", "dram_bw_pct",
]

rows       = []   # one row per benchmark (weighted average)
simpt_rows = []   # one row per simpoint (raw data)

for bench_dir in sorted(RESULTS_DIR.iterdir()):
    if not bench_dir.is_dir():
        continue
    bench    = bench_dir.name
    csv_path = bench_dir / "ipc_estimation.csv"
    if not csv_path.exists():
        continue

    weighted = {m: 0.0 for m in METRICS}
    total_w  = 0.0

    for subcmd_dir in sorted(bench_dir.glob("subcmd_*")):
        scid    = int(subcmd_dir.name.replace("subcmd_", ""))
        weights = load_weights(csv_path, scid)

        for sp_dir in sorted(subcmd_dir.glob("simpoint_*")):
            sp_id  = int(sp_dir.name.replace("simpoint_", ""))
            w      = weights.get(sp_id, 0.0)
            simout = sp_dir / "sim.out"
            if w == 0 or not simout.exists():
                continue

            stats = parse_simout(simout)
            for m in METRICS:
                if stats.get(m) is not None:
                    weighted[m] += stats[m] * w
            total_w += w
            simpt_rows.append({
                "benchmark": bench, "subcmd": scid,
                "simpoint": sp_id, "weight": w, **stats,
            })

    if total_w > 0:
        rows.append({
            "benchmark":    bench,
            "total_weight": total_w,
            **{m: weighted[m] / total_w for m in METRICS},
        })

df    = pd.DataFrame(rows).set_index("benchmark")
df_sp = pd.DataFrame(simpt_rows)

print(f"Loaded: {len(df)} benchmarks, {len(df_sp)} simpoints")
df[["ipc", "branch_mpki", "dtlb_mpki", "l2_mpki", "dram_mpki", "dram_bw_pct"]].round(2)

# %% [markdown]
# ## 2. Bottleneck Classification
#
# Each benchmark is assigned to one of six categories based on MPKI thresholds.
# L2/DRAM MPKI are used as primary signals — a high L2 *miss rate* with low MPKI
# simply means L2 is rarely accessed (compute-bound), not that L2 is a bottleneck.
#
# | Category     | Condition                              |
# |--------------|----------------------------------------|
# | DRAM-bound   | DRAM MPKI > 50 or DRAM BW > 50%       |
# | LLC+DRAM     | L2 MPKI > 15 and DRAM MPKI > 15       |
# | LLC-bound    | L2 MPKI > 5 and DRAM MPKI > 5         |
# | TLB-bound    | D-TLB MPKI > 50 or L2-TLB MPKI > 20  |
# | Branch-bound | Branch MPKI > 10                       |
# | Compute-bound| (none of the above)                    |

# %%
BOTTLENECK_ORDER = [
    "DRAM-bound",
    "LLC+DRAM",
    "LLC-bound",
    "TLB-bound",
    "Branch-bound",
    "Compute-bound",
]
BOTTLENECK_COLORS = {
    "DRAM-bound":   "#d62728",
    "LLC+DRAM":     "#ff7f0e",
    "LLC-bound":    "#e377c2",
    "TLB-bound":    "#9467bd",
    "Branch-bound": "#bcbd22",
    "Compute-bound":"#2ca02c",
}


def classify(row: pd.Series) -> str:
    d  = row["dram_mpki"]
    bw = row["dram_bw_pct"]
    l2 = row["l2_mpki"]
    dt = row["dtlb_mpki"]
    lt = row["l2tlb_mpki"]
    br = row["branch_mpki"]
    if d > 50 or bw > 50:   return "DRAM-bound"
    if l2 > 15 and d > 15:  return "LLC+DRAM"
    if l2 > 5  and d > 5:   return "LLC-bound"
    if dt > 50 or lt > 20:  return "TLB-bound"
    if br > 10:              return "Branch-bound"
    return "Compute-bound"


df["bottleneck"] = df.apply(classify, axis=1)
df[["ipc", "bottleneck"]].sort_values("ipc")

# %% [markdown]
# ## 3. IPC Overview (colored by bottleneck)

# %%
sorted_df = df.sort_values("ipc", ascending=True).reset_index()

fig = go.Figure()
for cat in BOTTLENECK_ORDER:
    sub = sorted_df[sorted_df["bottleneck"] == cat]
    if sub.empty:
        continue
    fig.add_trace(go.Bar(
        x=sub["ipc"],
        y=sub["benchmark"],
        orientation="h",
        name=cat,
        marker_color=BOTTLENECK_COLORS[cat],
        text=[f"{v:.3f}" for v in sub["ipc"]],
        textposition="outside",
        hovertemplate="%{y}<br>IPC: %{x:.3f}<extra>" + cat + "</extra>",
    ))

fig.add_vline(x=1.0, line_dash="dash", line_color="gray",
              annotation_text="IPC = 1.0", annotation_position="top right")
fig.update_layout(
    title="SPEC CPU2006 — IPC by Benchmark (colored by bottleneck)",
    xaxis_title="IPC (weighted average)",
    barmode="overlay",
    height=480,
    legend=dict(title="Bottleneck", orientation="v"),
    xaxis_range=[0, sorted_df["ipc"].max() * 1.18],
)
fig.show()

# %% [markdown]
# ## 4. Memory Hierarchy MPKI Comparison (log scale, grouped bar)

# %%
mpki_cols   = ["branch_mpki", "dtlb_mpki", "l2tlb_mpki", "l1d_mpki", "l2_mpki", "dram_mpki"]
mpki_labels = ["Branch", "D-TLB", "L2-TLB", "L1-D", "L2", "DRAM"]
mpki_colors = ["#aec7e8", "#ffbb78", "#c5b0d5", "#f7b6d2", "#c49c94", "#d62728"]

bench_order = df.sort_values("dram_mpki", ascending=False).index.tolist()

fig = go.Figure()
for col, label, color in zip(mpki_cols, mpki_labels, mpki_colors):
    fig.add_trace(go.Bar(
        x=bench_order,
        y=[df.loc[b, col] for b in bench_order],
        name=label,
        marker_color=color,
        hovertemplate="%{x}<br>" + label + ": %{y:.2f} MPKI<extra></extra>",
    ))

fig.update_layout(
    barmode="group",
    title="Memory Hierarchy MPKI per Benchmark",
    yaxis=dict(title="MPKI", type="log"),
    xaxis_title="Benchmark",
    height=480,
    legend=dict(orientation="h", y=1.08),
)
fig.show()

# %% [markdown]
# ## 5. Bottleneck Heatmap (column-normalized)
#
# All metrics are normalized to [0, 1] per column.
# IPC is inverted so that **red always means worse performance**.

# %%
hm_cols = {
    "ipc":             "IPC",
    "branch_mpki":     "Branch MPKI",
    "dtlb_mpki":       "D-TLB MPKI",
    "l2tlb_mpki":      "L2-TLB MPKI",
    "l1d_miss_pct":    "L1-D Miss%",
    "l1d_mpki":        "L1-D MPKI",
    "l2_miss_pct":     "L2 Miss%",
    "l2_mpki":         "L2 MPKI",
    "dram_mpki":       "DRAM MPKI",
    "dram_bw_pct":     "DRAM BW%",
    "dram_latency_ns": "DRAM Lat(ns)",
}

bench_order_ipc = df.sort_values("ipc", ascending=False).index.tolist()
hm_df = df.loc[bench_order_ipc, list(hm_cols.keys())].rename(columns=hm_cols)

norm = hm_df.copy().astype(float)
for col in norm.columns:
    mn, mx = norm[col].min(), norm[col].max()
    if mx > mn:
        norm[col] = (norm[col] - mn) / (mx - mn)
norm["IPC"] = 1 - norm["IPC"]   # invert: high IPC = low severity

# Text annotations: raw values
annot = hm_df.copy()
for col in annot.columns:
    annot[col] = annot[col].apply(lambda v: f"{v:.0f}" if v >= 10 else f"{v:.1f}")

y_labels = [f"{b}  [{df.loc[b, 'bottleneck']}]" for b in norm.index]

fig = go.Figure(go.Heatmap(
    z=norm.values,
    x=norm.columns.tolist(),
    y=y_labels,
    text=annot.values,
    texttemplate="%{text}",
    textfont=dict(size=9),
    colorscale="RdYlGn",
    reversescale=True,
    zmin=0, zmax=1,
    colorbar=dict(title="Normalized<br>severity", thickness=15),
    hovertemplate="<b>%{y}</b><br>%{x}: %{text}<extra></extra>",
))
fig.update_layout(
    title="Bottleneck Heatmap — normalized per column  |  IPC inverted (red = low IPC)",
    xaxis=dict(tickangle=-40, side="bottom"),
    height=480,
    margin=dict(l=220),
)
fig.show()

# %% [markdown]
# ## 6. Radar Chart (Plotly interactive)
#
# Five axes normalized by the worst observed value across all benchmarks.
# A score of 1.0 means that benchmark is the worst on that axis.

# %%
# Axis definition: (column, normalization max, display name)
RADAR_AXES = [
    ("dram_mpki",   163.6,  "DRAM MPKI"),
    ("l2_mpki",      81.8,  "LLC MPKI"),
    ("dtlb_mpki",   107.2,  "TLB MPKI"),
    ("branch_mpki",  18.81, "Branch MPKI"),
    ("idle_pct",     10.0,  "Idle %"),
]
categories        = [a[2] for a in RADAR_AXES]
categories_closed = categories + [categories[0]]

palette = px.colors.qualitative.Plotly
fig     = go.Figure()

for i, bench in enumerate(df.index):
    vals = [
        round(min(df.loc[bench, col] / norm_max, 1.0), 3)
        for col, norm_max, _ in RADAR_AXES
    ]
    fig.add_trace(go.Scatterpolar(
        r=vals + [vals[0]],
        theta=categories_closed,
        fill="toself",
        name=bench,
        opacity=0.55,
        line=dict(color=palette[i % len(palette)]),
    ))

fig.update_layout(
    polar=dict(radialaxis=dict(visible=True, range=[0, 1])),
    title="Bottleneck Radar Chart  (1.0 = worst observed across all benchmarks)",
    height=600,
)
fig.show()

# %% [markdown]
# ## 7. DRAM MPKI vs IPC Scatter Plot (Plotly interactive)
#
# Bubble size = L2 MPKI. Hover over each point to see all metrics.

# %%
fig = px.scatter(
    df.reset_index(),
    x="dram_mpki",
    y="ipc",
    color="bottleneck",
    color_discrete_map=BOTTLENECK_COLORS,
    text="benchmark",
    size="l2_mpki",
    size_max=45,
    hover_data=["branch_mpki", "dtlb_mpki", "dram_bw_pct", "l2_miss_pct"],
    title="DRAM MPKI vs IPC  (bubble size = L2 MPKI)",
    log_x=True,
)
fig.update_traces(textposition="top center")
fig.update_layout(
    height=520,
    xaxis_title="DRAM MPKI (log scale)",
    yaxis_title="IPC (weighted avg)",
)
fig.show()

# %% [markdown]
# ## 8. Per-Benchmark SimPoint Distribution
#
# Change `TARGET_BENCH` to inspect any benchmark.
# Shows IPC, L2 miss rate, and DRAM MPKI for the top-N simpoints by weight.
# The dashed line overlaid on each bar chart shows the simpoint weight.

# %%
TARGET_BENCH = "429.mcf"   # <-- change to any benchmark name
TOP_N        = 20          # number of simpoints to show (by weight, descending)

sp = df_sp[df_sp["benchmark"] == TARGET_BENCH].copy()
if sp.empty:
    print(f"No data found for '{TARGET_BENCH}'")
else:
    sp     = sp.sort_values("weight", ascending=False)
    sp_top = sp.head(min(TOP_N, len(sp))).copy()
    sp_top["label"] = sp_top.apply(
        lambda r: f"sp{int(r['simpoint'])} (sc{int(r['subcmd'])})", axis=1
    )

    _metrics = [
        ("ipc",         "IPC",       "#4878CF"),
        ("l2_miss_pct", "L2 Miss%",  "#e377c2"),
        ("dram_mpki",   "DRAM MPKI", "#d62728"),
    ]

    fig = make_subplots(
        rows=1, cols=3,
        subplot_titles=[m[1] for m in _metrics],
        shared_xaxes=False,
    )

    for col_idx, (col, ylabel, color) in enumerate(_metrics, start=1):
        vals = sp_top[col].fillna(0)
        # Bar for the metric
        fig.add_trace(go.Bar(
            x=sp_top["label"], y=vals,
            name=ylabel, marker_color=color, opacity=0.85,
            showlegend=(col_idx == 1),
            hovertemplate="%{x}<br>" + ylabel + ": %{y:.3f}<extra></extra>",
        ), row=1, col=col_idx)
        # Weight line on secondary y-axis (approximated via a scatter overlay)
        fig.add_trace(go.Scatter(
            x=sp_top["label"], y=sp_top["weight"],
            name="weight" if col_idx == 1 else None,
            showlegend=(col_idx == 1),
            mode="lines+markers",
            line=dict(color="black", dash="dash", width=1.5),
            marker=dict(size=5),
            yaxis=f"y{col_idx + 3}",   # separate y-axes: y4, y5, y6
            hovertemplate="%{x}<br>weight: %{y:.4f}<extra></extra>",
        ), row=1, col=col_idx)

    # Register the secondary y-axes for weight lines
    weight_min, weight_max = sp_top["weight"].min(), sp_top["weight"].max()
    for i in range(1, 4):
        axis_key = f"yaxis{i + 3}"
        fig.update_layout(**{axis_key: dict(
            overlaying=f"y{i}",
            side="right",
            showgrid=False,
            range=[weight_min * 0.8, weight_max * 1.2],
            title="weight" if i == 3 else "",
            tickformat=".3f",
        )})

    fig.update_xaxes(tickangle=-50, tickfont=dict(size=9))
    fig.update_layout(
        title=f"{TARGET_BENCH} — Top {len(sp_top)} simpoints by weight",
        height=420,
        legend=dict(orientation="h", y=-0.25),
    )
    fig.show()

    print(sp_top[[
        "subcmd", "simpoint", "weight",
        "ipc", "l2_miss_pct", "dram_mpki", "dtlb_mpki",
    ]].to_string(index=False))

# %% [markdown]
# ## 9. IPC Box Plot by Bottleneck Category (simpoint level)
#
# Shows how widely IPC varies within each category across individual simpoints.
# DRAM-bound benchmarks cluster near 0.1–0.3; Compute-bound benchmarks reach 1.5+.

# %%
df_sp2 = df_sp.merge(
    df[["bottleneck"]].reset_index(), on="benchmark", how="left"
)

labels_used = [c for c in BOTTLENECK_ORDER if c in df_sp2["bottleneck"].values]

fig = go.Figure()
for cat in labels_used:
    ipc_vals = df_sp2[df_sp2["bottleneck"] == cat]["ipc"].dropna().values
    fig.add_trace(go.Box(
        y=ipc_vals,
        name=cat,
        marker_color=BOTTLENECK_COLORS[cat],
        opacity=0.85,
        boxmean="sd",
    ))

fig.add_hline(y=1.0, line_dash="dash", line_color="gray", opacity=0.6)
fig.update_layout(
    title="IPC Distribution by Bottleneck Category  (simpoint level)",
    yaxis_title="IPC (individual simpoints)",
    showlegend=False,
    height=450,
)
fig.show()

# %% [markdown]
# ## 10. Cache Hierarchy Miss Pressure (Plotly interactive stacked bar)
#
# L1-D, L2, and DRAM MPKI stacked to show where misses occur in the hierarchy.
# Sorted by DRAM MPKI ascending (lowest memory pressure on the left).

# %%
stack_cols   = ["l1d_mpki", "l2_mpki", "dram_mpki"]
stack_names  = ["L1-D MPKI", "L2 MPKI", "DRAM MPKI"]
stack_colors = ["#aec7e8",   "#e377c2",  "#d62728"]

bench_order_dram = df.sort_values("dram_mpki", ascending=True).index.tolist()
df_plot = df.loc[bench_order_dram]

fig = go.Figure()
for col, name, color in zip(stack_cols, stack_names, stack_colors):
    fig.add_trace(go.Bar(
        y=df_plot.index,
        x=df_plot[col],
        name=name,
        orientation="h",
        marker_color=color,
    ))

fig.update_layout(
    barmode="stack",
    title="Cache Hierarchy Miss Pressure — stacked MPKI (sorted by DRAM MPKI)",
    xaxis_title="MPKI",
    height=420,
    legend=dict(orientation="h", y=1.08),
)
fig.show()

# %% [markdown]
# ## 11. SPEC CPU2006 Score Table
#
# Loads `ipc_summary.csv` which records the reference time and the SimPoint-estimated
# runtime for each benchmark.
#
# **Score (ratio)** = `ref_time_sec / run_time_sec`
#
# This is the SPECint2006 ratio at the simulated clock frequency (2 GHz).
# `spec_per_ghz` in the CSV equals `ratio` — both represent the same value.

# %%
_summary_path = RESULTS_DIR / "ipc_summary.csv"
assert _summary_path.exists(), f"ipc_summary.csv not found: {_summary_path}"

df_spec = pd.read_csv(_summary_path, comment="#")
df_spec = df_spec.set_index("benchmark")
df_spec = df_spec.join(df[["ipc", "bottleneck"]], how="left")

# Geometric mean of ratios (excludes benchmarks with ratio = 0)
valid_ratios = df_spec["ratio"].replace(0, np.nan).dropna()
geomean = np.exp(np.log(valid_ratios).mean())

print(f"SPECint2006 estimated score (geometric mean of ratios): {geomean:.2f}")
print()

# ---- Left: ratio bar (= SPEC score per bench) ----
bench_order_score = df_spec.sort_values("ratio", ascending=True).index.tolist()
colors_score = [
    BOTTLENECK_COLORS.get(df_spec.loc[b, "bottleneck"], "#888888")
    for b in bench_order_score
]

fig_spec = make_subplots(
    rows=1, cols=2,
    subplot_titles=["Score per Benchmark", "Ref Time vs Estimated Run Time"],
    horizontal_spacing=0.12,
)

fig_spec.add_trace(go.Bar(
    y=bench_order_score,
    x=df_spec.loc[bench_order_score, "ratio"],
    orientation="h",
    marker_color=colors_score,
    text=[f"{v:.2f}" for v in df_spec.loc[bench_order_score, "ratio"]],
    textposition="outside",
    name="SPEC ratio",
    showlegend=False,
), row=1, col=1)

# Geomean vertical line (shape on col=1 = x-axis 1)
fig_spec.add_vline(
    x=geomean, line_dash="dash", line_color="navy", line_width=1.5,
    annotation_text=f"Geomean={geomean:.2f}",
    annotation_position="top right",
    row=1, col=1,
)

# ---- Right: ref vs estimated runtime ----
bench_order_rt = df_spec.sort_values("run_time_sec", ascending=False).index.tolist()

fig_spec.add_trace(go.Bar(
    y=bench_order_rt,
    x=df_spec.loc[bench_order_rt, "ref_time_sec"] / 3600,
    orientation="h",
    marker_color="#aec7e8",
    name="Ref time (hours)",
    opacity=0.9,
), row=1, col=2)

fig_spec.add_trace(go.Bar(
    y=bench_order_rt,
    x=df_spec.loc[bench_order_rt, "run_time_sec"] / 3600,
    orientation="h",
    marker_color="#d62728",
    name="Estimated run time (hours)",
    opacity=0.8,
), row=1, col=2)

fig_spec.update_xaxes(title_text="SPECint2006 ratio  (ref_time / run_time)", row=1, col=1)
fig_spec.update_xaxes(title_text="Time (hours)", row=1, col=2)
fig_spec.update_layout(
    title="SPEC CPU2006 — Estimated Score Summary",
    barmode="overlay",
    height=480,
    legend=dict(orientation="h", y=-0.18),
)
fig_spec.show()

# ---- Styled table ----
tbl_cols = {
    "ref_time_sec":   "Ref Time (s)",
    "run_time_sec":   "Est. Run Time (s)",
    "ratio":          "Score (ratio)",
    "overall_ipc":    "IPC (summary)",
    "ipc":            "IPC (weighted)",
    "num_simpoints":  "# SimPoints",
    "bottleneck":     "Bottleneck",
}
tbl = (
    df_spec[list(tbl_cols.keys())]
    .rename(columns=tbl_cols)
    .sort_values("Score (ratio)", ascending=False)
)

def _highlight_bn(val):
    color_map = {
        "DRAM-bound":   "background-color: #ffcccc",
        "LLC+DRAM":     "background-color: #ffe5cc",
        "LLC-bound":    "background-color: #ffd6ee",
        "TLB-bound":    "background-color: #e8ccff",
        "Branch-bound": "background-color: #ffffcc",
        "Compute-bound":"background-color: #ccffcc",
    }
    return color_map.get(val, "")

numeric_tbl = [c for c in tbl.columns if c != "Bottleneck"]
styled_tbl = (
    tbl.style
    .format({c: "{:.2f}" for c in numeric_tbl if tbl[c].dtype != object})
    .format({"# SimPoints": "{:.0f}"})
    .applymap(_highlight_bn, subset=["Bottleneck"])
    .background_gradient(subset=["Score (ratio)"], cmap="YlGn")
    .background_gradient(subset=["IPC (weighted)"], cmap="Greens")
    .set_caption(
        f"SPEC CPU2006 Estimated Scores — sorted by Score desc  "
        f"| Geometric mean: {geomean:.2f}"
    )
)
styled_tbl

# %% [markdown]
# ## 12. Detailed Metrics Summary Table
#
# All weighted-average metrics sorted by IPC (descending).

# %%
display_cols = {
    "ipc":             "IPC",
    "branch_mpki":     "Branch MPKI",
    "dtlb_mpki":       "D-TLB MPKI",
    "l2tlb_mpki":      "L2-TLB MPKI",
    "l1d_miss_pct":    "L1-D Miss%",
    "l2_miss_pct":     "L2 Miss%",
    "l2_mpki":         "L2 MPKI",
    "dram_mpki":       "DRAM MPKI",
    "dram_bw_pct":     "DRAM BW%",
    "dram_latency_ns": "DRAM Lat(ns)",
    "bottleneck":      "Bottleneck",
}
out = (
    df[list(display_cols.keys())]
    .rename(columns=display_cols)
    .sort_values("IPC", ascending=False)
)

numeric_cols = [c for c in out.columns if c != "Bottleneck"]
styled = (
    out.style
    .format({c: "{:.2f}" for c in numeric_cols})
    .applymap(_highlight_bn, subset=["Bottleneck"])
    .background_gradient(subset=["DRAM MPKI"], cmap="Reds",   vmin=0, vmax=165)
    .background_gradient(subset=["IPC"],       cmap="Greens")
    .set_caption("SPEC CPU2006 — Weighted Average Metrics (sorted by IPC desc)")
)
styled
