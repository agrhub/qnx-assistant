# libqlinux
#
#   make                 build libqlinux.a for the host (logic tests)
#   make test            build and run the tests on the host
#   make qnx ARCH=x86_64 build for QNX 8.0 with qcc (x86_64 for QEMU, aarch64le for Pi 5);
#                        needs the SDP environment (source qnxsdp-env.sh)
#   make qnx-test ARCH=x86_64
#                        build the test binary for QNX; copy build/qnx-<ARCH>/test_qlinux
#                        to the target (QEMU or Raspberry Pi 5) and run it there

ARCH   ?= x86_64
CFLAGS ?= -O2 -g
QL_FLAGS := -std=c11 -Wall -Wextra -D_POSIX_C_SOURCE=200809L -Iinclude/qlinux $(CFLAGS)
SRCS   := src/epoll.c src/eventfd.c src/compat.c

HOST_OUT := build/host
QNX_OUT  := build/qnx-$(ARCH)
QCC      := qcc -Vgcc_nto$(ARCH)
QAR      := nto$(patsubst %le,%,$(ARCH))-ar

.PHONY: all test qnx qnx-test clean
all: $(HOST_OUT)/libqlinux.a

$(HOST_OUT)/%.o: src/%.c $(wildcard include/qlinux/*.h include/qlinux/sys/*.h)
	@mkdir -p $(@D)
	$(CC) $(QL_FLAGS) -c $< -o $@

$(HOST_OUT)/libqlinux.a: $(SRCS:src/%.c=$(HOST_OUT)/%.o)
	$(AR) rcs $@ $^

$(HOST_OUT)/test_qlinux: tests/test_qlinux.c $(HOST_OUT)/libqlinux.a
	$(CC) $(QL_FLAGS) -D_DEFAULT_SOURCE $< -o $@ -L$(HOST_OUT) -lqlinux -lpthread

test: $(HOST_OUT)/test_qlinux
	./$(HOST_OUT)/test_qlinux

$(QNX_OUT)/%.o: src/%.c
	@mkdir -p $(@D)
	$(QCC) $(QL_FLAGS) -c $< -o $@

$(QNX_OUT)/libqlinux.a: $(SRCS:src/%.c=$(QNX_OUT)/%.o)
	$(QAR) rcs $@ $^

qnx: $(QNX_OUT)/libqlinux.a

qnx-test: tests/test_qlinux.c $(QNX_OUT)/libqlinux.a
	$(QCC) $(QL_FLAGS) $< -o $(QNX_OUT)/test_qlinux -L$(QNX_OUT) -lqlinux

clean:
	rm -rf build
