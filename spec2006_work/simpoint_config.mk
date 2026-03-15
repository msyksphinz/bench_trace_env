# SimPoint parameters (single source of truth for Makefile and scripts).
# Scripts can read defaults via: make -s -C spec2006_work print-simpoint-config
SIMPOINT_INTERVAL ?= 20000000
SIMPOINT_K ?= 30
