#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 4 ]; then
  echo "Usage: $0 <benchmark> <SPEC_ROOT> <SPECINVOKE> <RESULT_DIR>" >&2
  exit 1
fi

benchmark="$1"
SPEC_ROOT="$2"
SPECINVOKE="$3"
RESULT_DIR="$4"

run_dir="${SPEC_ROOT}/benchspec/CPU2006/${benchmark}/run/run_base_ref_gcc.0000"
output_dir="${RESULT_DIR}/${benchmark}"

echo "=== Running ${benchmark} ==="
mkdir -p "${output_dir}"

subcmds="$(cd "${run_dir}" && "${SPECINVOKE}" -n 2>&1 | grep -v "^#" | grep -v "^timer" | grep -v "^$")"
num_subcmds="$(echo "${subcmds}" | wc -l)"
echo "=== Subcommands for ${benchmark} (${num_subcmds} commands)"

output_dir_abs="$(cd "${output_dir}" && pwd)"
export output_dir_abs

export BENCHMARK="${benchmark}" NUM_SUBCMDS="${num_subcmds}" RUN_DIR="${run_dir}"

echo "${subcmds}" | nl -nln | \
parallel --line-buffer --colsep '\t' -j "${num_subcmds}" '
cmd_clean=$(echo {2} | sed "s/ [0-9]*>>* *[^ ]*//g");
output_file="${output_dir_abs}/output_{1}.txt";
echo "[$BENCHMARK {1}/$NUM_SUBCMDS] Starting...";
(cd "$RUN_DIR" && eval "$cmd_clean" > "$output_file" 2>&1) && \
echo "[$BENCHMARK {1}/$NUM_SUBCMDS] Completed" || \
echo "[$BENCHMARK {1}/$NUM_SUBCMDS] Failed"
'

echo "=== Completed all ${benchmark} subcommands ==="


