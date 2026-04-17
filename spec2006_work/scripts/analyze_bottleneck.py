#!/usr/bin/env python3
"""
analyze_bottleneck.py

各ベンチマークの SimPoint シミュレーション結果 (sim.out) からボトルネック統計を
重み付き集計し、CSV と可読テキストレポートを出力する。

使い方:
  python3 analyze_bottleneck.py [sniper_results_dir]

sniper_results_dir のデフォルトは
  ../sniper_results  (スクリプトの隣の spec2006_work/sniper_results)
"""

import re
import sys
import csv
from pathlib import Path


# ============================================================
# sim.out パーサ
# ============================================================

def parse_simout(path: Path) -> dict:
    """sim.out から主要統計を辞書で返す。パース失敗時は空辞書。"""
    text = path.read_text(errors="replace")
    result = {}

    def _float(pattern):
        m = re.search(pattern, text)
        return float(m.group(1)) if m else None

    # 基本
    result["ipc"]           = _float(r"^\s+IPC\s+\|\s+([\d.]+)", )
    result["instructions"]  = _float(r"^\s+Instructions\s+\|\s+([\d]+)")
    result["cycles"]        = _float(r"^\s+Cycles\s+\|\s+([\d]+)")
    result["idle_pct"]      = _float(r"^\s+Idle time \(%\)\s+\|\s+([\d.]+)%")

    # 分岐予測
    result["branch_mispredict_rate_pct"] = _float(
        r"misprediction rate\s+\|\s+([\d.]+)%")
    result["branch_mpki"]   = _float(
        r"Branch predictor stats.*?\n(?:.*?\n){1,10}?\s+mpki\s+\|\s+([\d.]+)")

    # D-TLB
    result["dtlb_miss_rate_pct"] = _float(
        r"D-TLB\s*\n.*?\n.*?\n\s+miss rate\s+\|\s+([\d.]+)%")
    result["dtlb_mpki"]     = _float(
        r"D-TLB\s*\n(?:.*?\n){1,4}?\s+mpki\s+\|\s+([\d.]+)")

    # L2 TLB
    result["l2tlb_miss_rate_pct"] = _float(
        r"L2 TLB\s*\n.*?\n.*?\n\s+miss rate\s+\|\s+([\d.]+)%")
    result["l2tlb_mpki"]    = _float(
        r"L2 TLB\s*\n(?:.*?\n){1,4}?\s+mpki\s+\|\s+([\d.]+)")

    # L1-I
    result["l1i_miss_rate_pct"] = _float(
        r"Cache L1-I\s*\n.*?\n.*?\n\s+miss rate\s+\|\s+([\d.]+)%")
    result["l1i_mpki"]      = _float(
        r"Cache L1-I\s*\n(?:.*?\n){1,4}?\s+mpki\s+\|\s+([\d.]+)")

    # L1-D
    result["l1d_miss_rate_pct"] = _float(
        r"Cache L1-D\s*\n.*?\n.*?\n\s+miss rate\s+\|\s+([\d.]+)%")
    result["l1d_mpki"]      = _float(
        r"Cache L1-D\s*\n(?:.*?\n){1,4}?\s+mpki\s+\|\s+([\d.]+)")

    # L2 Cache
    result["l2_miss_rate_pct"] = _float(
        r"Cache L2\s*\n.*?\n.*?\n\s+miss rate\s+\|\s+([\d.]+)%")
    result["l2_mpki"]       = _float(
        r"Cache L2\s*\n(?:.*?\n){1,4}?\s+mpki\s+\|\s+([\d.]+)")

    # DRAM
    result["dram_accesses"]     = _float(
        r"num dram accesses\s+\|\s+([\d]+)")
    result["dram_latency_ns"]   = _float(
        r"average dram access latency \(ns\)\s+\|\s+([\d.]+)")
    result["dram_bw_util_pct"]  = _float(
        r"average dram bandwidth utilization\s+\|\s+([\d.]+)%")

    # mpki 再計算 (sim.out の branch mpki は分岐ヘッダ直後にある)
    # より確実な方法: instructions ベースで直接計算
    if result["instructions"] and result["dram_accesses"]:
        result["dram_mpki"] = result["dram_accesses"] / (result["instructions"] / 1000.0)
    else:
        result["dram_mpki"] = None

    return result


# より厳密なパーサ: セクションごとに読む
def parse_simout_v2(path: Path) -> dict:
    """行ベースで sim.out を解析する (正規表現ネスト依存を減らす版)。"""
    lines = path.read_text(errors="replace").splitlines()
    result = {}

    def val(line):
        """'  Key  |  value' から value 文字列を取り出す。"""
        parts = line.split("|", 1)
        return parts[1].strip().rstrip("%") if len(parts) == 2 else None

    section = None
    sub_section = None
    for line in lines:
        stripped = line.strip()

        # セクション検出
        if stripped.startswith("Branch predictor"):
            section = "branch"
            sub_section = None
        elif stripped.startswith("TLB Summary"):
            section = "tlb"
            sub_section = None
        elif stripped.startswith("I-TLB"):
            sub_section = "itlb"
        elif stripped.startswith("D-TLB"):
            sub_section = "dtlb"
        elif stripped.startswith("L2 TLB"):
            sub_section = "l2tlb"
        elif stripped.startswith("Cache Summary"):
            section = "cache"
            sub_section = None
        elif stripped.startswith("Cache L1-I"):
            sub_section = "l1i"
        elif stripped.startswith("Cache L1-D"):
            sub_section = "l1d"
        elif stripped.startswith("Cache L2"):
            sub_section = "l2"
        elif stripped.startswith("DRAM summary"):
            section = "dram"
            sub_section = None
        elif stripped.startswith("Coherency"):
            section = "coherency"
            sub_section = None

        if "|" not in line:
            continue
        key_part = line.split("|")[0].strip()
        v = val(line)
        if v is None:
            continue

        try:
            # コアベース統計
            if "Instructions" in key_part and section is None:
                result["instructions"] = float(v)
            elif "Cycles" in key_part and section is None:
                result["cycles"] = float(v)
            elif key_part == "IPC" and section is None:
                result["ipc"] = float(v)
            elif "Idle time (%)" in key_part:
                result["idle_pct"] = float(v)

            # 分岐
            elif section == "branch":
                if "misprediction rate" in key_part:
                    result["branch_mispredict_rate_pct"] = float(v)
                elif key_part == "mpki":
                    result["branch_mpki"] = float(v)

            # TLB
            elif section == "tlb":
                if sub_section == "dtlb":
                    if "miss rate" in key_part:
                        result["dtlb_miss_rate_pct"] = float(v)
                    elif key_part == "mpki":
                        result["dtlb_mpki"] = float(v)
                elif sub_section == "l2tlb":
                    if "miss rate" in key_part:
                        result["l2tlb_miss_rate_pct"] = float(v)
                    elif key_part == "mpki":
                        result["l2tlb_mpki"] = float(v)

            # キャッシュ
            elif section == "cache":
                if sub_section == "l1i":
                    if "miss rate" in key_part:
                        result["l1i_miss_rate_pct"] = float(v)
                    elif key_part == "mpki":
                        result["l1i_mpki"] = float(v)
                elif sub_section == "l1d":
                    if "miss rate" in key_part:
                        result["l1d_miss_rate_pct"] = float(v)
                    elif key_part == "mpki":
                        result["l1d_mpki"] = float(v)
                elif sub_section == "l2":
                    if "miss rate" in key_part:
                        result["l2_miss_rate_pct"] = float(v)
                    elif key_part == "mpki":
                        result["l2_mpki"] = float(v)

            # DRAM
            elif section == "dram":
                if "num dram accesses" in key_part:
                    result["dram_accesses"] = float(v)
                elif "average dram access latency" in key_part:
                    result["dram_latency_ns"] = float(v)
                elif "average dram bandwidth utilization" in key_part:
                    result["dram_bw_util_pct"] = float(v)

        except (ValueError, TypeError):
            pass

    # DRAM mpki 計算
    if result.get("instructions") and result.get("dram_accesses"):
        result["dram_mpki"] = result["dram_accesses"] / (result["instructions"] / 1000.0)

    return result


# ============================================================
# メイン集計
# ============================================================

METRICS = [
    "ipc",
    "idle_pct",
    "branch_mispredict_rate_pct",
    "branch_mpki",
    "dtlb_miss_rate_pct",
    "dtlb_mpki",
    "l2tlb_miss_rate_pct",
    "l2tlb_mpki",
    "l1i_miss_rate_pct",
    "l1i_mpki",
    "l1d_miss_rate_pct",
    "l1d_mpki",
    "l2_miss_rate_pct",
    "l2_mpki",
    "dram_mpki",
    "dram_latency_ns",
    "dram_bw_util_pct",
]


def collect_benchmark(bench_dir: Path) -> dict:
    """ベンチマーク 1 個分: サブコマンド × simpoint を集計して重み付き平均を返す。"""
    weighted = {m: 0.0 for m in METRICS}
    total_weight = 0.0
    num_simpoints = 0
    errors = []

    for subcmd_dir in sorted(bench_dir.glob("subcmd_*")):
        csv_path = subcmd_dir.parent / "ipc_estimation.csv"
        if not csv_path.exists():
            continue

        # weight 辞書 {simpoint_id: weight}
        weights = {}
        try:
            with open(csv_path) as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split(",")
                    if len(parts) >= 3:
                        try:
                            subcmd_id = int(parts[0])
                            sp_id = int(parts[1])
                            w = float(parts[2])
                            if subcmd_dir.name == f"subcmd_{subcmd_id}":
                                weights[sp_id] = w
                        except ValueError:
                            pass
        except Exception as e:
            errors.append(str(e))
            continue

        for sp_dir in sorted(subcmd_dir.glob("simpoint_*")):
            sp_id_str = sp_dir.name.replace("simpoint_", "")
            try:
                sp_id = int(sp_id_str)
            except ValueError:
                continue
            w = weights.get(sp_id, 0.0)
            if w == 0.0:
                continue

            simout = sp_dir / "sim.out"
            if not simout.exists():
                continue

            stats = parse_simout_v2(simout)
            for m in METRICS:
                v = stats.get(m)
                if v is not None:
                    weighted[m] += v * w

            total_weight += w
            num_simpoints += 1

    if total_weight > 0:
        avg = {m: weighted[m] / total_weight for m in METRICS}
    else:
        avg = {m: None for m in METRICS}

    avg["total_weight"] = total_weight
    avg["num_simpoints"] = num_simpoints
    return avg


def bottleneck_label(row: dict) -> str:
    """主要ボトルネックを判定して文字列で返す。

    判定優先度:
      1. DRAM律速: DRAM_mpki > 50 or DRAM_bw > 50%
      2. TLB律速:  DTLB_mpki > 50 or L2TLB_mpki > 20
      3. LLC+DRAM: L2_mpki > 15 and DRAM_mpki > 15
      4. 分岐ミス: branch_mpki > 10
      5. L2ミス:   L2_mpki > 5 (かつ DRAM_mpki > 5)
      6. 計算律速 or L1/L2小

    注: L2 miss率が高くても DRAM_mpki が小さい場合は L2 へのアクセス自体が
        少ない (= L1 で大半がヒット) ため、実質的に計算律速と見なす。
    """
    ipc = row.get("ipc") or 0
    dram_mpki = row.get("dram_mpki") or 0
    l2_mpki = row.get("l2_mpki") or 0
    l2_miss = row.get("l2_miss_rate_pct") or 0
    dtlb_mpki = row.get("dtlb_mpki") or 0
    l2tlb_mpki = row.get("l2tlb_mpki") or 0
    branch_mpki = row.get("branch_mpki") or 0
    dram_bw = row.get("dram_bw_util_pct") or 0

    bottlenecks = []

    # DRAM 帯域 > 50% → 帯域律速 (最優先)
    if dram_bw > 50:
        bottlenecks.append(f"DRAM帯域({dram_bw:.0f}%)")
    # DRAM mpki > 50 → メモリレイテンシ律速
    if dram_mpki > 50:
        bottlenecks.append(f"DRAMレイテンシ(mpki={dram_mpki:.0f})")

    # D-TLB mpki > 50 → TLB スラッシング
    if dtlb_mpki > 50:
        bottlenecks.append(f"DTLBミス(mpki={dtlb_mpki:.0f})")
    # L2 TLB mpki > 20 → page walk 律速
    if l2tlb_mpki > 20:
        bottlenecks.append(f"PageWalk(mpki={l2tlb_mpki:.0f})")

    # DRAM 律速でない場合の LLC/DRAM 評価
    if not bottlenecks:
        # L2 mpki > 15 かつ DRAM mpki > 15 → LLC+DRAM 複合
        if l2_mpki > 15 and dram_mpki > 15:
            bottlenecks.append(f"LLC+DRAM(L2mpki={l2_mpki:.0f},DRAMmpki={dram_mpki:.0f})")
        # L2 mpki > 5 かつ DRAM mpki > 5 → LLCミス律速
        elif l2_mpki > 5 and dram_mpki > 5:
            bottlenecks.append(f"LLCミス(L2mpki={l2_mpki:.0f},DRAMmpki={dram_mpki:.0f})")

    # 分岐ミス mpki > 10 → 分岐予測律速
    if branch_mpki > 10:
        bottlenecks.append(f"分岐ミス(mpki={branch_mpki:.1f})")

    # 何も引っかからない → 計算律速
    if not bottlenecks:
        if ipc >= 1.0:
            bottlenecks.append(f"計算律速(IPC={ipc:.2f})")
        elif l2_miss > 20:
            # L2ミス率は高いが DRAM mpki が小さい → L2 アクセス自体少ない計算律速
            bottlenecks.append(f"計算律速(L2アクセス少,IPC={ipc:.2f})")
        else:
            bottlenecks.append(f"計算律速(IPC={ipc:.2f})")

    return " / ".join(bottlenecks)


def main():
    base = Path(sys.argv[1]) if len(sys.argv) > 1 else \
        Path(__file__).parent.parent / "sniper_results"

    if not base.exists():
        print(f"ERROR: {base} not found", file=sys.stderr)
        sys.exit(1)

    benchmarks = sorted(d.name for d in base.iterdir()
                        if d.is_dir() and not d.name.startswith("."))

    rows = []
    for bench in benchmarks:
        bench_dir = base / bench
        print(f"  collecting {bench} ...", flush=True)
        stats = collect_benchmark(bench_dir)
        stats["benchmark"] = bench
        rows.append(stats)

    # ---- CSV 出力 ----
    csv_path = base / "bottleneck_analysis.csv"
    fieldnames = ["benchmark"] + METRICS + ["total_weight", "num_simpoints"]
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"\nCSV written: {csv_path}")

    # ---- テキストレポート ----
    report_path = base / "bottleneck_report.txt"
    with open(report_path, "w") as f:
        f.write("=" * 100 + "\n")
        f.write("  SPEC CPU2006 Sniper SimPoint ボトルネック解析レポート\n")
        f.write("=" * 100 + "\n\n")

        # ヘッダ
        hdr = (f"{'Benchmark':<18} {'IPC':>5} {'Idle%':>6} "
               f"{'BrMPKI':>7} "
               f"{'DTLB%':>6} {'DTLBmpki':>9} "
               f"{'L2TLBmpki':>10} "
               f"{'L1D%':>6} {'L2%':>5} {'L2mpki':>7} "
               f"{'DRAMmpki':>9} {'DRAMbw%':>8} "
               f"{'主なボトルネック'}")
        f.write(hdr + "\n")
        f.write("-" * 130 + "\n")

        for row in rows:
            def fmt(k, fmt_str=".1f", fallback="-"):
                v = row.get(k)
                return format(v, fmt_str) if v is not None else fallback

            label = bottleneck_label(row)
            line = (f"{row['benchmark']:<18} "
                    f"{fmt('ipc', '.3f'):>5} "
                    f"{fmt('idle_pct'):>6} "
                    f"{fmt('branch_mpki'):>7} "
                    f"{fmt('dtlb_miss_rate_pct'):>6} "
                    f"{fmt('dtlb_mpki', '.1f'):>9} "
                    f"{fmt('l2tlb_mpki', '.1f'):>10} "
                    f"{fmt('l1d_miss_rate_pct'):>6} "
                    f"{fmt('l2_miss_rate_pct'):>5} "
                    f"{fmt('l2_mpki', '.1f'):>7} "
                    f"{fmt('dram_mpki', '.1f'):>9} "
                    f"{fmt('dram_bw_util_pct'):>8} "
                    f"  {label}")
            f.write(line + "\n")

        f.write("\n")

        # ---- ボトルネック分類サマリ ----
        f.write("=" * 100 + "\n")
        f.write("  ボトルネック分類サマリ\n")
        f.write("=" * 100 + "\n\n")

        categories = {
            "DRAM律速 (dram_mpki > 50 or dram_bw > 50%)": [],
            "LLC+DRAM複合律速 (L2_mpki > 15 and DRAM_mpki > 15)": [],
            "LLCミス律速 (L2_mpki > 5 and DRAM_mpki > 5)": [],
            "TLB律速 (dtlb_mpki > 50 or l2tlb_mpki > 20)": [],
            "分岐ミス律速 (branch_mpki > 10)": [],
            "計算律速 (IPC >= 1.0 or キャッシュアクセス少)": [],
            "その他": [],
        }

        for row in rows:
            b = row["benchmark"]
            dram_mpki   = row.get("dram_mpki") or 0
            dram_bw     = row.get("dram_bw_util_pct") or 0
            l2_mpki     = row.get("l2_mpki") or 0
            dtlb_mpki   = row.get("dtlb_mpki") or 0
            l2tlb_mpki  = row.get("l2tlb_mpki") or 0
            branch_mpki = row.get("branch_mpki") or 0
            ipc         = row.get("ipc") or 0

            if dram_mpki > 50 or dram_bw > 50:
                categories["DRAM律速 (dram_mpki > 50 or dram_bw > 50%)"].append(b)
            elif l2_mpki > 15 and dram_mpki > 15:
                categories["LLC+DRAM複合律速 (L2_mpki > 15 and DRAM_mpki > 15)"].append(b)
            elif l2_mpki > 5 and dram_mpki > 5:
                categories["LLCミス律速 (L2_mpki > 5 and DRAM_mpki > 5)"].append(b)
            elif dtlb_mpki > 50 or l2tlb_mpki > 20:
                categories["TLB律速 (dtlb_mpki > 50 or l2tlb_mpki > 20)"].append(b)
            elif branch_mpki > 10:
                categories["分岐ミス律速 (branch_mpki > 10)"].append(b)
            elif ipc >= 1.0:
                categories["計算律速 (IPC >= 1.0 or キャッシュアクセス少)"].append(b)
            else:
                categories["その他"].append(b)

        for cat, benches in categories.items():
            if benches:
                f.write(f"【{cat}】\n")
                for b in benches:
                    row = next(r for r in rows if r["benchmark"] == b)
                    ipc = row.get("ipc") or 0
                    dmpki = row.get("dram_mpki") or 0
                    l2mpki = row.get("l2_mpki") or 0
                    l2m = row.get("l2_miss_rate_pct") or 0
                    dtlb = row.get("dtlb_mpki") or 0
                    bw = row.get("dram_bw_util_pct") or 0
                    brmk = row.get("branch_mpki") or 0
                    label = bottleneck_label(row)
                    f.write(f"  {b:<20} IPC={ipc:.3f}  DRAM_mpki={dmpki:.1f}  L2_mpki={l2mpki:.1f}  "
                            f"L2_miss={l2m:.1f}%  DTLB_mpki={dtlb:.1f}  Br_mpki={brmk:.1f}  "
                            f"DRAM_bw={bw:.1f}%\n")
                    f.write(f"    → {label}\n")
                f.write("\n")

        # ---- 詳細数値テーブル ----
        f.write("=" * 100 + "\n")
        f.write("  詳細数値 (重み付き平均)\n")
        f.write("=" * 100 + "\n\n")

        metric_labels = {
            "ipc":                      "IPC (加重平均)",
            "idle_pct":                 "Idle time (%)",
            "branch_mispredict_rate_pct": "分岐ミス率 (%)",
            "branch_mpki":              "分岐ミス MPKI",
            "dtlb_miss_rate_pct":       "D-TLB ミス率 (%)",
            "dtlb_mpki":                "D-TLB MPKI",
            "l2tlb_miss_rate_pct":      "L2-TLB ミス率 (%)",
            "l2tlb_mpki":               "L2-TLB MPKI",
            "l1i_miss_rate_pct":        "L1-I ミス率 (%)",
            "l1i_mpki":                 "L1-I MPKI",
            "l1d_miss_rate_pct":        "L1-D ミス率 (%)",
            "l1d_mpki":                 "L1-D MPKI",
            "l2_miss_rate_pct":         "L2 ミス率 (%)",
            "l2_mpki":                  "L2 MPKI",
            "dram_mpki":                "DRAM MPKI",
            "dram_latency_ns":          "DRAM 平均レイテンシ (ns)",
            "dram_bw_util_pct":         "DRAM 帯域利用率 (%)",
        }

        bench_names = [r["benchmark"] for r in rows]
        col_w = 14
        hdr2 = f"{'指標':<30}" + "".join(f"{b:>{col_w}}" for b in bench_names)
        f.write(hdr2 + "\n")
        f.write("-" * (30 + col_w * len(bench_names)) + "\n")

        for m, label in metric_labels.items():
            line2 = f"{label:<30}"
            for row in rows:
                v = row.get(m)
                line2 += f"{format(v, '.2f') if v is not None else '-':>{col_w}}"
            f.write(line2 + "\n")

    print(f"Report written: {report_path}")

    # 標準出力にもサマリを表示
    print()
    with open(report_path) as f:
        print(f.read())


if __name__ == "__main__":
    main()
