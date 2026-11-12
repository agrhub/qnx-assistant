"""Build targets: the real QNX 8.0 toolchain, or a QNX API emulation on the host.

Every target is driven through small compiler wrappers (cc / c++) written into
the work tree. A wrapper adds what the port needs to any build system
(CMake, Autotools, plain make) without touching its files:
  * the libqlinux shim headers and, at link time, the shim library;
  * on the `emulate` target, the QNX API emulation header and stub headers.

`emulate` runs on a Linux host without the QNX SDP. It removes, for the
project being built, what QNX 8.0 does not provide:
  * Linux-only headers the project names become `#error` stubs (headers the
    host libc includes for itself are left alone);
  * Linux-only functions are refused at link time (`ld --wrap` with no
    wrapper), and the link errors are traced back to the calling lines;
  * `__linux__` is undefined, so code takes its non-Linux branches and
    configure/CMake checks answer as they would on QNX.
Nothing is pre-included, so the project's own feature macros (_GNU_SOURCE,
_XOPEN_SOURCE, ...) behave exactly as in a normal build. It is a fast first
check, not a replacement for building with the real QNX toolchain.
"""
from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

QLINUX_SRC = Path(os.environ.get("QPA_QLINUX", Path(__file__).resolve().parent.parent / "libqlinux"))
SHIM_HEADERS = {"sys/epoll.h", "sys/eventfd.h"}

# Ordinary POSIX headers: whatever Linux headers the host libc includes through these is libc's own
# business and is never stubbed.
LIBC_PROBE = [
    "stdio.h", "stdlib.h", "string.h", "unistd.h", "fcntl.h", "time.h", "sched.h", "pthread.h",
    "sys/types.h", "sys/mman.h", "sys/socket.h",
    "errno.h", "limits.h", "signal.h", "poll.h", "dirent.h", "dlfcn.h", "netdb.h", "ifaddrs.h", "termios.h",
    "glob.h", "pwd.h", "grp.h", "arpa/inet.h", "net/if.h", "netinet/in.h", "netinet/tcp.h", "netinet/udp.h",
    "sys/stat.h", "sys/statvfs.h", "sys/time.h", "sys/uio.h", "sys/select.h", "sys/wait.h", "sys/resource.h",
    "sys/ioctl.h", "sys/un.h", "sys/param.h", "sys/utsname.h", "sys/ipc.h", "sys/shm.h", "sys/msg.h",
    "sys/sem.h", "sys/sysmacros.h",
]
SHIMMED_CALLS = ["accept4", "pipe2", "dup3"]   # refused too when the shim is off
# Linux-only functions; a link that references them fails (ld --wrap with no wrapper), which also
# makes CMake/Autotools function checks answer "no", as they would on QNX.
ABSENT_FUNCS = [
    "sched_setaffinity", "sched_getaffinity", "pthread_setaffinity_np", "pthread_getaffinity_np",
    "memfd_create", "splice", "tee", "vmsplice", "copy_file_range",
    "epoll_create", "epoll_create1", "epoll_ctl", "epoll_wait", "epoll_pwait",
    "eventfd", "eventfd_read", "eventfd_write", "timerfd_create", "timerfd_settime", "timerfd_gettime",
    "signalfd", "prctl", "sysinfo", "statfs", "fstatfs", "sendfile",
    "backtrace", "backtrace_symbols", "backtrace_symbols_fd",
]
# Headers that are not on QNX 8.0 even when a project only uses them indirectly.
ALWAYS_BLOCKED = [
    "sys/epoll.h", "sys/eventfd.h", "sys/timerfd.h", "sys/signalfd.h", "sys/prctl.h", "sys/sysinfo.h",
    "sys/vfs.h", "sys/statfs.h", "sys/sendfile.h", "execinfo.h", "liburing.h", "libaio.h",
]

PROBES = {
    "ACCEPT4": "#include <sys/socket.h>\nint main(void){return accept4(0,0,0,0);}\n",
    "PIPE2": "#include <unistd.h>\n#include <fcntl.h>\nint main(void){int p[2];return pipe2(p,0);}\n",
    "DUP3": "#include <unistd.h>\n#include <fcntl.h>\nint main(void){return dup3(0,1,0);}\n",
}


@dataclass
class Target:
    name: str
    kind: str                     # qnx | emulate
    arch: str = "x86_64"          # x86_64 | aarch64le
    cc: list[str] = field(default_factory=list)
    cxx: list[str] = field(default_factory=list)
    ar: str = "ar"
    host_triple: str | None = None

    @property
    def is_qnx(self) -> bool:
        return self.kind == "qnx"


TARGETS = ("emulate", "qnx-x86_64", "qnx-aarch64le")


def make_target(name: str) -> Target:
    if name == "emulate":
        return Target("emulate", "emulate", os.uname().machine,
                      [os.environ.get("CC", "cc")], [os.environ.get("CXX", "c++")], "ar")
    if name not in TARGETS:
        raise ValueError(f"unknown target {name}; choose from {', '.join(TARGETS)}")
    arch = name.split("-", 1)[1]
    short = arch[:-2] if arch.endswith("le") else arch
    triple = f"{short}-pc-nto-qnx8.0.0" if short == "x86_64" else f"{short}-unknown-nto-qnx8.0.0"
    if shutil.which(f"nto{short}-gcc"):
        cc, cxx = [f"nto{short}-gcc"], [f"nto{short}-g++"]
    elif shutil.which("qcc"):
        cc, cxx = ["qcc", f"-Vgcc_nto{arch}"], ["q++", f"-Vgcc_nto{arch}_cxx"]
    else:
        raise RuntimeError("QNX SDP 8.0 compiler not found: source qnxsdp-env.sh first (see `qpa doctor`)")
    return Target(name, "qnx", arch, cc, cxx, f"nto{short}-ar", triple)


@dataclass
class Toolchain:
    target: Target
    root: Path                     # <work>/.qpa
    env: dict[str, str]
    shim_lib: Path | None
    have: list[str]                # QLINUX_HAVE_* found by probing
    cmake_toolchain: Path | None
    blocked: list[str]


def _run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)


def _probe(target: Target, root: Path) -> list[str]:
    if not target.is_qnx:
        return []                  # emulate assumes the pessimistic case: use the shim
    have = []
    d = root / "probe"
    d.mkdir(parents=True, exist_ok=True)
    for name, src in PROBES.items():
        f = d / f"{name.lower()}.c"
        f.write_text(src)
        if _run([*target.cc, str(f), "-o", str(d / name.lower())]).returncode == 0:
            have.append(name)
    return have


def _build_shim(target: Target, root: Path) -> Path:
    out = root / "qlinux"
    out.mkdir(parents=True, exist_ok=True)
    objs = []
    for src in ("epoll.c", "eventfd.c", "compat.c"):
        obj = out / src.replace(".c", ".o")
        r = _run([*target.cc, "-std=c11", "-O2", "-D_POSIX_C_SOURCE=200809L",
                  f"-I{QLINUX_SRC / 'include' / 'qlinux'}", "-c", str(QLINUX_SRC / "src" / src), "-o", str(obj)])
        if r.returncode != 0:
            raise RuntimeError(f"building libqlinux for {target.name} failed:\n{r.stderr}")
        objs.append(str(obj))
    lib = out / "libqlinux.a"
    lib.unlink(missing_ok=True)
    r = _run([target.ar, "rcs", str(lib), *objs])
    if r.returncode != 0:
        raise RuntimeError(f"archiving libqlinux failed:\n{r.stderr}")
    return lib


def _libc_headers(cc: list[str], root: Path) -> set[str]:
    """Linux headers that the host libc pulls in by itself; these must never be stubbed."""
    probe = root / "libc-headers.c"
    probe.write_text("".join(f"#include <{h}>\n" for h in LIBC_PROBE))
    r = _run([*cc, "-D_GNU_SOURCE", "-M", str(probe)])
    found = set()
    for tok in r.stdout.replace("\\\n", " ").split():
        if "/include/" not in tok:
            continue
        rel = tok.rsplit("/include/", 1)[1]
        first, _, rest = rel.partition("/")
        if "-linux-" in first and rest:      # multiarch directory, e.g. x86_64-linux-gnu/asm/...
            rel = rest
        found.add(rel)
    return found


def _stubs(stub_dir: Path, headers: list[str]) -> None:
    for h in headers:
        f = stub_dir / h
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(f'#error "{h} is not available on QNX 8.0 (qpa emulate target)"\n')


def _wrapper(path: Path, real: list[str], pre: list[str], post: list[str], build_only: list[str]) -> None:
    """build_only flags are left out while a build system configures (QPA_PHASE=configure):
    feature checks such as `char socket(); socket();` must not see pre-included headers."""
    q = lambda xs: " ".join(shlex.quote(x) for x in xs)  # noqa: E731
    path.write_text(f"""#!/bin/sh
# Generated by qpa: compiler wrapper for the port.
link=1
for a in "$@"; do case "$a" in -c|-S|-E|-M|-MM) link=0 ;; esac; done
if [ "$QPA_PHASE" != configure ]; then set -- {q(build_only)} "$@"; fi
if [ "$link" = 1 ]; then exec {q(real)} {q(pre)} "$@" {q(post)}; fi
exec {q(real)} {q(pre)} "$@"
""")
    path.chmod(0o755)


def prepare(target: Target, work: Path, include_headers: set[str], shim: bool = True) -> Toolchain:
    """Set up wrappers, the shim and (for emulate) the API emulation in <work>/.qpa."""
    root = work / ".qpa"
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    have = _probe(target, root)
    lib = _build_shim(target, root) if shim else None

    pre: list[str] = []
    build_only: list[str] = []
    blocked: list[str] = []
    post = [str(lib)] if lib else []
    if shim:
        pre += [f"-I{QLINUX_SRC / 'include' / 'qlinux'}"]
    if target.kind == "emulate":
        stub_dir = root / "stubs"
        wanted = (set(ALWAYS_BLOCKED) | set(include_headers)) - (SHIM_HEADERS if shim else set())
        blocked = sorted(wanted - _libc_headers(target.cc, root))
        _stubs(stub_dir, blocked)
        pre += [f"-I{stub_dir}", "-U__linux__", "-U__linux", "-Ulinux", "-U__gnu_linux__", "-DQPA_EMULATE=1"]
        # the host libc has accept4/pipe2/dup3; whether QNX does is probed on the real target
        absent = ABSENT_FUNCS + ([] if shim else SHIMMED_CALLS)
        post += ["-lpthread"] + [f"-Wl,--wrap={fn}" for fn in absent]
    elif shim:
        pre += [f"-I{QLINUX_SRC / 'include'}"]
        build_only = ["-DQLINUX_FORCE_INCLUDE", "-include", "qlinux/compat.h"]
        build_only += [f"-DQLINUX_HAVE_{h}" for h in have]

    bindir = root / "bin"
    bindir.mkdir()
    _wrapper(bindir / "cc", target.cc, pre, post, build_only)
    _wrapper(bindir / "c++", target.cxx, pre, post, build_only)

    env = {"CC": str(bindir / "cc"), "CXX": str(bindir / "c++"), "AR": target.ar,
           "RANLIB": target.ar.replace("-ar", "-ranlib") if target.is_qnx else "ranlib"}
    tc = None
    if target.is_qnx:
        tc = root / "qnx.toolchain.cmake"
        tc.write_text(f"""# Generated by qpa
set(CMAKE_SYSTEM_NAME QNX)
set(CMAKE_SYSTEM_PROCESSOR {target.arch})
set(CMAKE_C_COMPILER {env['CC']})
set(CMAKE_CXX_COMPILER {env['CXX']})
set(CMAKE_AR {shutil.which(target.ar) or target.ar} CACHE FILEPATH "")
# no CMAKE_SYSROOT: the QNX compilers already point at $QNX_TARGET (headers) and $QNX_TARGET/<arch> (libs)
set(CMAKE_FIND_ROOT_PATH $ENV{{QNX_TARGET}} $ENV{{QNX_TARGET}}/{target.arch})
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
""")
    return Toolchain(target, root, env, lib, have, tc, blocked)
