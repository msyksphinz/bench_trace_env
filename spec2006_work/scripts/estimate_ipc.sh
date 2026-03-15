#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -lt 1 ]; then
  echo "Usage: SIMPOINT_DIR=... SIMULATION_DIR=... [SPEC_ROOT=...] [FREQ_GHZ=1] [REF_IPC_TIMES_FREQ_GHZ=0.0667] $0 <benchmark>" >&2
  echo "" >&2
  echo "This script estimates the overall IPC of a benchmark by computing" >&2
  echo "the weighted average of IPCs from all SimPoint simulations," >&2
  echo "and optionally computes SPEC/GHz using reference time from SPEC_ROOT." >&2
  exit 1
fi

benchmark="$1"

: "${SIMPOINT_DIR:?SIMPOINT_DIR is required}"
: "${SIMULATION_DIR:?SIMULATION_DIR is required}"
: "${FREQ_GHZ:=1}"

# SPEC CPU 2006 reference machine: Sun UltraSparc II at 296 MHz (run rules 4.3.1).
# ratio = reference_time / run_time; SPEC/GHz = ratio / our_freq_GHz.
# total_instructions = ref_time * (ref_IPC * ref_freq_Hz); run_time = total_instructions / (our_IPC * our_freq_Hz).
# So ratio = our_IPC * our_freq_Hz / (ref_IPC * ref_freq_Hz), SPEC/GHz = our_IPC / (ref_IPC * ref_freq_GHz).
# ref_freq_GHz = 0.296. ref_IPC is unknown; use REF_IPC_TIMES_FREQ_GHZ = ref_IPC*ref_freq_GHz so that
# SPEC/GHz ≈ 10--20 for typical IPC 0.5--1.5 (e.g. 1/15 ≈ 0.0667 => SPEC/GHz ≈ 15*IPC).
: "${REF_IPC_TIMES_FREQ_GHZ:=0.0667}"

simpoint_dir="${SIMPOINT_DIR}/${benchmark}"
simulation_dir="${SIMULATION_DIR}/${benchmark}"

# Reference time (seconds) for SPEC/GHz; read from SPEC_ROOT if set
ref_time_sec=""
if [ -n "${SPEC_ROOT:-}" ] && [ -f "${SPEC_ROOT}/benchspec/CPU2006/${benchmark}/data/ref/reftime" ]; then
  ref_time_sec=$(sed -n '2p' "${SPEC_ROOT}/benchspec/CPU2006/${benchmark}/data/ref/reftime" | tr -d '\r')
fi

echo "=== Estimating IPC for ${benchmark} ==="

# Check if directories exist
if [ ! -d "${simpoint_dir}" ]; then
  echo "Error: SimPoint directory ${simpoint_dir} not found." >&2
  echo "Please run 'make run_simpoint_${benchmark}' first." >&2
  exit 1
fi

if [ ! -d "${simulation_dir}" ]; then
  echo "Error: Simulation directory ${simulation_dir} not found." >&2
  echo "Please run 'make run_sniper_${benchmark}' first." >&2
  exit 1
fi

# Find all weights files
weights_files=$(find "${simpoint_dir}" -type f -name "*.weights" | sort)

if [ -z "${weights_files}" ]; then
  echo "Error: No weights files found in ${simpoint_dir}." >&2
  exit 1
fi

# Output CSV: detailed rows for verification, then summary row
output_csv="${simulation_dir}/ipc_estimation.csv"
summary_csv="${SIMULATION_DIR}/ipc_summary.csv"
echo "subcmd,simpoint,weight,ipc,weighted_ipc" > "${output_csv}"

# Process each weights file
# Use decimal form for bc (avoid "syntax error" when bc outputs scientific notation and we reuse it)
total_weighted_ipc=0.0
total_weight=0.0
num_simpoints=0

# Normalize a number to decimal for bc (handles scientific notation from bc or input)
bc_decimal() { printf '%f' "${1:-0}" 2>/dev/null || echo "0"; }

echo ""
echo "Processing SimPoint results..."
echo ""

while IFS= read -r weights_file; do
  # Extract subcmd number from filename (e.g., bbv_1.out.0.weights -> 1)
  basename_weights=$(basename "${weights_file}")
  subcmd=$(echo "${basename_weights}" | grep -oP '^bbv_\K[0-9]+' || echo "")

  if [ -z "${subcmd}" ]; then
    echo "Warning: Could not extract subcmd from ${weights_file}, skipping" >&2
    continue
  fi

  # Find corresponding simpoints file
  simpoints_file="${weights_file%.weights}.simpoints"
  if [ ! -f "${simpoints_file}" ]; then
    echo "Warning: SimPoints file not found: ${simpoints_file}" >&2
    continue
  fi

  # Create associative arrays to map cluster_id to simpoint_index and weight
  declare -A cluster_to_simpoint
  declare -A cluster_to_weight

  # Read simpoints file: <simpoint_index> <cluster_id>
  while read -r simpoint_idx cluster_id rest; do
    # Skip empty lines or comments
    if [ -z "${simpoint_idx}" ] || [[ "${simpoint_idx}" =~ ^# ]]; then
      continue
    fi
    cluster_to_simpoint[$cluster_id]=$simpoint_idx
  done < "${simpoints_file}"

  # Read weights file: <weight> <cluster_id>
  while read -r weight cluster_id rest; do
    # Skip empty lines or comments
    if [ -z "${weight}" ] || [[ "${weight}" =~ ^# ]]; then
      continue
    fi
    cluster_to_weight[$cluster_id]=$weight
  done < "${weights_file}"

  # Process each cluster
  for cluster_id in "${!cluster_to_simpoint[@]}"; do
    simpoint_idx="${cluster_to_simpoint[$cluster_id]}"
    weight="${cluster_to_weight[$cluster_id]}"

    if [ -z "${weight}" ]; then
      echo "Warning: No weight found for cluster ${cluster_id}" >&2
      continue
    fi

    # Find corresponding simulation output
    # Prefer sim.stats.json (from convert_sniper_sqlite); fallback to sim.out
    sim_dir="${simulation_dir}/subcmd_${subcmd}/simpoint_${simpoint_idx}"
    stats_json="${sim_dir}/sim.stats.json"
    sim_out_path="${sim_dir}/sim.out"

    # Extract IPC: from sim.stats.json (core.instructions / (time_fs/1e6)) or from sim.out
    ipc=""
    if [ -f "${stats_json}" ]; then
      ipc=$(python3 -c "
import re, sys
path = sys.argv[1]
try:
    with open(path) as f:
        c = f.read()
    inst = re.search(r'\"core\.instructions\"\s*:\s*(\d+)', c)
    t = re.search(r'\"barrier\.global_time\"\s*:\s*(\d+)', c) or re.search(r'\"thread\.elapsed_time\"\s*:\s*(\d+)', c)
    if inst and t:
        time_fs = int(t.group(1))
        cycles = time_fs / 1e6
        print(round(int(inst.group(1)) / cycles, 4) if cycles else '')
except Exception:
    pass
" "${stats_json}" 2>/dev/null) || ipc=""
    fi
    if [ -z "${ipc}" ] && [ -f "${sim_out_path}" ]; then
      ipc=$(grep -m1 "^  IPC" "${sim_out_path}" 2>/dev/null | awk '{print $NF}') || ipc=""
    fi

    if [ -z "${ipc}" ]; then
      echo "Warning: Could not extract IPC (no sim.stats.json or sim.out): ${sim_dir}" >&2
      continue
    fi

    # Calculate weighted IPC (normalize to decimal so bc never sees scientific notation on next use)
    weighted_ipc=$(echo "$(bc_decimal "${ipc}") * $(bc_decimal "${weight}")" | bc -l 2>/dev/null)
    weighted_ipc=$(bc_decimal "${weighted_ipc}")

    # Add to CSV
    echo "${subcmd},${simpoint_idx},${weight},${ipc},${weighted_ipc}" >> "${output_csv}"

    # Update totals (inputs/output in decimal to avoid bc "syntax error")
    total_weighted_ipc=$(echo "$(bc_decimal "${total_weighted_ipc}") + $(bc_decimal "${weighted_ipc}")" | bc -l 2>/dev/null)
    total_weighted_ipc=$(bc_decimal "${total_weighted_ipc}")
    total_weight=$(echo "$(bc_decimal "${total_weight}") + $(bc_decimal "${weight}")" | bc -l 2>/dev/null)
    total_weight=$(bc_decimal "${total_weight}")
    num_simpoints=$((num_simpoints + 1))

    printf "  [subcmd %s] SimPoint %5s: IPC=%.4f, Weight=%.6f, Weighted_IPC=%.6f\n" \
           "${subcmd}" "${simpoint_idx}" "${ipc}" "${weight}" "${weighted_ipc}"
  done

  # Clean up associative arrays
  unset cluster_to_simpoint
  unset cluster_to_weight

done <<< "${weights_files}"

echo ""
echo "=== Results ==="
echo "Total SimPoints processed: ${num_simpoints}"
echo "Total weight sum: ${total_weight}"

if (( $(echo "$(bc_decimal "${total_weight}") > 0" | bc -l 2>/dev/null) )); then
  overall_ipc=$(echo "scale=6; $(bc_decimal "${total_weighted_ipc}") / $(bc_decimal "${total_weight}")" | bc -l 2>/dev/null)
  overall_ipc=$(bc_decimal "${overall_ipc}")

  # SPEC/GHz from execution time (SPEC CPU 2006 run rules 4.3.1):
  # Reference machine = Sun UltraSparc II at 296 MHz. ratio = reference_time / run_time; SPEC/GHz = ratio / our_freq_GHz.
  # total_instructions = ref_time * (ref_IPC * ref_freq_Hz); run_time = total_instructions / (our_IPC * our_freq_Hz).
  # So run_time = ref_time * REF_IPC_TIMES_FREQ_GHZ / (our_IPC * our_freq_GHz),
  # ratio = our_IPC * our_freq_GHz / REF_IPC_TIMES_FREQ_GHZ, SPEC/GHz = our_IPC / REF_IPC_TIMES_FREQ_GHZ.
  run_time_sec=""
  ratio=""
  if [ -n "${ref_time_sec}" ] && [ "$(echo "$(bc_decimal "${overall_ipc}") * $(bc_decimal "${FREQ_GHZ}") > 0" | bc -l 2>/dev/null)" -eq 1 ] && [ "$(echo "$(bc_decimal "${REF_IPC_TIMES_FREQ_GHZ}") > 0" | bc -l 2>/dev/null)" -eq 1 ]; then
    run_time_sec=$(echo "scale=6; $(bc_decimal "${ref_time_sec}") * $(bc_decimal "${REF_IPC_TIMES_FREQ_GHZ}") / ($(bc_decimal "${overall_ipc}") * $(bc_decimal "${FREQ_GHZ}"))" | bc -l 2>/dev/null)
    run_time_sec=$(bc_decimal "${run_time_sec}")
    ratio=$(echo "scale=6; $(bc_decimal "${ref_time_sec}") / $(bc_decimal "${run_time_sec}")" | bc -l 2>/dev/null)
    ratio=$(bc_decimal "${ratio}")
    spec_per_ghz=$(echo "scale=6; $(bc_decimal "${ratio}") / $(bc_decimal "${FREQ_GHZ}")" | bc -l 2>/dev/null)
    spec_per_ghz=$(bc_decimal "${spec_per_ghz}")
  else
    # Fallback when ref_time or REF_IPC_TIMES_FREQ_GHZ not set: SPEC/GHz = IPC / default_ref (so still scaled)
    spec_per_ghz=$(echo "scale=6; $(bc_decimal "${overall_ipc}") / $(bc_decimal "${REF_IPC_TIMES_FREQ_GHZ}")" | bc -l 2>/dev/null)
    spec_per_ghz=$(bc_decimal "${spec_per_ghz}")
  fi

  echo ""
  echo "======================================"
  echo "Estimated Overall IPC: ${overall_ipc}"
  if [ -n "${ref_time_sec}" ] && [ -n "${run_time_sec}" ]; then
    echo "Reference time (baseline): ${ref_time_sec} s"
    echo "Run time (simulated @ ${FREQ_GHZ} GHz): ${run_time_sec} s"
    echo "Ratio (ref_time/run_time): ${ratio}"
    echo "SPEC/GHz: ${spec_per_ghz}"
  else
    echo "SPEC/GHz: ${spec_per_ghz} (ref_time not set; equals IPC at ${FREQ_GHZ} GHz)"
  fi
  echo "======================================"
  echo ""

  # Append summary row to detailed CSV for later verification
  echo "# summary: overall_ipc,total_weight,num_simpoints,ref_time_sec,run_time_sec,ratio,spec_per_ghz" >> "${output_csv}"
  echo "${overall_ipc},${total_weight},${num_simpoints},${ref_time_sec:-},${run_time_sec:-},${ratio:-},${spec_per_ghz}" >> "${output_csv}"

  # Overwrite aggregate summary CSV: keep other benchmarks' rows, replace this benchmark's row (no append/duplicate).
  summary_header="benchmark,overall_ipc,total_weight,num_simpoints,ref_time_sec,run_time_sec,ratio,spec_per_ghz"
  summary_line="${benchmark},${overall_ipc},${total_weight},${num_simpoints},${ref_time_sec:-},${run_time_sec:-},${ratio:-},${spec_per_ghz}"
  if [ -f "${summary_csv}" ]; then
    {
      echo "${summary_header}"
      awk -F, -v bench="${benchmark}" 'NR>1 && $1!=bench' "${summary_csv}"
      echo "${summary_line}"
    } > "${summary_csv}.tmp" && mv "${summary_csv}.tmp" "${summary_csv}"
  else
    echo "${summary_header}" > "${summary_csv}"
    echo "${summary_line}" >> "${summary_csv}"
  fi

  # Save human-readable summary
  summary_file="${simulation_dir}/ipc_summary.txt"
  {
    echo "Benchmark: ${benchmark}"
    echo "Total SimPoints: ${num_simpoints}"
    echo "Total Weight Sum: ${total_weight}"
    echo "Estimated Overall IPC: ${overall_ipc}"
    if [ -n "${ref_time_sec}" ] && [ -n "${run_time_sec}" ]; then
      echo "Reference time (baseline, s): ${ref_time_sec}"
      echo "Run time (simulated @ ${FREQ_GHZ} GHz, s): ${run_time_sec}"
      echo "Ratio (reference_time / run_time): ${ratio}"
    fi
    echo "SPEC/GHz: ${spec_per_ghz}"
    echo ""
    echo "Detailed results (for verification): ${output_csv}"
    echo "Aggregate summary: ${summary_csv}"
    echo ""
    echo "SPEC/GHz from execution time (SPEC CPU 2006: reference = Sun UltraSparc II 296 MHz):"
    echo "  ref_IPC * ref_freq_GHz = REF_IPC_TIMES_FREQ_GHZ = ${REF_IPC_TIMES_FREQ_GHZ}"
    echo "  total_instructions    = ref_time * REF_IPC_TIMES_FREQ_GHZ * 1e9"
    echo "  run_time              = total_instructions / (IPC * freq_Hz) = ref_time * REF_IPC_TIMES_FREQ_GHZ / (IPC * freq_GHz)"
    echo "  ratio                 = reference_time / run_time = IPC * freq_GHz / REF_IPC_TIMES_FREQ_GHZ"
    echo "  SPEC/GHz              = ratio / freq_GHz = IPC / REF_IPC_TIMES_FREQ_GHZ"
    echo "For composite SPECint-style score over multiple benchmarks, use geometric mean of spec_per_ghz."
  } > "${summary_file}"

  echo "Summary saved to: ${summary_file}"
  echo "Detailed CSV (with summary row) saved to: ${output_csv}"
  echo "Aggregate summary CSV: ${summary_csv}"
else
  echo "Error: Total weight is zero or invalid." >&2
  exit 1
fi

echo ""
echo "=== Completed IPC estimation for ${benchmark} ==="
