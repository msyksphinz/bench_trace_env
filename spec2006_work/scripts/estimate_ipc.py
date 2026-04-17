#!/usr/bin/env python3
"""
Estimate overall IPC and SPEC/GHz for a SPEC CPU 2006 benchmark from SimPoint + Sniper results.

Usage:
  SIMPOINT_DIR=... SIMULATION_DIR=... [SPEC_ROOT=...] [FREQ_GHZ=1] [REF_IPC_TIMES_FREQ_GHZ=0.0667] \\
    python estimate_ipc.py <benchmark>

Outputs:
  - <simulation_dir>/<benchmark>/ipc_estimation.csv   (per-SimPoint rows + summary)
  - <simulation_dir>/ipc_summary.csv                  (one row per benchmark, overwritten)
  - <simulation_dir>/<benchmark>/ipc_summary.txt     (human-readable)
"""

import csv
import os
import re
import sys
from pathlib import Path


def get_env(name: str, default: str | None = None) -> str:
    """Get environment variable; if required and unset, exit with SystemExit."""
    v = os.environ.get(name)
    if v is not None:
        return v
    if default is not None:
        return default
    raise SystemExit(f"Error: {name} is required. Set it in the environment.")


def read_reftime(spec_root: str, benchmark: str) -> float | None:
    """Read SPEC reference time (seconds) from the second line of reftime; return None if missing or invalid."""
    path = Path(spec_root) / "benchspec/CPU2006" / benchmark / "data/ref/reftime"
    if not path.exists():
        return None
    with open(path) as f:
        lines = f.readlines()
    if len(lines) < 2:
        return None
    try:
        return float(lines[1].strip().replace("\r", ""))
    except ValueError:
        return None


def load_simpoints(path: Path) -> dict[int, int]:
    """Load SimPoints file. Format: one line per 'simpoint_index cluster_id'. Returns cluster_id -> simpoint_index."""
    out: dict[int, int] = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) >= 2:
                try:
                    simpoint_idx, cluster_id = int(parts[0]), int(parts[1])
                    out[cluster_id] = simpoint_idx
                except ValueError:
                    pass
    return out


def load_weights(path: Path) -> dict[int, float]:
    """Load weights file. Format: one line per 'weight cluster_id'. Returns cluster_id -> weight."""
    out: dict[int, float] = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) >= 2:
                try:
                    weight, cluster_id = float(parts[0]), int(parts[1])
                    out[cluster_id] = weight
                except ValueError:
                    pass
    return out


def extract_ipc_from_sqlite(path: Path, freq_ghz: float = 2.0) -> float | None:
    """Compute IPC from sim.stats.sqlite3 using the correct formula.

    Instructions = performance_model.instruction_count at roi-end
    Elapsed      = thread.elapsed_time[roi-end] - thread.elapsed_time[roi-begin]  (femtoseconds)
    Cycles       = elapsed_fs / clock_period_fs  where clock_period_fs = 1e12 / (freq_ghz * 1e9)
    IPC          = instructions / cycles
    """
    try:
        import sqlite3 as _sqlite3
        conn = _sqlite3.connect(str(path))
        cur = conn.cursor()

        def _get(prefix: str, obj: str, metric: str):
            cur.execute(
                '''SELECT v.value FROM "values" v
                   JOIN names n ON v.nameid = n.nameid
                   JOIN prefixes p ON v.prefixid = p.prefixid
                   WHERE p.prefixname = ? AND n.objectname = ? AND n.metricname = ?''',
                (prefix, obj, metric),
            )
            row = cur.fetchone()
            return int(row[0]) if row else None

        instructions = _get("roi-end", "performance_model", "instruction_count")
        elapsed_end  = _get("roi-end",   "thread", "elapsed_time")
        elapsed_beg  = _get("roi-begin", "thread", "elapsed_time")
        conn.close()

        if instructions is None or elapsed_end is None or elapsed_beg is None:
            return None
        delta_fs = elapsed_end - elapsed_beg
        if delta_fs <= 0:
            return None
        # clock period in femtoseconds: 1 s / freq_hz = 1e15 fs / (freq_ghz * 1e9)
        clock_period_fs = 1e15 / (freq_ghz * 1e9)
        cycles = delta_fs / clock_period_fs
        return round(instructions / cycles, 4)
    except Exception:
        return None


def extract_ipc_from_simout(path: Path) -> float | None:
    """Return IPC from the last field of the line starting with '  IPC' in sim.out."""
    try:
        with open(path) as f:
            for line in f:
                if line.startswith("  IPC"):
                    parts = line.split()
                    if parts:
                        return float(parts[-1])
    except OSError:
        pass
    return None


def get_ipc(sim_dir: Path, freq_ghz: float = 2.0) -> float | None:
    """Get IPC from sim_dir.

    Priority:
      1. sim.out          — Sniper's own formatted output; always correct
      2. sim.stats.sqlite3 — raw database; correct when read with extract_ipc_from_sqlite
      3. sim.stats.json   — may be corrupted by shell redirect; used as last resort
    """
    sim_out = sim_dir / "sim.out"
    if sim_out.exists():
        ipc = extract_ipc_from_simout(sim_out)
        if ipc is not None:
            return ipc
    sqlite_file = sim_dir / "sim.stats.sqlite3"
    if sqlite_file.exists():
        ipc = extract_ipc_from_sqlite(sqlite_file, freq_ghz)
        if ipc is not None:
            return ipc
    return None


def compute_spec_ghz(
    overall_ipc: float,
    ref_time_sec: float | None,
    freq_ghz: float,
    ref_ipc_times_freq_ghz: float,
) -> tuple[float | None, float | None, float]:
    """
    Compute run_time (s), ratio, and SPEC/GHz.
    Reference machine: SPEC CPU 2006 Sun UltraSparc II 296 MHz. SPEC/GHz = IPC / REF_IPC_TIMES_FREQ_GHZ.

    Returns:
        (run_time_sec, ratio, spec_per_ghz). run_time_sec and ratio are None when ref_time is not set.
    """
    if overall_ipc <= 0 or ref_ipc_times_freq_ghz <= 0:
        return None, None, overall_ipc / ref_ipc_times_freq_ghz if ref_ipc_times_freq_ghz > 0 else 0.0

    spec_per_ghz = overall_ipc / ref_ipc_times_freq_ghz

    if ref_time_sec is None or ref_time_sec <= 0 or freq_ghz <= 0:
        return None, None, spec_per_ghz

    run_time_sec = ref_time_sec * ref_ipc_times_freq_ghz / (overall_ipc * freq_ghz)
    ratio = ref_time_sec / run_time_sec
    return run_time_sec, ratio, spec_per_ghz


def _write_outputs(
    benchmark: str,
    simulation_dir: Path,
    summary_csv: Path,
    rows: list[tuple[int, int, float, float]],
    total_weighted_ipc: float,
    total_weight: float,
    overall_ipc: float,
    ref_time_sec: float | None,
    run_time_sec: float | None,
    ratio: float | None,
    spec_per_ghz: float,
    freq_ghz: float,
    ref_ipc_times_freq_ghz: float,
) -> None:
    """Write ipc_estimation.csv, ipc_summary.csv, and ipc_summary.txt."""
    output_csv = simulation_dir / "ipc_estimation.csv"
    summary_txt = simulation_dir / "ipc_summary.txt"

    with open(output_csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["subcmd", "simpoint", "weight", "ipc", "weighted_ipc"])
        for subcmd, simpoint_idx, weight, ipc in rows:
            w.writerow([subcmd, simpoint_idx, weight, ipc, ipc * weight])
        f.write("# summary: overall_ipc,total_weight,num_simpoints,ref_time_sec,run_time_sec,ratio,spec_per_ghz\n")
        w.writerow([
            f"{overall_ipc:.6f}", f"{total_weight:.6f}", len(rows),
            f"{ref_time_sec}" if ref_time_sec is not None else "",
            f"{run_time_sec:.6f}" if run_time_sec is not None else "",
            f"{ratio:.6f}" if ratio is not None else "",
            f"{spec_per_ghz:.6f}",
        ])

    summary_header = [
        "benchmark", "overall_ipc", "total_weight", "num_simpoints",
        "ref_time_sec", "run_time_sec", "ratio", "spec_per_ghz",
    ]
    summary_row = [
        benchmark, f"{overall_ipc:.6f}", f"{total_weight:.6f}", len(rows),
        f"{ref_time_sec}" if ref_time_sec is not None else "",
        f"{run_time_sec:.6f}" if run_time_sec is not None else "",
        f"{ratio:.6f}" if ratio is not None else "",
        f"{spec_per_ghz:.6f}",
    ]
    if summary_csv.exists():
        with open(summary_csv) as f:
            r = csv.reader(f)
            next(r, None)
            existing = [row for row in r if row and row[0] != benchmark]
        with open(summary_csv, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(summary_header)
            w.writerows(existing)
            w.writerow(summary_row)
    else:
        with open(summary_csv, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(summary_header)
            w.writerow(summary_row)

    with open(summary_txt, "w") as f:
        f.write(f"Benchmark: {benchmark}\n")
        f.write(f"Total SimPoints: {len(rows)}\n")
        f.write(f"Total Weight Sum: {total_weight}\n")
        f.write(f"Estimated Overall IPC: {overall_ipc}\n")
        if ref_time_sec is not None and run_time_sec is not None:
            f.write(f"Reference time (baseline, s): {ref_time_sec}\n")
            f.write(f"Run time (simulated @ {freq_ghz} GHz, s): {run_time_sec}\n")
            f.write(f"Ratio (reference_time / run_time): {ratio}\n")
        f.write(f"SPEC/GHz: {spec_per_ghz}\n")
        f.write("\n")
        f.write(f"Detailed results (for verification): {output_csv}\n")
        f.write(f"Aggregate summary: {summary_csv}\n")
        f.write("\n")
        f.write("SPEC/GHz from execution time (SPEC CPU 2006: reference = Sun UltraSparc II 296 MHz):\n")
        f.write(f"  ref_IPC * ref_freq_GHz = REF_IPC_TIMES_FREQ_GHZ = {ref_ipc_times_freq_ghz}\n")
        f.write("  run_time = ref_time * REF_IPC_TIMES_FREQ_GHZ / (IPC * freq_GHz)\n")
        f.write("  ratio = reference_time / run_time\n")
        f.write("  SPEC/GHz = IPC / REF_IPC_TIMES_FREQ_GHZ\n")
        f.write("For composite SPECint-style score, use geometric mean of spec_per_ghz.\n")


def main() -> None:
    """Parse args and env, compute SimPoint-weighted IPC and SPEC/GHz, and write the three output files."""
    if len(sys.argv) < 2:
        print(
            "Usage: SIMPOINT_DIR=... SIMULATION_DIR=... [SPEC_ROOT=...] [FREQ_GHZ=1] [REF_IPC_TIMES_FREQ_GHZ=0.0667]",
            file=sys.stderr,
        )
        print("  python estimate_ipc.py <benchmark>", file=sys.stderr)
        sys.exit(1)

    benchmark = sys.argv[1]
    # --- Environment and paths ---
    simpoint_dir = Path(get_env("SIMPOINT_DIR")) / benchmark
    simulation_dir = Path(get_env("SIMULATION_DIR")) / benchmark
    freq_ghz = float(get_env("FREQ_GHZ", "1"))
    ref_ipc_times_freq_ghz = float(get_env("REF_IPC_TIMES_FREQ_GHZ", "0.0667"))
    spec_root = os.environ.get("SPEC_ROOT")
    ref_time_sec = read_reftime(spec_root, benchmark) if spec_root else None

    # --- Check directories exist ---
    if not simpoint_dir.is_dir():
        print(f"Error: SimPoint directory {simpoint_dir} not found.", file=sys.stderr)
        print(f"Please run 'make run_simpoint_{benchmark}' first.", file=sys.stderr)
        sys.exit(1)
    if not simulation_dir.is_dir():
        print(f"Error: Simulation directory {simulation_dir} not found.", file=sys.stderr)
        print(f"Please run 'make run_sniper_{benchmark}' first.", file=sys.stderr)
        sys.exit(1)

    weights_files = sorted(simpoint_dir.glob("*.weights"))
    if not weights_files:
        print(f"Error: No weights files found in {simpoint_dir}.", file=sys.stderr)
        sys.exit(1)

    # --- Collect IPC per SimPoint and accumulate weighted sum ---
    rows: list[tuple[int, int, float, float]] = []
    total_weighted_ipc = 0.0
    total_weight = 0.0

    print("=== Estimating IPC for", benchmark, "===")
    print()
    print("Processing SimPoint results...")
    print()

    for wpath in weights_files:
        # subcmd from filename: bbv_1.out.0.weights -> 1
        base = wpath.name
        m = re.match(r"^bbv_(\d+)\.", base)
        if not m:
            print(f"Warning: Could not extract subcmd from {wpath}, skipping", file=sys.stderr)
            continue
        subcmd = int(m.group(1))

        # bbv_1.out.0.weights -> bbv_1.out.0.simpoints
        simpoints_path = wpath.parent / (wpath.stem + ".simpoints")
        if not simpoints_path.exists():
            print(f"Warning: SimPoints file not found for {wpath}", file=sys.stderr)
            continue

        cluster_to_simpoint = load_simpoints(simpoints_path)
        cluster_to_weight = load_weights(wpath)

        for cluster_id, simpoint_idx in cluster_to_simpoint.items():
            weight = cluster_to_weight.get(cluster_id)
            if weight is None:
                print(f"Warning: No weight for cluster {cluster_id}", file=sys.stderr)
                continue

            sim_dir = simulation_dir / f"subcmd_{subcmd}" / f"simpoint_{simpoint_idx}"
            ipc = get_ipc(sim_dir, freq_ghz=freq_ghz)
            if ipc is None:
                print(f"Warning: Could not extract IPC: {sim_dir}", file=sys.stderr)
                continue

            weighted_ipc = ipc * weight
            rows.append((subcmd, simpoint_idx, weight, ipc))
            total_weighted_ipc += weighted_ipc
            total_weight += weight
            print(f"  [subcmd {subcmd}] SimPoint {simpoint_idx:5}: IPC={ipc:.4f}, Weight={weight:.6f}, Weighted_IPC={weighted_ipc:.6f}")

    if total_weight <= 0:
        print("Error: Total weight is zero or invalid.", file=sys.stderr)
        sys.exit(1)

    # --- Compute weighted average IPC and SPEC/GHz ---
    overall_ipc = total_weighted_ipc / total_weight
    run_time_sec, ratio, spec_per_ghz = compute_spec_ghz(
        overall_ipc, ref_time_sec, freq_ghz, ref_ipc_times_freq_ghz
    )

    print()
    print("=== Results ===")
    print("Total SimPoints processed:", len(rows))
    print("Total weight sum:", total_weight)
    print()
    print("======================================")
    print("Estimated Overall IPC:", f"{overall_ipc:.6f}")
    if ref_time_sec is not None and run_time_sec is not None:
        print("Reference time (baseline):", ref_time_sec, "s")
        print(f"Run time (simulated @ {freq_ghz} GHz):", f"{run_time_sec:.6f}", "s")
        print("Ratio (ref_time/run_time):", f"{ratio:.6f}")
    print("SPEC/GHz:", f"{spec_per_ghz:.6f}")
    print("======================================")
    print()

    # --- Write ipc_estimation.csv, ipc_summary.csv, ipc_summary.txt ---
    summary_csv = Path(get_env("SIMULATION_DIR")) / "ipc_summary.csv"
    output_csv = simulation_dir / "ipc_estimation.csv"
    summary_txt = simulation_dir / "ipc_summary.txt"
    _write_outputs(
        benchmark, simulation_dir, summary_csv, rows,
        total_weighted_ipc, total_weight, overall_ipc,
        ref_time_sec, run_time_sec, ratio, spec_per_ghz,
        freq_ghz, ref_ipc_times_freq_ghz,
    )

    print("Summary saved to:", summary_txt)
    print("Detailed CSV (with summary row) saved to:", output_csv)
    print("Aggregate summary CSV:", summary_csv)
    print()
    print("=== Completed IPC estimation for", benchmark, "===")


if __name__ == "__main__":
    main()
