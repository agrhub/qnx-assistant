# QNX Port Assistant (`qpa`)

Find, fix and verify what keeps a Linux C/C++ project from running on **QNX 8.0**.

Porting a Linux project to QNX by hand means hunting for `epoll`, `/proc`, `/sys`, `systemctl` and dozens of other Linux-only details, one compiler error at a time. `qpa` reads the whole project, sorts every Linux-specific spot by how hard it is to port, says what to use on QNX instead, and ships a shim library that makes the commonest calls work unchanged.

```
$ qpa scan ./mosquitto
Scanned 605 files, 116,374 lines.
  Blocker      0
  Hard         2
  Medium      17
  Easy        10
  Review       0
  - [hard] Linux kernel headers: 2 in 1 file(s)
  - [medium] epoll: 12 in 1 file(s)
  ...
Report: qpa-report/report.html
```

## What it does

| Step | Command | Status |
| --- | --- | --- |
| Scan the project, classify every finding, write an HTML + JSON report | `qpa scan` | working |
| Make common Linux calls (epoll, eventfd, accept4, pipe2, dup3) work unchanged | `libqlinux` | working, host-tested |
| Check the QNX SDP 8.0 toolchain | `qpa doctor` | working |
| Apply fixes (rules first, then AI), each one checked by a real QNX build | `qpa fix` / `qpa build` | in progress |
| Run the project's tests on QNX 8.0 in QEMU or on a Raspberry Pi 5 | `qpa test` | in progress |

### Why the scanner works on the syntax tree

`qpa` parses C and C++ with tree-sitter instead of searching text, so:

- calls in comments or inside strings are never counted;
- an external command is reported only where the program really launches it: `system()`, `popen()`, `exec*()`, or an argv array that is passed to a launcher. A JSON key such as `"ip"` is not mistaken for the `ip` command, and option tables that happen to end in `NULL` are ignored;
- code that is already behind `#ifdef __linux__`, `HAVE_EPOLL` and similar is marked as *guarded*. It usually needs a QNX branch or a build option rather than a rewrite. In mosquitto, for example, all 12 epoll calls sit behind `WITH_EPOLL`.

Launched commands get their own category because no compiler will ever flag `nmcli` or `systemctl`; a port that builds cleanly can still fail the first time it runs.

### Levels

| Level | Meaning |
| --- | --- |
| Blocker | No QNX equivalent: needs a different design (e.g. a vendor NPU SDK) |
| Hard | Rewrite against a QNX service or driver API (sysfs, V4L2, GStreamer, NetworkManager) |
| Medium | Local rewrite or the libqlinux shim (epoll, eventfd, `/proc`, systemd) |
| Easy | Mechanical change (`statfs`, socket flags, `CLOCK_BOOTTIME`) |
| Review | A launched command that must exist on the target image |

The rules live in [`qpa/rules/linux_api.yaml`](qpa/rules/linux_api.yaml) and [`qpa/rules/commands.yaml`](qpa/rules/commands.yaml). Each rule records its QNX replacement and a confidence; `verified_on` is set once a rule has been proven by a real QNX 8.0 build.

## Install

```sh
pip install -e .            # Python 3.10+
qpa scan path/to/project -o report
open report/report.html
```

Useful options: `--exclude DIR` (repeatable), `--title NAME`, and `--fail-on medium` to make CI fail when a change brings in new Linux-only code. `qpa rules` lists every rule.

## libqlinux

[`libqlinux/`](libqlinux/README.md) implements `epoll` on top of `poll()`, `eventfd` on an anonymous FIFO, and `accept4`/`pipe2`/`dup3`/`SOCK_*` flags through `fcntl()`. Point the include path at `libqlinux/include/qlinux` and an unchanged `#include <sys/epoll.h>` builds on QNX.

```sh
cd libqlinux
make test                    # host logic tests
make qnx ARCH=x86_64         # QNX 8.0 build (QEMU); ARCH=aarch64le for Raspberry Pi 5
```

## Evidence of QNX use

- `libqlinux/Makefile`, targets `qnx` and `qnx-test`: builds the shim and its tests with the QNX SDP 8.0 `qcc` toolchain for `x86_64` (QEMU) and `aarch64le` (Raspberry Pi 5).
- `libqlinux/src/epoll.c`, `eventfd.c`, `compat.c`: replacements for Linux calls that QNX 8.0 does not provide.
- `qpa/rules/*.yaml`: the Linux → QNX 8.0 mapping used for every finding (e.g. `sched_setaffinity` → `ThreadCtl(_NTO_TCTL_RUNMASK)`, `mkfs.ext4` → `mkqnx6fs`, `/sys/class/net/*/address` → `getifaddrs(AF_LINK)`).
- `qpa/cli.py`, `doctor`: checks `QNX_HOST`, `QNX_TARGET` and the `qcc` / `ntox86_64-gcc` / `ntoaarch64-gcc` toolchain.

Target: QNX SDP 8.0 (QNX Everywhere), QEMU x86_64 and Raspberry Pi 5, `qcc` toolchain.

## Development

```sh
pip install -e '.[test]'
python -m pytest tests
make -C libqlinux test
```

## License

MIT, see [LICENSE](LICENSE).
