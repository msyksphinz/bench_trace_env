#!/usr/bin/env bash
# CI pipeline: same steps as .github/workflows/simpoint.yml.
# Run from repo root or spec2006_work. Use this script locally to reproduce CI.
#
# Usage:
#   ./scripts/ci_pipeline.sh [--phase 1|2|3]   # from spec2006_work
#   cd spec2006_work && ./scripts/ci_pipeline.sh
#
# Env (optional):
#   CDROM_DIR     - Path to extracted SPEC CPU2006 (required for phase 1)
#   NPROC         - Parallel jobs (default: nproc/2)
#   SIMPOINT_INTERVAL - If unset, read from Makefile/simpoint_config.mk
#   BENCHMARKS    - Space-separated benchmark list (default: all)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SPEC2006_WORK="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$SPEC2006_WORK/.." && pwd)"

# Benchmark list (must match Makefile bench_lists)
DEFAULT_BENCHMARKS="400.perlbench 401.bzip2 403.gcc 429.mcf 445.gobmk 456.hmmer 458.sjeng 462.libquantum 464.h264ref 471.omnetpp 473.astar 483.xalancbmk"
BENCHMARKS="${BENCHMARKS:-$DEFAULT_BENCHMARKS}"
NPROC="${NPROC:-$(($(nproc 2>/dev/null || echo 2) / 2))}"
# SimPoint params: use Makefile/simpoint_config.mk as single source when unset
if [[ -z "${SIMPOINT_INTERVAL:-}" ]]; then
  SIMPOINT_INTERVAL="$(make -s -C "$SPEC2006_WORK" print-simpoint-interval 2>/dev/null)" || SIMPOINT_INTERVAL=1000000
fi

RUN_PHASE_1=false
RUN_PHASE_2=false
RUN_PHASE_3=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --phase)
      shift
      case "${1:-}" in
        1) RUN_PHASE_1=true ;;
        2) RUN_PHASE_2=true ;;
        3) RUN_PHASE_3=true ;;
        *) echo "Usage: $0 [--phase 1|2|3]. Unknown phase: $1" >&2; exit 1 ;;
      esac
      shift
      ;;
    *)
      echo "Usage: $0 [--phase 1|2|3]" >&2
      exit 1
      ;;
  esac
done

if ! $RUN_PHASE_1 && ! $RUN_PHASE_2 && ! $RUN_PHASE_3; then
  RUN_PHASE_1=true
  RUN_PHASE_2=true
  RUN_PHASE_3=true
fi

cd "$SPEC2006_WORK"
export SIMPOINT_INTERVAL

# --- Phase 1: build QEMU, prepare SPEC, BBV, SimPoint, build Sniper, clean BBV ---
phase1() {
  echo "=== Phase 1: build-qemu, prepare, build, run_bbv, run_simpoint, build_sniper, clean-bbv ==="
  if [[ -z "${CDROM_DIR:-}" ]]; then
    echo "Error: CDROM_DIR is required for phase 1. Set it to the path of extracted SPEC CPU2006, e.g.:" >&2
    echo "  CDROM_DIR=/path/to/spec2006_cdrom $0" >&2
    echo "  or run only phase 2/3: $0 --phase 2   or   $0 --phase 3" >&2
    exit 1
  fi
  make -C "$REPO_ROOT" build-qemu
  make prepare CDROM_DIR="$CDROM_DIR"
  make build -j"$NPROC"
  make run_bbv -j"$NPROC"
  make build_simpoint
  make run_simpoint -j"$NPROC"
  make build_sniper
  make clean-bbv
  echo "=== Phase 1 done ==="
}

# --- Phase 2: enumerate SimPoints and run SIFT + Sniper per SimPoint ---
phase2() {
  echo "=== Phase 2: SIFT generation and Sniper simulation for each SimPoint ==="
  SIMPOINT_DIR="$SPEC2006_WORK/simpoint_results"
  SPEC_ROOT="$SPEC2006_WORK/spec2006_installed"
  SPECINVOKE="${SPEC_ROOT}/bin/specinvoke"

  TASK_FILE="$(mktemp)"
  trap "rm -f $TASK_FILE" EXIT

  for benchmark in $BENCHMARKS; do
    simpoint_dir="$SIMPOINT_DIR/$benchmark"
    if [[ ! -d "$simpoint_dir" ]]; then
      echo "[SKIP] SimPoint directory not found for $benchmark"
      continue
    fi
    run_dir="$SPEC_ROOT/benchspec/CPU2006/$benchmark/run/run_base_ref_gcc.0000"
    if [[ ! -d "$run_dir" ]]; then
      echo "[SKIP] Run directory not found for $benchmark"
      continue
    fi
    subcmds="$(cd "$run_dir" && "$SPECINVOKE" -n 2>&1 | grep -v '^#' | grep -v '^timer' | grep -v '^$' || true)"
    echo "=== Enumerating SimPoints for $benchmark ==="
    echo "$subcmds" | nl -nln -w1 -s$'\t' | while IFS=$'\t' read -r cmd_num cmd_raw; do
      simpoint_file="$simpoint_dir/bbv_${cmd_num}.out."*.simpoints
      weights_file="$simpoint_dir/bbv_${cmd_num}.out."*.weights
      sf="$(ls $simpoint_file 2>/dev/null | head -1)"
      wf="$(ls $weights_file 2>/dev/null | head -1)"
      if [[ -n "${sf:-}" && -n "${wf:-}" ]]; then
        paste -d ' ' "$sf" "$wf" | while IFS=' ' read -r simpoint _ weight _; do
          if [[ -n "${simpoint:-}" && ! "$simpoint" =~ ^# ]]; then
            echo "$benchmark $cmd_num $simpoint $weight" >> "$TASK_FILE"
          fi
        done
      fi
    done
  done

  total_tasks="$(wc -l < "$TASK_FILE" 2>/dev/null || echo 0)"
  echo "=== Found $total_tasks SimPoints to process, parallelism: $NPROC ==="

  FAILED_FILE="$(mktemp)"
  trap "rm -f $TASK_FILE $FAILED_FILE" EXIT

  process_task() {
    local line="$1"
    IFS=' ' read -r benchmark subcmd simpoint weight <<< "$line"
    echo "[PROCESS] $benchmark subcmd=$subcmd simpoint=$simpoint weight=$weight"
    if SIMPOINT_INTERVAL="$SIMPOINT_INTERVAL" make run_sift_${benchmark}_${subcmd}_${simpoint}; then
      echo "[SUCCESS] $benchmark subcmd=$subcmd simpoint=$simpoint"
      return 0
    else
      echo "[FAILED] $benchmark subcmd=$subcmd simpoint=$simpoint"
      echo "$benchmark $subcmd $simpoint" >> "$FAILED_FILE"
      return 1
    fi
  }
  export -f process_task
  export SIMPOINT_INTERVAL
  export FAILED_FILE

  cat "$TASK_FILE" | xargs -P "$NPROC" -I {} bash -c 'process_task "{}"'

  failed="$(wc -l < "$FAILED_FILE" 2>/dev/null || echo 0)"
  echo "=== Phase 2 done: processed $total_tasks SimPoints, $failed failed ==="
  if [[ "$failed" -gt 0 ]]; then
    echo ""
    echo "=== Failed SimPoints: benchmark subcmd simpoint ==="
    cat "$FAILED_FILE"
    exit 1
  fi
}

# --- Phase 3: estimate overall IPC ---
phase3() {
  echo "=== Phase 3: estimate_ipc ==="
  make estimate_ipc
  echo "=== Phase 3 done ==="
}

if $RUN_PHASE_1; then phase1; fi
if $RUN_PHASE_2; then phase2; fi
if $RUN_PHASE_3; then phase3; fi

echo "=== CI pipeline completed ==="
