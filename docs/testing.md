# Testing

What has been run, on what, and what is still to run on a real QNX 8.0 target.

## Automated (CI and `python -m pytest tests`)

| Suite | What it checks |
| --- | --- |
| `tests/test_scanner.py` | comments and strings ignored; JSON keys not taken for commands; argv arrays vs option tables; wrappers behind `timeout`; concatenated path literals; `#ifdef __linux__` guards |
| `tests/test_fix.py` | rule fixes (statfs, clocks, prctl) and that guarded code and preprocessor conditions are left alone; reply parsing |
| `tests/test_build.py` | GCC/ld error parsing; a stub `#error` reported at the project's `#include`; a refused function traced back to its call line |
| `tests/test_target.py` | QNX target selection, probes, wrappers and the CMake toolchain file (with a stand-in `ntox86_64-*` toolchain); emulate stubs and link refusals |
| `tests/test_port.py` | `qpa port` end to end on the example: rule fixes → 2 repair rounds → build → self-test pass; the patch applies to the untouched original with `git apply`, and the patched code still builds and passes on Linux; bad edits are reverted; the original project is never modified; optional ssh runner test (`QPA_TEST_DEVICE`) |
| `make -C libqlinux test` | 77 checks of the epoll, eventfd and fd-flag emulation, under ASan, UBSan and TSan in CI |

The ssh test runner was also run against a local OpenSSH server. It copied the ported binary, ran its self-test remotely and reported a clean failure for an unreachable device.

## Benchmark on the `emulate` target, AI off

`python bench/run.py --no-ai`, on 2026-11-12 (`bench/results/emulate.md`):

| Project | Lines | Build | Tests on target | Notes |
| --- | ---: | --- | --- | --- |
| inih | 1,343 | pass | pass (unit tests vs. baselines) | plain C |
| libyaml | 17,197 | pass | pass (version, reader, nesting) | CMake |
| iperf3 | 21,274 | pass | pass (1 s loopback throughput run) | configure turns off Linux-only features once `__linux__` and the Linux functions are gone |
| mosquitto | 116,374 | pass | pass (broker + publish/subscribe) | event loop runs on libqlinux epoll (`qlinux_epoll_*` in the binary) |
| linux-sysmon | 146 | 2 errors left | – | needs the repair loop: passes with it (see `tests/test_port.py`, codelab) |
| redis | 430,849 | 11 errors left | – | `debug.c` uses `Dl_info`, which redis only enables on Linux; needs repair rounds |
| htop | 48,950 | 7 errors left | – | its Linux platform backend is all `/proc`, `/sys` and `linux/capability.h`; needs a QNX backend (a redesign, reported as such) |

These numbers are without a language model. A run with `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` set (and `QPA_MODEL`) uses the repair loop on the remaining errors.

## The QNX target path

The `qnx-x86_64` path was exercised with a stand-in toolchain (`ntox86_64-gcc` → host gcc) and an ssh device. That run checked compiler selection, probing, wrappers, the CMake toolchain file, copying files to the device and running tests there: inih, libyaml and iperf3 passed remotely. It showed that a sysroot must not be forced in the toolchain file, and that dependencies must exist for QNX. mosquitto stops at `find_package(cJSON)`, as it would on a QNX sysroot without a cJSON port.

## To run on real QNX 8.0 (needs the SDP licence)

```sh
source ~/qnx800/qnxsdp-env.sh
./scripts/qnx-e2e.sh                 # ARCH=aarch64le for AArch64
```

The script boots a QEMU VM with `mkqnximage` and runs the libqlinux tests on QNX. It then ports and tests the example on the VM, and runs the benchmark with `--target qnx-x86_64`. Results go to `bench/results/qnx-x86_64.md`. For a Raspberry Pi 5, set `QPA_DEVICE=root@<pi-ip>` and `ARCH=aarch64le`.

## Known limits

- `emulate` is a fast first check, not QNX. Its view of what is missing is the rule set's view; real QNX headers can differ, so final results come from the QNX toolchain.
- Rules marked `confidence: unverified` (e.g. whether QNX 8.0 has `accept4`, `inotify`) need confirming with a real build. qpa probes the target for `accept4`/`pipe2`/`dup3` instead of assuming.
- Runtime paths (`/proc`, `/sys`) and launched commands are reported, not fixed: no compiler can see them.
- `mkqnximage --ssh-ident` is given the generated public key; if your SDP version expects a different form, start the VM with `mkqnximage` yourself and set `QPA_DEVICE`.
