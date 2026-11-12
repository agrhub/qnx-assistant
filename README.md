# QNX Port Assistant (`qpa`)

Port Linux C/C++ projects to **QNX 8.0**. qpa finds every Linux-only spot and fixes what it can. The QNX compiler and a QNX VM decide what stays.

```
$ qpa port examples/linux-sysmon
linux-sysmon -> emulate
  fixes      1 rule, 2 AI (2 AI round(s))
  build      OK (make, 3 attempt(s))
  tests      PASS on host (emulate)
  report     qpa-port/report.html
  patch      qpa-port/qnx-port.patch
```

## What it does

1. **Scan.** It parses C/C++ on the syntax tree and sorts every Linux-only spot by how hard it is to port. Each spot gets its QNX replacement, including commands the program launches (`nmcli`, `systemctl`, `parted`), which no compiler flags.
2. **Rule fixes.** Changes that are always the same are made as exact edits (`statfs` → `statvfs`, `CLOCK_BOOTTIME` → `CLOCK_MONOTONIC`, `prctl(PR_SET_NAME)` → `pthread_setname_np`). Code already behind `#ifdef __linux__` or a configure check is left alone.
3. **libqlinux.** `epoll`, `eventfd`, `accept4`, `pipe2` and `dup3` work on QNX unchanged.
4. **Build** with the QNX SDP 8.0 toolchain through generated compiler wrappers: CMake, Autotools, make or custom commands, with no edits to the project's build files.
5. **AI repair.** A language model proposes edits for the remaining errors, and the compiler is the referee. An edit is kept only if the next build gets further; otherwise it is reverted and the model is told why.
6. **Test** on QNX. `qpa vm up` boots a QNX 8.0 QEMU VM with `mkqnximage`; qpa copies the binaries over ssh and runs the project's own tests there. A Raspberry Pi 5 works the same way.
7. **Report.** An HTML report shows the build, the tests, every change as a diff, every AI round kept or reverted, and what is left. A single `qnx-port.patch` applies to the original tree with `git apply`.

The original project is never modified. How it works: [docs/architecture.md](docs/architecture.md).

## Install

```sh
git clone https://github.com/agrhub/qnx-assistant && cd qnx-assistant
pip install -e .            # Python 3.10+, plus gcc/make (and CMake/Autotools for such projects)
```

## Use

```sh
qpa scan path/to/project                      # report only: qpa-report/report.html
qpa port path/to/project                      # emulate target: no SDP needed, fast first pass
source ~/qnx800/qnxsdp-env.sh && qpa doctor   # QNX SDP 8.0 toolchain
eval "$(qpa vm up)"                           # boot a QNX 8.0 VM, sets QPA_DEVICE
qpa port path/to/project -t qnx-x86_64        # build for QNX, test on the VM
qpa port path/to/project -t qnx-aarch64le -d root@<pi5-ip>   # Raspberry Pi 5
qpa vm down
```

| Option | |
| --- | --- |
| `-t, --target` | `emulate` (default), `qnx-x86_64`, `qnx-aarch64le` |
| `-d, --device` / `-i, --identity` | QNX device for tests (`user@host[:port]`, ssh key); default `$QPA_DEVICE` / `$QPA_SSH_IDENTITY` |
| `--no-ai`, `--max-rounds N` | repair loop off / limit |
| `--no-fix`, `--no-test`, `--no-shim` | skip a stage |
| `-c, --config` | a `qpa.yaml` other than `<project>/qpa.yaml` |

`qpa scan` also takes `--fail-on medium`, which fails CI when a change brings in new Linux-only code. `qpa rules` lists the rule set.

### Language model for the repair loop

| Variable | |
| --- | --- |
| `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` | picks the provider (or set `QPA_PROVIDER=anthropic\|openai`) |
| `QPA_MODEL` | model id (required) |
| `QPA_API_BASE` | another endpoint: a gateway, or a local OpenAI-compatible server |

Without a key the port still runs: rule fixes, shim, build and tests. The report lists the errors that need judgement. Every prompt and reply is saved in `<out>/ai/` for review.

### Per-project settings: `qpa.yaml`

```yaml
build:
  system: cmake                     # auto | cmake | autotools | make | custom
  cmake_args: [-DWITH_TLS=OFF]
test:
  command: ./build-qnx/tests/run    # run on the target, in /tmp/qpa/<project>
  files: [build-qnx/tests/run]      # copied to the target
```

See [`bench/projects.yaml`](bench/projects.yaml) for real examples.

## Targets

| Target | Needs | What it is |
| --- | --- | --- |
| `qnx-x86_64`, `qnx-aarch64le` | QNX SDP 8.0 | the real port: `ntox86_64-gcc` / `ntoaarch64-gcc` (or `qcc`), a generated QNX CMake toolchain, Autotools `--host=…-nto-qnx8.0.0`. The toolchain is probed so libqlinux only covers what QNX lacks. |
| `emulate` | a Linux host | a fast first pass. Linux-only headers the project uses become `#error` stubs, Linux-only functions are refused at link time (traced back to the calling lines), and `__linux__` is undefined so configure/CMake checks answer as on QNX. Not a substitute for the QNX toolchain. |

## libqlinux

[`libqlinux/`](libqlinux/README.md) provides `epoll` on `poll()`, `eventfd` on an anonymous FIFO, and `accept4`/`pipe2`/`dup3`/`SOCK_*` through `fcntl()`. qpa links it automatically. Standalone:

```sh
make -C libqlinux test                   # host tests (77 checks)
make -C libqlinux qnx ARCH=x86_64        # QNX 8.0 build; ARCH=aarch64le for Raspberry Pi 5
```

## Results

`python bench/run.py --no-ai` on the emulate target (full table: [bench/results/emulate.md](bench/results/emulate.md); details: [docs/testing.md](docs/testing.md)):

| Project | Lines | Build | Tests |
| --- | ---: | --- | --- |
| inih | 1,343 | pass | pass |
| libyaml | 17,197 | pass | pass |
| iperf3 | 21,274 | pass | pass (loopback throughput run) |
| mosquitto | 116,374 | pass | pass (broker + pub/sub; event loop on libqlinux epoll) |
| linux-sysmon (example) | 146 | needs repair loop | pass with it (2 compiler-checked rounds) |
| redis | 430,849 | 11 errors left without AI | – |
| htop | 48,950 | needs a QNX platform backend (reported as a redesign) | – |

To run everything on real QNX 8.0: `source qnxsdp-env.sh && ./scripts/qnx-e2e.sh`.

## Codelab

[Port a Linux service to QNX 8.0 with qpa](docs/codelab.md), about 30 minutes.

## Evidence of QNX use

| Where | What |
| --- | --- |
| `qpa/target.py` | QNX 8.0 targets: SDP compiler selection (`ntox86_64-gcc`, `ntoaarch64-gcc`, `qcc -Vgcc_nto…`), toolchain probes, CMake toolchain with `CMAKE_SYSTEM_NAME QNX`, Autotools `--host=x86_64-pc-nto-qnx8.0.0` |
| `qpa/vm.py`, `qpa vm up` | QNX 8.0 QEMU VM with `mkqnximage --type=qemu --run=-h`, `--getip`, `--ssh-ident` |
| `qpa/runner.py` | copies binaries to the QNX target and runs tests over ssh |
| `libqlinux/Makefile` (`qnx`, `qnx-test`) | builds the shim and its tests with `qcc -Vgcc_nto$(ARCH)` for x86_64 and aarch64le |
| `qpa/rules/*.yaml` | the Linux → QNX 8.0 mapping: `ThreadCtl(_NTO_TCTL_RUNMASK)`, `statvfs`, `mkqnx6fs`, io-sock routing sockets, io-audio, SLM… |
| `scripts/qnx-e2e.sh` | end-to-end run on a QNX VM: libqlinux tests on QNX, the example ported and tested, the benchmark |

**Target:** QNX SDP 8.0 (QNX Everywhere) · QEMU x86_64 and Raspberry Pi 5 · SDP gcc toolchain.

## Development

```sh
pip install -e '.[test]'
python -m pytest tests
make -C libqlinux test
python bench/run.py --no-ai --only inih libyaml
```

## License

MIT, see [LICENSE](LICENSE).
