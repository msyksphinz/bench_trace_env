# SPEC CPU2017 Benchmark Makefile
# This Makefile allows parallel execution of benchmarks using QEMU
# without relying on SPEC's runspec command.

# Configuration
SPEC_ROOT := $(CURDIR)/spec2017_installed
QEMU := /home/kimura/work/bench_trace_env/qemu-10.0.6/build/qemu-riscv64
QEMU_BUILD_DIR := /home/kimura/work/bench_trace_env/qemu-10.0.6/build
RISCV_SYSROOT := /riscv-linux/sysroot # inside docker container
QEMU_FLAGS := -L $(RISCV_SYSROOT)
BBV_PLUGIN := $(QEMU_BUILD_DIR)/contrib/plugins/libbbv.so
SPECINVOKE := $(SPEC_ROOT)/bin/specinvoke
RESULT_DIR := results
BBV_DIR := bbv_results
SIMPOINT_DIR := simpoint_results
SIFT_DIR := sift_results
SIMPOINT := $(abspath ../SimPoint/bin/simpoint)
SIMPOINT_K := 30

# Sniper configuration for SIFT generation
SNIPER_ROOT := $(abspath /home/kimura/work/sniper/prave_iccd2025/sniper)
QEMU_FRONTEND_PLUGIN := $(SNIPER_ROOT)/frontend/qemu-frontend/libqemu-frontend.so
LD_LIB := LD_LIBRARY_PATH="$(LD_LIBRARY_PATH):$(SNIPER_ROOT)/lib:$(SNIPER_ROOT)/pin_kit/extras/xed-intel64/lib:$(SNIPER_ROOT)/pin_kit/intel64/runtime/pincrt:$(SNIPER_ROOT)/python_kit/intel64/lib/"
QEMU_CPU_OPTIONS := rv64,zba=true,zbb=true,v=true,vlen=1024,vext_spec=v1.0,rvv_ta_all_1s=true,rvv_ma_all_1s=true

# Benchmark list - SPECint2017
bench_lists += 600.perlbench_s
bench_lists += 602.gcc_s
bench_lists += 605.mcf_s
bench_lists += 620.omnetpp_s
bench_lists += 623.xalancbmk_s
bench_lists += 625.x264_s
bench_lists += 631.deepsjeng_s
bench_lists += 641.leela_s
bench_lists += 648.exchange2_s
bench_lists += 657.xz_s

# Generate run targets
ALL_BENCH_TARGETS := $(addprefix all_,$(bench_lists))
RUN_BENCH_TARGETS := $(addprefix run_,$(bench_lists))
RUN_BBV_TARGETS := $(addprefix run_bbv_,$(bench_lists))
RUN_SIMPOINT_TARGETS := $(addprefix run_simpoint_,$(bench_lists))
RUN_SIFT_TARGETS := $(addprefix run_sift_,$(bench_lists))
BUILD_BENCH_TARGETS := $(addprefix build_,$(bench_lists))

# Default target
.DEFAULT_GOAL := help

help:
	@echo "SPEC CPU2017 Benchmark Makefile"
	@echo ""
	@echo "Targets:"
	@echo "  prepare        - Install SPEC CPU2017"
	@echo "  build          - build SPEC CPU2017 and build benchmarks"
	@echo "  run            - Run all benchmarks (sequential)"
	@echo "  run_bbv        - Run all benchmarks with BBV collection (sequential)"
	@echo "  run_simpoint   - Run SimPoint analysis on all BBV results"
	@echo "  run_sift       - Generate SIFT traces based on SimPoint results"
	@echo "  report         - Show summary of benchmark results"
	@echo "  clean          - Clean build and result directories"
	@echo "  clean-results  - Clean only result directories"
	@echo "  clean-bbv      - Clean only BBV results"
	@echo "  clean-simpoint - Clean only SimPoint results"
	@echo "  clean-sift     - Clean only SIFT results"
	@echo ""
	@echo "Individual benchmark targets:"
	@echo "  run_<benchmark>         - Run a specific benchmark with all inputs"
	@echo "  run_bbv_<benchmark>     - Run a specific benchmark with BBV collection"
	@echo "  run_simpoint_<benchmark>- Run SimPoint analysis for a specific benchmark"
	@echo "  run_sift_<benchmark>    - Generate SIFT traces for a specific benchmark"
	@echo ""
	@echo "Output directories:"
	@echo "  results/<benchmark>/        - Output files for each subcommand"
	@echo "  bbv_results/<benchmark>/    - BBV output files"
	@echo "  simpoint_results/<benchmark>/ - SimPoint output files (simpoints, weights)"
	@echo "  sift_results/<benchmark>/   - SIFT trace files"
	@echo ""
	@echo "Available benchmarks:"
	@for bench in $(bench_lists); do echo "  - $$bench"; done
	@echo ""
	@echo "Examples:"
	@echo "  make run_605.mcf_s                       # Run 605.mcf_s"
	@echo "  make run_bbv_605.mcf_s                   # Run 605.mcf_s with BBV"
	@echo "  make run_simpoint_605.mcf_s              # Run SimPoint on 605.mcf_s BBV results"
	@echo "  make run_sift_605.mcf_s                  # Generate SIFT traces for 605.mcf_s"
	@echo "  make -j4 run_605.mcf_s run_602.gcc_s     # Run 2 benchmarks in parallel"
	@echo "  make -j4 run_bbv_605.mcf_s run_bbv_602.gcc_s   # Run 2 with BBV in parallel"
	@echo "  make -j4 run_simpoint_605.mcf_s run_simpoint_602.gcc_s  # Run SimPoint in parallel"

# Prepare SPEC2017 installation
prepare: .prepare_spec2017
.prepare_spec2017:
	cd ../spec2017_cdrom && ./install.sh -f -d $(PWD)/spec2017_installed
	touch $@

$(ALL_BENCH_TARGETS): benchmark=$(subst all_,,$@)
$(ALL_BENCH_TARGETS):
	$(MAKE) build_$(benchmark)
	$(MAKE) run_$(benchmark)

# Build all benchmarks
build: prepare .build_benchmarks
.build_benchmarks:
	@echo "Building all benchmarks..."
	$(MAKE) $(addprefix build_,$(bench_lists))

$(BUILD_BENCH_TARGETS): benchmark=$(subst build_,,$@)
$(BUILD_BENCH_TARGETS):
	@echo "Building $(benchmark)..."
	./build.sh $(benchmark) || exit 1

# Run all benchmarks
run: $(RUN_BENCH_TARGETS)

$(RUN_BENCH_TARGETS): benchmark=$(subst run_,,$@)
$(RUN_BENCH_TARGETS): run_dir=$(SPEC_ROOT)/benchspec/CPU/$(benchmark)/run/run_base_refspeed_none.0000
$(RUN_BENCH_TARGETS): output_dir=$(RESULT_DIR)/$(benchmark)
$(RUN_BENCH_TARGETS):
	@echo "=== Running $(benchmark) ==="
	@mkdir -p $(output_dir)
	@subcmds=$$(cd $(run_dir) && $(SPECINVOKE) -n 2>&1 | grep -v "^#" | grep -v "^timer" | grep -v "^$$"); \
	num_subcmds=$$(echo "$$subcmds" | wc -l); \
	echo "=== Subcommands for $(benchmark) ($$num_subcmds commands)"; \
	output_dir_abs=$$(cd $(output_dir) && pwd); \
	export output_dir_abs; \
	echo "$$subcmds" | nl -nln | \
	parallel --line-buffer --colsep '\t' -j $$num_subcmds \
	'cmd_clean=$$(echo {2} | sed "s/ [0-9]*>>* *[^ ]*//g"); \
	output_file="$$output_dir_abs/output_{1}.txt"; \
	echo "[$(benchmark) {1}/$$num_subcmds] Starting..."; \
	(cd $(run_dir) && eval $$cmd_clean > $$output_file 2>&1) && \
	echo "[$(benchmark) {1}/$$num_subcmds] Completed" || \
	echo "[$(benchmark) {1}/$$num_subcmds] Failed"'; \
	echo "=== Completed all $(benchmark) subcommands ==="

# Run all benchmarks with BBV collection
run_bbv: $(RUN_BBV_TARGETS)

$(RUN_BBV_TARGETS): benchmark=$(subst run_bbv_,,$@)
$(RUN_BBV_TARGETS): run_dir=$(SPEC_ROOT)/benchspec/CPU/$(benchmark)/run/run_base_refspeed_none.0000
$(RUN_BBV_TARGETS): bbv_output_dir=$(BBV_DIR)/$(benchmark)
$(RUN_BBV_TARGETS): output_dir=$(RESULT_DIR)/$(benchmark)_bbv
$(RUN_BBV_TARGETS):
	@echo "=== Preparing BBV output directory for $(benchmark) ==="
	@mkdir -p $(bbv_output_dir)
	@mkdir -p $(output_dir)
	@subcmds=$$(cd $(run_dir) && $(SPECINVOKE) -n 2>&1 | grep -v "^#" | grep -v "^timer" | grep -v "^$$"); \
	num_subcmds=$$(echo "$$subcmds" | wc -l); \
	echo "=== Subcommands for $(benchmark) with BBV ($$num_subcmds commands)"; \
	bbv_dir_abs=$$(cd $(bbv_output_dir) && pwd); \
	output_dir_abs=$$(cd $(output_dir) && pwd); \
	export bbv_dir_abs output_dir_abs; \
	echo "$$subcmds" | nl -nln | \
	parallel --line-buffer --colsep '\t' -j $$num_subcmds \
	'cmd_clean=$$(echo {2} | sed "s/ [0-9]*>>* *[^ ]*//g"); \
	bbv_file="$$bbv_dir_abs/bbv_{1}.out"; \
	output_file="$$output_dir_abs/output_{1}.txt"; \
	cmd_with_bbv=$$(echo $$cmd_clean | sed "s|$(QEMU)|$(QEMU) -plugin $(BBV_PLUGIN),outfile=$$bbv_file|"); \
	echo "[$(benchmark) BBV {1}/$$num_subcmds] Starting..."; \
	(cd $(run_dir) && eval $$cmd_with_bbv > $$output_file 2>&1) && \
	echo "[$(benchmark) BBV {1}/$$num_subcmds] Completed - BBV saved to $$bbv_file" || \
	echo "[$(benchmark) BBV {1}/$$num_subcmds] Failed"'; \
	echo "=== Completed all $(benchmark) BBV collection ==="

# Run SimPoint analysis on all benchmarks
run_simpoint: $(RUN_SIMPOINT_TARGETS)

$(RUN_SIMPOINT_TARGETS): benchmark=$(subst run_simpoint_,,$@)
$(RUN_SIMPOINT_TARGETS): bbv_output_dir=$(BBV_DIR)/$(benchmark)
$(RUN_SIMPOINT_TARGETS): simpoint_output_dir=$(SIMPOINT_DIR)/$(benchmark)
$(RUN_SIMPOINT_TARGETS):
	@echo "=== Running SimPoint analysis for $(benchmark) ==="
	@mkdir -p $(simpoint_output_dir)
	@if [ ! -d "$(bbv_output_dir)" ]; then \
		echo "Error: BBV directory $(bbv_output_dir) not found. Please run 'make run_bbv_$(benchmark)' first."; \
		exit 1; \
	fi; \
	bbv_files=$$(ls $(bbv_output_dir)/bbv_*.out.*.bb 2>/dev/null); \
	if [ -z "$$bbv_files" ]; then \
		echo "Error: No BBV files found in $(bbv_output_dir). Please run 'make run_bbv_$(benchmark)' first."; \
		exit 1; \
	fi; \
	echo "$$bbv_files" | \
	parallel --line-buffer -j $$(nproc) \
	'bbv_file={}; \
	base_name=$$(basename $$bbv_file .bb); \
	simpoint_out="$(simpoint_output_dir)/$${base_name}.simpoints"; \
	weights_out="$(simpoint_output_dir)/$${base_name}.weights"; \
	echo "[$(benchmark)] Processing $$bbv_file..."; \
	$(SIMPOINT) -loadFVFile $$bbv_file -saveSimpoints $$simpoint_out -saveSimpointWeights $$weights_out -maxK $(SIMPOINT_K) > /dev/null 2>&1; \
	if [ -f "$$simpoint_out" ]; then \
		echo "[$(benchmark)] SimPoint completed: $$simpoint_out (weights: $$weights_out)"; \
	else \
		echo "[$(benchmark)] SimPoint failed for $$bbv_file"; \
	fi'; \
	echo "=== Completed SimPoint analysis for $(benchmark) ==="

# Generate SIFT traces based on SimPoint results
run_sift: $(RUN_SIFT_TARGETS)

$(RUN_SIFT_TARGETS): benchmark=$(subst run_sift_,,$@)
$(RUN_SIFT_TARGETS): run_dir=$(SPEC_ROOT)/benchspec/CPU/$(benchmark)/run/run_base_refspeed_none.0000
$(RUN_SIFT_TARGETS): simpoint_output_dir=$(SIMPOINT_DIR)/$(benchmark)
$(RUN_SIFT_TARGETS): sift_output_dir=$(SIFT_DIR)/$(benchmark)
$(RUN_SIFT_TARGETS):
	@echo "=== Generating SIFT traces for $(benchmark) ==="
	@mkdir -p $(sift_output_dir)
	@if [ ! -d "$(simpoint_output_dir)" ]; then \
		echo "Error: SimPoint directory $(simpoint_output_dir) not found. Please run 'make run_simpoint_$(benchmark)' first."; \
		exit 1; \
	fi; \
	subcmds=$$(cd $(run_dir) && $(SPECINVOKE) -n 2>&1 | grep -v "^#" | grep -v "^timer" | grep -v "^$$"); \
	num_subcmds=$$(echo "$$subcmds" | wc -l); \
	echo "=== Processing $(benchmark) subcommands for SIFT generation ($$num_subcmds commands)"; \
	sift_dir_abs=$$(cd $(sift_output_dir) && pwd); \
	simpoint_dir_abs=$$(cd $(simpoint_output_dir) && pwd); \
	export sift_dir_abs simpoint_dir_abs; \
	echo "$$subcmds" | nl -nln | \
	SHELL=/bin/bash parallel --line-buffer --colsep '\t' -j 1 \
	'cmd_num={1}; \
	cmd_clean=$$(echo {2} | sed "s/ [0-9]*>>* *[^ ]*//g"); \
	simpoint_file="$$simpoint_dir_abs/bbv_$$cmd_num.out.*.simpoints"; \
	weights_file="$$simpoint_dir_abs/bbv_$$cmd_num.out.*.weights"; \
	simpoint_files=$$(ls $$simpoint_file 2>/dev/null | head -1); \
	weights_files=$$(ls $$weights_file 2>/dev/null | head -1); \
	if [ -z "$$simpoint_files" ] || [ -z "$$weights_files" ]; then \
		echo "[$(benchmark) SIFT $$cmd_num/$$num_subcmds] No SimPoint files found, skipping"; \
		exit 0; \
	fi; \
	echo "[$(benchmark) SIFT $$cmd_num/$$num_subcmds] Found SimPoint files"; \
	sift_subcmd_dir="$$sift_dir_abs/subcmd_$$cmd_num"; \
	mkdir -p "$$sift_subcmd_dir"; \
	paste "$$simpoint_files" "$$weights_files" | while IFS=" " read -r simpoint weight; do \
		output_base="$$sift_subcmd_dir/simpoint_$${simpoint}"; \
		response_file="$$output_base.response.sift"; \
		mkdir -p "$$(dirname "$$response_file")"; \
		touch "$$response_file"; \
		cmd_with_sift=$$(echo "$$cmd_clean" | sed "s|$(QEMU) $(QEMU_FLAGS)|QEMU_CPU=$(QEMU_CPU_OPTIONS) $(LD_LIB) $(QEMU) $(QEMU_FLAGS) -plugin $(QEMU_FRONTEND_PLUGIN),verbose=on,response_files=on,use_roi=on,output_file=$$output_base|"); \
		echo "[$(benchmark) SIFT $$cmd_num/$$num_subcmds] Generating SIFT for SimPoint $$simpoint (weight: $$weight)"; \
		(cd $(run_dir) && eval $$cmd_with_sift > "$$output_base.log" 2>&1) && \
		echo "[$(benchmark) SIFT $$cmd_num/$$num_subcmds] Completed SimPoint $$simpoint" || \
		echo "[$(benchmark) SIFT $$cmd_num/$$num_subcmds] Failed SimPoint $$simpoint"; \
	done; \
	echo "[$(benchmark) SIFT $$cmd_num/$$num_subcmds] All SimPoints processed"'; \
	echo "=== Completed SIFT generation for $(benchmark) ==="

# Clean targets
clean: clean-results
	rm -rf .prepare_spec2017 .build_benchmarks
	rm -rf $(SPEC_ROOT)

clean-results:
	rm -rf $(RESULT_DIR)

clean-bbv:
	rm -rf $(BBV_DIR)

clean-simpoint:
	rm -rf $(SIMPOINT_DIR)

clean-sift:
	rm -rf $(SIFT_DIR)

.PHONY: help prepare build run run_bbv run_simpoint run_sift clean clean-results clean-bbv clean-simpoint clean-sift $(RUN_BENCH_TARGETS) $(RUN_BBV_TARGETS) $(RUN_SIMPOINT_TARGETS) $(RUN_SIFT_TARGETS)
