# Codelab: port a Linux service to QNX 8.0 with qpa

**Time:** about 30 minutes · **You will need:** a Linux host (Ubuntu 22.04/24.04), Python 3.10+, gcc, make, git. For the QNX part: a free [QNX Everywhere](https://qnx.software/en/developers/get-started/qnx-everywhere) licence and QNX SDP 8.0.

You will take `sysmon`, a small Linux monitoring daemon, and make it build and run on QNX 8.0. `sysmon` uses many of the Linux-only facilities that make real services hard to port:

| sysmon uses | Why it breaks on QNX 8.0 |
| --- | --- |
| `epoll` + `eventfd` event loop | no epoll or eventfd on QNX |
| `statfs()`, `<sys/statfs.h>` | Linux-only; QNX has POSIX `statvfs()` |
| `clock_gettime(CLOCK_BOOTTIME)` | Linux-only clock id |
| `prctl(PR_SET_NAME)` | Linux-only; QNX has `pthread_setname_np()` |
| `sysinfo()` | Linux-only |
| `sched_setaffinity()` / `cpu_set_t` | Linux-only; QNX uses `ThreadCtl(_NTO_TCTL_RUNMASK)` |
| `/proc/loadavg` | Linux `/proc` layout |

You will learn:
- how to see every Linux-only spot in a project before you start;
- which parts a shim makes work unchanged, which a mechanical rule rewrites, and which need a real change;
- how to keep the Linux build working while you add QNX support;
- how to run the result on a QNX 8.0 virtual machine.

## 1. Get qpa (2 min)

```sh
git clone https://github.com/agrhub/qnx-assistant
cd qnx-assistant
pip install -e .
qpa --version
```

## 2. See what is Linux-only (3 min)

```sh
qpa scan examples/linux-sysmon -o out/scan
```

```
Scanned 1 files, 146 lines.
  Blocker      0
  Hard         0
  Medium       7
  Easy        12
  Review       0
  - [medium] epoll: 4 in 1 file(s)
  - [medium] eventfd: 2 in 1 file(s)
  - [medium] Linux /proc layout: 1 in 1 file(s)
  - [easy] CPU affinity: 4 in 1 file(s)
  - [easy] prctl: 3 in 1 file(s)
  - [easy] statfs (Linux): 2 in 1 file(s)
  ...
```

Open `out/scan/report.html`. Each row is one kind of problem, with every place in the code, what to use on QNX instead, and how qpa will handle it:

- **libqlinux shim**: epoll and eventfd will work unchanged; qpa links its shim.
- **auto-fix**: `statfs`, `CLOCK_BOOTTIME` are rewritten mechanically.
- **AI rewrite + build check**: `sysinfo` and CPU affinity need a real change.
- **runtime**: `/proc/loadavg` compiles fine but has nothing to read on QNX; `sysmon` already prints `n/a` then.

## 3. Port it without the QNX SDP (5 min)

The `emulate` target builds on your Linux host with what QNX 8.0 lacks taken away: Linux-only headers fail, Linux-only functions fail to link, and `__linux__` is not defined.

```sh
qpa port examples/linux-sysmon -o out/emulate --no-ai
```

```
linux-sysmon -> emulate
  fixes      1 rule, 0 AI (0 AI round(s))
  build      FAILED (make, 1 attempt(s), 2 error(s) left)
  tests      not run
  note       no language model configured; ...
```

`out/emulate/qnx-port.patch` already holds the mechanical fixes:

```diff
-#include <sys/prctl.h>
-#include <sys/statfs.h>
+#include <pthread.h>
+#include <sys/statvfs.h>
...
-	if (clock_gettime(CLOCK_BOOTTIME, &ts) != 0)
+	if (clock_gettime(CLOCK_MONOTONIC, &ts) != 0)
...
-	prctl(PR_SET_NAME, "sysmon-worker", 0, 0, 0);
+	pthread_setname_np(pthread_self(), "sysmon-worker");
```

The two errors left are the ones that need judgement: `<sys/sysinfo.h>` and the CPU affinity code.

## 4. Let the repair loop finish it (5 min)

Give qpa a language model (any of these):

```sh
export ANTHROPIC_API_KEY=...   QPA_MODEL=<model id>
# or: export OPENAI_API_KEY=... QPA_MODEL=<model id>   [QPA_API_BASE=<OpenAI-compatible URL>]
qpa port examples/linux-sysmon -o out/emulate
```

No key at hand? Replay the hand-written responses that the test suite uses to exercise the loop (they are not model output, but they go through exactly the same checks):

```sh
QPA_PROVIDER=replay QPA_REPLAY=tests/fixtures/sysmon-replay.json \
  qpa port examples/linux-sysmon -o out/emulate
```

```
linux-sysmon -> emulate
  fixes      1 rule, 2 AI (2 AI round(s))
  build      OK (make, 3 attempt(s))
  tests      PASS on host (emulate)
```

The **AI repair rounds** table in the report shows how each round went. Round 1 fixed `sysinfo` and took the build from 2 errors to 1, a link error that qpa traced back to the `sched_setaffinity()` call. Round 2 fixed the affinity code and took it to 0. Each round's edits were kept only because the compiler got further. The model never decides alone. Every prompt and reply is in `out/emulate/ai/`.

The edits keep Linux as it was and add a QNX path:

```c
static int pin_to_cpu0(void)
{
#if defined(__QNX__)
	return ThreadCtl(_NTO_TCTL_RUNMASK, (void *)(uintptr_t)1u) == -1 ? -1 : 0;
#elif !defined(__linux__)
	return -1;
#else
	cpu_set_t set;
	...
	return sched_setaffinity(0, sizeof set, &set);
#endif
}
```

## 5. Keep the Linux build working (2 min)

```sh
cp -r examples/linux-sysmon /tmp/sysmon && cd /tmp/sysmon && git init -q
git apply ~/qnx-assistant/out/emulate/qnx-port.patch
cc -O2 -o sysmon sysmon.c && ./sysmon --selftest     # still PASS on Linux
cd -
```

The same patch serves both platforms, so it can be sent upstream.

## 6. Build for QNX 8.0 and run on a QNX virtual machine (10 min)

```sh
source ~/qnx800/qnxsdp-env.sh          # from QNX Software Center
qpa doctor                             # finds ntox86_64-gcc / qcc
eval "$(qpa vm up)"                    # mkqnximage --type=qemu, headless; sets QPA_DEVICE
qpa port examples/linux-sysmon -t qnx-x86_64 -o out/qnx
```

qpa builds libqlinux with the QNX toolchain, probes what the QNX libc already has, builds `sysmon` and copies it to the VM with `scp`. It then runs `./sysmon --selftest` there over `ssh`:

```
  build      OK (make, ...)
  tests      PASS on root@<vm-ip>:22
```

On a Raspberry Pi 5 running QNX 8.0, use `-t qnx-aarch64le -d root@<pi-ip>` instead of the VM. Stop the VM with `qpa vm down`.

## 7. Where to go next

- `python bench/run.py` ports seven projects (inih, libyaml, iperf3, mosquitto, redis, htop and sysmon) and writes a results table.
- Add a `qpa.yaml` to your own project (build options, test command, files to copy) and run `qpa port` on it.
- New Linux → QNX knowledge goes in `qpa/rules/*.yaml`; set `verified_on: qnx-8.0` once a real build proves a rule.
