build:
	docker build -t spec2017-runner .
	$(MAKE) build-qemu

run:
	docker run --rm -it -v "${HOME}:${HOME}" --user $(shell id -u):$(shell id -g) -w "${PWD}" spec2017-runner

# QEMU_VERSION=10.1.0
# QEMU_VERSION=9.2.4
QEMU_VERSION=9.0.0
build-qemu: .build_qemu-$(QEMU_VERSION)
.build_qemu-$(QEMU_VERSION):
	wget https://download.qemu.org/qemu-$(QEMU_VERSION).tar.xz
	tar xJf qemu-$(QEMU_VERSION).tar.xz
	cd qemu-$(QEMU_VERSION) && \
		mkdir -p build && cd build && \
	    ../configure --target-list=riscv64-softmmu,riscv64-linux-user && \
		make -j32
	touch $@
