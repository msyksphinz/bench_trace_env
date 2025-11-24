#!/bin/bash

CPU2017_DIR=`realpath ./spec2017_installed`

TARGET_LIB=glibc
LINK_TYPE=dynamic
# BENCHMARK=600.perlbench_s
BENCHMARK=$1

CONFIG=_opt_flags_${TARGET_LIB}_${BENCHMARK}
CONFIG_FILE=${CPU2017_DIR}/config/${CONFIG}.cfg

cp `realpath riscv64_config.cfg` ${CONFIG_FILE}

if [ "${LINK_TYPE}" == "static" ]; then
    sed -i '/^[[:space:]]*OPTIMIZE[[:space:]]*/s/$/ -static/' ${CONFIG_FILE}
fi

if [ "${TARGET_LIB}" != "glibc" ]; then
    # Link against target_lib
    sed -i "/EXTRA_OPTIMIZE/aLIBS                = -lrvv-libc -l${TARGET_LIB}" ${CONFIG_FILE}
fi

cd ${CPU2017_DIR} && . ${CPU2017_DIR}/shrc
printenv SPEC
ulimit -s unlimited
${CPU2017_DIR}/bin/runcpu -a setup -c ${CONFIG} -I ${BENCHMARK}
