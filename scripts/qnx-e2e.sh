#!/usr/bin/env bash
# End-to-end check on a real QNX 8.0 virtual machine.
#
#   source ~/qnx800/qnxsdp-env.sh          # QNX SDP 8.0 from QNX Everywhere
#   ./scripts/qnx-e2e.sh                    # ARCH=aarch64le for an AArch64 VM
#
# 1. checks the toolchain             (qpa doctor)
# 2. boots a QNX VM with mkqnximage   (qpa vm up)
# 3. builds libqlinux and runs its tests on QNX
# 4. ports the example project for QNX and runs its self-test on the VM
# 5. runs the benchmark against the VM (bench/results/qnx-<arch>.md)
# 6. stops the VM
#
# Set ANTHROPIC_API_KEY (or OPENAI_API_KEY) and QPA_MODEL to let the repair loop use a model.
# Set QPA_DEVICE=root@<ip> (and QPA_SSH_IDENTITY) to use a running VM or a Raspberry Pi instead.
set -euo pipefail
cd "$(dirname "$0")/.."
ARCH="${ARCH:-x86_64}"
OUT="${OUT:-qnx-e2e}"
: "${QNX_HOST:?source qnxsdp-env.sh from the QNX SDP 8.0 first}"

echo "== 1. toolchain"
qpa doctor

started_vm=0
if [ -z "${QPA_DEVICE:-}" ]; then
  echo "== 2. QNX VM ($ARCH)"
  eval "$(qpa vm up --arch "$ARCH")"
  started_vm=1
  trap 'qpa vm down --arch "$ARCH" || true' EXIT
fi
echo "   device: $QPA_DEVICE"
host="${QPA_DEVICE#*@}"; host="${host%%:*}"; user="${QPA_DEVICE%@*}"
ssh_opts=(-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR)
[ -n "${QPA_SSH_IDENTITY:-}" ] && ssh_opts+=(-i "$QPA_SSH_IDENTITY")

echo "== 3. libqlinux on QNX"
make -C libqlinux qnx-test ARCH="$ARCH"
scp "${ssh_opts[@]}" "libqlinux/build/qnx-$ARCH/test_qlinux" "$user@$host:/tmp/test_qlinux"
ssh "${ssh_opts[@]}" "$user@$host" /tmp/test_qlinux

echo "== 4. port the example"
mkdir -p "$OUT"
qpa port examples/linux-sysmon --target "qnx-$ARCH" --out "$OUT/linux-sysmon"

echo "== 5. benchmark"
python3 bench/run.py --target "qnx-$ARCH"

echo "== done: $OUT/linux-sysmon/report.html, bench/results/qnx-$ARCH.md"
[ "$started_vm" = 1 ] && echo "   (the VM is stopped on exit)"
