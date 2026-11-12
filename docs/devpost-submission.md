# Devpost submission: QNX Port Assistant

Copy-ready text for the QNX Global Hackathon submission form (deadline 15 Dec 2026, 2:00 pm EST).

**Project name:** QNX Port Assistant (qpa)

**Tagline:** Port Linux C/C++ projects to QNX 8.0: find every Linux-only spot, fix it, and let the QNX compiler and a QNX VM decide what stays.

**Category:** Developer Tooling & Host Tools

**Bonus prizes entered:** Best Codelab / Tutorial (codelab URL below)

**Links**
- Repository: https://github.com/agrhub/qnx-assistant (MIT)
- Demo video: `<YouTube URL>`
- Codelab: https://github.com/agrhub/qnx-assistant/blob/main/docs/codelab.md

**Built with:** Python, C, tree-sitter, QNX SDP 8.0 (qcc / ntox86_64-gcc / ntoaarch64-gcc, mkqnximage), QEMU, CMake, Autotools, GNU make, OpenSSH, Anthropic / OpenAI-compatible LLM APIs

---

## Inspiration

QNX 8.0 is now free for non-commercial use, and the first thing a new developer wants is the software they already rely on: an MQTT broker, a database, a network tool, their own Linux service. Porting each one by hand means hunting for `epoll`, `/proc`, `/sys`, `systemctl` and dozens of other Linux-only details, one compiler error at a time.

We hit this ourselves. We wanted to move our AI camera gateway, 67,000 lines of C written for an Amlogic board, onto QNX. Our first, naive scan treated the JSON key `"ip"` as the `ip` command. That told us a useful tool has to understand code, not search text.

## What it does

`qpa port <project>` takes a Linux C/C++ project and:

1. **Scans** it on the syntax tree and sorts every Linux-only spot by how hard it is to port (blocker, hard, medium, easy, review). Each spot gets the QNX replacement: `sched_setaffinity` → `ThreadCtl(_NTO_TCTL_RUNMASK)`, `mkfs.ext4` → `mkqnx6fs`, `/sys/class/net/*/address` → `getifaddrs(AF_LINK)`. It also finds the commands a program launches (`nmcli`, `systemctl`, `parted`), which no compiler will ever flag.
2. **Fixes** what is always the same with exact syntax-tree edits (statfs → statvfs, `CLOCK_BOOTTIME` → `CLOCK_MONOTONIC`, `prctl(PR_SET_NAME)` → `pthread_setname_np`). It leaves alone code already behind `#ifdef __linux__` or a configure check.
3. **Links libqlinux**, our shim that makes `epoll`, `eventfd`, `accept4`, `pipe2` and `dup3` work on QNX with no source change.
4. **Builds** with the QNX SDP 8.0 toolchain through generated compiler wrappers. These work with CMake, Autotools, plain make or custom commands, without editing the project's build files.
5. **Repairs** the remaining compiler errors with a language model in a loop. **The compiler is the referee:** an edit is kept only if the next QNX build gets further, otherwise it is reverted and the model is told why. Edits keep the Linux path behind `#ifdef __linux__`, so the result can go upstream.
6. **Tests** on QNX: `qpa vm up` boots a QNX 8.0 QEMU VM with `mkqnximage`; qpa copies the binaries over ssh and runs the project's own tests there (also on a Raspberry Pi 5).
7. **Reports**: an HTML report (build, tests, every change as a diff, every AI round kept or reverted, what is left), and one `qnx-port.patch` that applies to the original tree with `git apply`.

Without the SDP, the `emulate` target gives a fast first pass on a Linux host. It stubs out the Linux-only headers a project uses and refuses Linux-only functions at link time. It also undefines `__linux__`, so configure and CMake checks answer as they would on QNX.

## How we built it

- **Python CLI** (`qpa scan | port | vm | rules | doctor`). It uses tree-sitter for C/C++ and a YAML rule set of about 40 Linux → QNX rules, each with a QNX replacement, a fix type and a confidence.
- **libqlinux** (C). epoll is emulated on `poll()`: the epoll fd is a pipe, which also wakes a thread blocked in `epoll_wait()` when another thread changes the interest set. eventfd uses an anonymous read-write FIFO. Both have 77 checks, run under ASan, UBSan and TSan.
- **Compiler wrappers** add the shim and the target flags to any build system. Before building, qpa probes the QNX toolchain and maps shim calls only where QNX lacks them.
- **Repair loop** with providers for Anthropic, any OpenAI-compatible endpoint, and a replay provider for reproducible tests. It uses the standard library only. Every prompt and reply is saved for review.
- **Benchmark runner** that ports real projects at pinned commits and tabulates the results.

## QNX-specific technologies used

- QNX SDP 8.0 toolchains: `ntox86_64-gcc`, `ntoaarch64-gcc`, `qcc -Vgcc_nto…`; Autotools hosts `*-nto-qnx8.0.0`; a generated CMake toolchain with `CMAKE_SYSTEM_NAME QNX`.
- `mkqnximage --type=qemu` VMs for automated on-target testing.
- QNX APIs in the knowledge base and repairs: `ThreadCtl(_NTO_TCTL_RUNMASK)` for CPU affinity, `pthread_setname_np`, `statvfs`, `mkqnx6fs`, slay/SLM instead of systemd, io-sock/BSD routing sockets instead of netlink, io-audio instead of ALSA.
- libqlinux builds for QNX x86_64 (QEMU) and aarch64le (Raspberry Pi 5).

## Evidence of QNX use (for reviewers)

| Where | What |
| --- | --- |
| `qpa/target.py` | QNX targets `qnx-x86_64` / `qnx-aarch64le`: SDP compiler selection, toolchain probes, CMake QNX toolchain file, Autotools `--host=…-nto-qnx8.0.0` |
| `qpa/vm.py`, `qpa vm up` | QNX 8.0 QEMU VM via `mkqnximage --type=qemu --run=-h`, `--getip`, `--ssh-ident` |
| `qpa/runner.py` | copies binaries to the QNX target and runs tests over ssh |
| `libqlinux/Makefile` (`qnx`, `qnx-test`) | builds the shim and its tests with `qcc -Vgcc_nto$(ARCH)` |
| `qpa/rules/*.yaml` | the Linux → QNX 8.0 mapping |
| `scripts/qnx-e2e.sh` | one-command end-to-end run on a QNX VM |

## Results

On the emulate target, without a language model (`bench/results/emulate.md`):

- **Pass with no source changes:** inih, libyaml, iperf3 (a real loopback throughput run) and mosquitto (broker + publish/subscribe, its event loop running on libqlinux's epoll).
- **Need the repair loop:** the example service, which passes with it in 2 compiler-checked rounds, and redis (11 errors left).
- **Correctly reported as a redesign:** htop, whose Linux backend is all `/proc` and `/sys`.

On our own 67,000-line camera gateway, qpa scanned 38 files in under a second. It flagged the Amlogic NPU SDK as a blocker and GStreamer, NetworkManager and sysfs as rewrites, and listed every launched command (`nmcli`, `systemctl`, `parted`, `mkfs.ext4`) that would have failed only at run time.

## Challenges we ran into

- **Emulating QNX on Linux without lying.** Our first emulation pre-included headers and poisoned Linux names. That broke autoconf's `char socket();` checks, and then hiredis, whose `-Werror` build needs the XSI `strerror_r`, because pre-including fixes glibc's feature macros for the whole file. The final design pre-includes nothing. It refuses functions at link time and traces the errors back to source lines, and it skips the Linux headers that the host libc pulls in for itself.
- **Not counting what is already handled.** Real projects keep Linux code behind `HAVE_…` checks or `#ifdef TCP_USER_TIMEOUT`. Recognizing these guards cut iperf3's open findings from 32 to 7.
- **Force-including a shim** fixed libc feature macros too early, so `CPU_ZERO` went missing. libqlinux now has a header-free force-include mode.

## Accomplishments that we're proud of

- The compiler, not the model, decides what stays, and every AI edit is in the report as a diff, kept or reverted.
- A shim good enough to run a real MQTT broker's event loop unchanged.
- One patch that keeps the Linux build working and adds the QNX path: suitable for upstreaming.

## What we learned

The hard part of porting is knowing *where* to look and *what* to use instead, and verifying fast. A model is useful for the judgement calls, but only inside a loop where the toolchain checks every step.

## What's next

- Run the full benchmark on QNX 8.0 hardware and mark rules `verified_on: qnx-8.0`.
- QNX-native fixes: a pulse-based eventfd, `ionotify`-based epoll, and resource managers in place of sysfs.
- Upstream the generated patches, starting with the projects in the benchmark.
- A QNX platform backend for htop, written with qpa's report as the map.

## Build and run instructions

- **QNX version:** QNX SDP 8.0 (QNX Everywhere).
- **Targets:** QEMU x86_64 via `mkqnximage`; Raspberry Pi 5 (aarch64le).
- **Toolchain:** `ntox86_64-gcc` / `ntoaarch64-gcc` (or `qcc`) from the SDP. The host needs Python 3.10+, gcc, make, CMake, OpenSSH.

```sh
git clone https://github.com/agrhub/qnx-assistant && cd qnx-assistant
pip install -e .
qpa scan examples/linux-sysmon                       # report only
source ~/qnx800/qnxsdp-env.sh && qpa doctor          # QNX toolchain
eval "$(qpa vm up)"                                  # QNX 8.0 VM
qpa port examples/linux-sysmon -t qnx-x86_64         # port, build, test on the VM
./scripts/qnx-e2e.sh                                 # everything, including the benchmark
```
