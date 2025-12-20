#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 2 ]; then
  echo "Usage: SPEC_ROOT=... SPECINVOKE=... SIMPOINT_DIR=... SIFT_DIR=... SNIPER_ROOT=... PIN_HOME=... SNIPER_SIM_LD_PATH=... QEMU=... QEMU_FLAGS=... QEMU_CPU_OPTIONS=... $0 <benchmark>" >&2
  exit 1
fi

benchmark="$1"
SIMPOINT_INTERVAL="$2"
: "${SPEC_ROOT:?SPEC_ROOT is required}"
: "${SPECINVOKE:?SPECINVOKE is required}"
: "${SIMPOINT_DIR:?SIMPOINT_DIR is required}"
: "${SIFT_DIR:?SIFT_DIR is required}"
: "${SNIPER_ROOT:?SNIPER_ROOT is required}"
: "${PIN_HOME:?PIN_HOME is required}"
: "${SNIPER_SIM_LD_PATH:?SNIPER_SIM_LD_PATH is required}"
: "${QEMU:?QEMU is required}"
: "${QEMU_FLAGS:?QEMU_FLAGS is required}"
: "${QEMU_CPU_OPTIONS:?QEMU_CPU_OPTIONS is required}"
: "${SIMPOINT_INTERVAL:?SIMPOINT_INTERVAL is required}"
run_dir="${SPEC_ROOT}/benchspec/CPU2006/${benchmark}/run/run_base_ref_gcc.0000"
simpoint_output_dir="${SIMPOINT_DIR}/${benchmark}"
sift_output_dir="${SIFT_DIR}/${benchmark}"

echo "=== Generating SIFT traces for ${benchmark} ==="
mkdir -p "${sift_output_dir}"

if [ ! -d "${simpoint_output_dir}" ]; then
  echo "Error: SimPoint directory ${simpoint_output_dir} not found. Please run 'make run_simpoint_${benchmark}' first."
  exit 1
fi

subcmds="$(cd "${run_dir}" && "${SPECINVOKE}" -n 2>&1 | grep -v "^#" | grep -v "^timer" | grep -v "^$")"
num_subcmds="$(echo "${subcmds}" | wc -l)"
echo "=== Processing ${benchmark} subcommands for SIFT generation (${num_subcmds} commands)"

sift_dir_abs="$(cd "${sift_output_dir}" && pwd)"
simpoint_dir_abs="$(cd "${simpoint_output_dir}" && pwd)"
export sift_dir_abs simpoint_dir_abs

export BENCHMARK="${benchmark}" NUM_SUBCMDS="${num_subcmds}" RUN_DIR="${run_dir}"
export SNIPER_ROOT PIN_HOME SNIPER_SIM_LD_PATH QEMU QEMU_FLAGS QEMU_CPU_OPTIONS QEMU_FRONTEND_PLUGIN
export SIMPOINT_INTERVAL

# Get the number of parallel jobs from environment variable (default: number of CPUs)
# Limit to 8 to avoid file handle limits
PARALLEL_JOBS="${PARALLEL_JOBS:-$(nproc)}"
if [ "$PARALLEL_JOBS" -gt 8 ]; then
  PARALLEL_JOBS=8
fi

# List of all script files
all_script_list_file="${sift_dir_abs}/.all_script_list.txt"
rm -f "$all_script_list_file"

# Generate script files sequentially
echo "${subcmds}" | nl -nln -w1 -s$'\t'| while IFS=$'\t' read -r cmd_num cmd_raw; do
  # Escape special characters to safely execute sed command
  cmd_clean=$(printf "%s\n" "$cmd_raw" | sed "s| [0-9]*>>* *[^ ]*||g")
   
  simpoint_file="${simpoint_dir_abs}/bbv_${cmd_num}.out.*.simpoints"
  weights_file="${simpoint_dir_abs}/bbv_${cmd_num}.out.*.weights"
  simpoint_files=$(ls $simpoint_file 2>/dev/null | head -1)
  weights_files=$(ls $weights_file 2>/dev/null | head -1)
  
  
  if [ -z "$simpoint_files" ] || [ -z "$weights_files" ]; then
    echo "[${BENCHMARK} SIFT ${cmd_num}/${NUM_SUBCMDS}] No SimPoint files found, skipping"
    continue
  fi
  
  echo "[${BENCHMARK} SIFT ${cmd_num}/${NUM_SUBCMDS}] Found SimPoint files"
  sift_subcmd_dir="${sift_dir_abs}/subcmd_${cmd_num}"
  mkdir -p "$sift_subcmd_dir"

  # Create parent directory structure so relative path ../run_base_ref_gcc.0000 can be referenced
  # Creating one at subcmd level makes it accessible from all SimPoints
  run_base_dir="${sift_subcmd_dir}/run_base_ref_gcc.0000"
  if [ ! -d "$run_base_dir" ]; then
    cp -r "$RUN_DIR" "$run_base_dir" 2>/dev/null || true
  fi

  # Generate script file for each SimPoint
  paste -d " " "$simpoint_files" "$weights_files" | while IFS=" " read -r simpoint dummy1 weight dummy2; do
    output_base="${sift_subcmd_dir}/simpoint_${simpoint}"
    response_file="${output_base}_response.app0.th0.sift"
    mkdir -p "$(dirname "$response_file")"
    touch "$response_file"
    
    cmd_suffix=$(echo "$cmd_clean" | sed "s|^[^ ]* ||")
    cmd_suffix_noL=$(echo "$cmd_suffix" | sed "s|^-L [^ ]* ||")
    cmd_suffix_noL=$(echo "$cmd_suffix_noL" | sed "s|^ *||")
    
    sniper_vm_ld_path="$SNIPER_SIM_LD_PATH"
    original_ld_path="$LD_LIBRARY_PATH"
    sniper_script_ld_path="$original_ld_path"
    
    # SimPoint line only contains SimPointIndex, so
    # BBV interval length (number of instructions) is obtained from .simpoints filename.
    # Example: bbv_1.out.100000000.simpoints -> interval = 100000000
    base_name="$(basename "$simpoint_files" .simpoints)"
    interval="$SIMPOINT_INTERVAL"
    # fast_forward_target = SimPointIndex * interval
    fast_forward_target=$((simpoint * interval))
    detailed_target="${interval}"

    # Create individual execution directory for each SimPoint
    simpoint_run_dir="${sift_subcmd_dir}/run_dir_simpoint_${simpoint}"
    mkdir -p "$simpoint_run_dir"
    
    # Generate script file for each SimPoint
    script_file="${sift_subcmd_dir}/run_sift_simpoint_${simpoint}.sh"
    cat > "$script_file" << EOF
#!/usr/bin/env bash
set -euo pipefail

echo "[${BENCHMARK} SIFT ${cmd_num}/${NUM_SUBCMDS}] Generating SIFT for SimPoint ${simpoint} (weight: ${weight})";

# Copy RUN_DIR contents to individual execution directory (first time only)
# run_base_ref_gcc.0000 is already created at subcmd level, so only copy execution directory contents
if [ ! -f "${simpoint_run_dir}/.copied" ]; then
  if [ -d "${RUN_DIR}" ]; then
    # Copy RUN_DIR contents (handle empty case as well)
    if [ "\$(ls -A "${RUN_DIR}" 2>/dev/null)" ]; then
      cp -r "${RUN_DIR}"/* "${simpoint_run_dir}/" 2>&1 || {
        echo "[${BENCHMARK} SIFT ${cmd_num}/${NUM_SUBCMDS}] Warning: Failed to copy some files from ${RUN_DIR} to ${simpoint_run_dir}" >&2;
      };
    fi;
    touch "${simpoint_run_dir}/.copied";
  else
    echo "[${BENCHMARK} SIFT ${cmd_num}/${NUM_SUBCMDS}] Error: RUN_DIR ${RUN_DIR} does not exist" >&2;
    exit 1;
  fi;
fi;

cd "${simpoint_run_dir}" && \\
SNIPER_ROOT="${SNIPER_ROOT}" \\
GRAPHITE_ROOT="${SNIPER_ROOT}" \\
PIN_HOME="${PIN_HOME}" \\
PIN_LD_RESTORE_REQUIRED=1 \\
PIN_VM_LD_LIBRARY_PATH="${sniper_vm_ld_path}" \\
PIN_APP_LD_LIBRARY_PATH="${original_ld_path}" \\
SNIPER_SCRIPT_LD_LIBRARY_PATH="${sniper_script_ld_path}" \\
LD_LIBRARY_PATH="${sniper_vm_ld_path}" \\
LD_PRELOAD= \\
QEMU_CPU="${QEMU_CPU_OPTIONS}" \\
"${QEMU}" ${QEMU_FLAGS} -plugin "${QEMU_FRONTEND_PLUGIN}",verbose=on,response_files=on,fast_forward_target=${fast_forward_target},detailed_target=${detailed_target},output_file="${output_base}" ${cmd_suffix_noL} \\
> "${output_base}.log" 2>&1 && \\
echo "[${BENCHMARK} SIFT ${cmd_num}/${NUM_SUBCMDS}] Completed SimPoint ${simpoint}" || \\
echo "[${BENCHMARK} SIFT ${cmd_num}/${NUM_SUBCMDS}] Failed SimPoint ${simpoint}"
EOF
    chmod +x "$script_file"
    echo "$script_file" >> "$all_script_list_file"
  done
  
  echo "[${BENCHMARK} SIFT ${cmd_num}/${NUM_SUBCMDS}] All SimPoints processed"
done

echo $all_script_list_file

# Execute all generated script files in parallel
if [ -f "$all_script_list_file" ] && [ -s "$all_script_list_file" ]; then
  num_scripts=$(wc -l < "$all_script_list_file")
  echo "=== Executing $num_scripts scripts in parallel ==="
  cat "$all_script_list_file" | \
  SHELL=/bin/bash parallel --line-buffer -j ${PARALLEL_JOBS} bash '{}' 2>&1 || {
    echo "Warning: Some scripts failed. Check logs in ${sift_dir_abs}" >&2;
  };
  rm -f "$all_script_list_file"
fi

echo "=== Completed SIFT generation for ${benchmark} ==="


