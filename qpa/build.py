"""Configure and build a project with a prepared toolchain, and read its errors."""
from __future__ import annotations

import os
import re
import shlex
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from .config import BuildConfig
from .target import Toolchain

DIAG = re.compile(
    r"^(?P<file>[^\s:][^:\n]*?):(?P<line>\d+):(?:(?P<col>\d+):)?\s*(?P<sev>fatal error|error|warning):\s*(?P<msg>.*)$")
UNDEF = re.compile(r"(?:(?P<file>[^\s:]+\.(?:c|cc|cpp|cxx|C)):\([^)]*\): )?undefined reference to "
                   r"[`'\"](?P<sym>[^`'\"]+)[`'\"]")
CMAKE_ERR = re.compile(r"^CMake Error")


@dataclass
class Diagnostic:
    file: str
    line: int
    severity: str
    message: str

    @property
    def key(self) -> tuple:
        return (self.file, self.line, self.message)


@dataclass
class BuildResult:
    ok: bool
    system: str
    seconds: float
    errors: list[Diagnostic] = field(default_factory=list)
    log: str = ""
    step: str = ""


def detect_system(src: Path, cfg: BuildConfig) -> str:
    if cfg.system != "auto":
        return cfg.system
    if cfg.commands:
        return "custom"
    if (src / "CMakeLists.txt").exists():
        return "cmake"
    if (src / "configure").exists() or (src / "configure.ac").exists():
        return "autotools"
    if any((src / m).exists() for m in ("Makefile", "makefile", "GNUmakefile")):
        return "make"
    raise RuntimeError("no build system found (CMakeLists.txt, configure, Makefile); set build.commands in qpa.yaml")


INCLUDED_FROM = re.compile(r"^In file included from (?P<file>[^:]+):(?P<line>\d+)")
STUB = re.compile(r"\.qpa/stubs/(?P<header>.+)$")


def _rel(f: str, src: Path) -> str:
    p = Path(f)
    try:
        return str(p.resolve().relative_to(src.resolve())) if p.is_absolute() or (src / p).exists() else f
    except ValueError:
        return f


def parse_errors(log: str, src: Path) -> list[Diagnostic]:
    out: list[Diagnostic] = []
    seen = set()
    includer = None
    for raw in log.splitlines():
        inc = INCLUDED_FROM.match(raw.strip())
        if inc:
            includer = (inc.group("file"), int(inc.group("line")))
            continue
        m = DIAG.match(raw.strip())
        if m and m.group("sev") != "warning":
            f = m.group("file")
            stub = STUB.search(f)
            if stub and includer:
                # an #error stub of the emulate target: report it at the #include in the project
                d = Diagnostic(_rel(includer[0], src), includer[1], "error",
                               f"<{stub.group('header')}> is not available on QNX 8.0")
            else:
                d = Diagnostic(_rel(f, src), int(m.group("line")), "error", m.group("msg").strip())
            includer = None
        else:
            u = UNDEF.search(raw)
            if not u:
                continue
            for d in _link_error(u.group("sym"), u.group("file"), src):
                if d.key not in seen:
                    seen.add(d.key)
                    out.append(d)
            continue
        if d.key not in seen:
            seen.add(d.key)
            out.append(d)
    return out


def _link_error(sym: str, obj_src: str | None, src: Path) -> list[Diagnostic]:
    """A missing symbol, traced back to the lines that call it when the source file is known.
    `__wrap_X` comes from the emulate target refusing a Linux-only function X."""
    name = sym[len("__wrap_"):] if sym.startswith("__wrap_") else sym
    msg = f"{name}() is not available on QNX 8.0" if sym.startswith("__wrap_") else f"undefined reference to {sym}"
    hits = []
    if obj_src:
        cands = [src / obj_src] if (src / obj_src).is_file() else list(src.rglob(Path(obj_src).name))[:3]
        call = re.compile(rf"\b{re.escape(name)}\s*\(")
        for f in cands:
            for i, line in enumerate(f.read_text(errors="replace").splitlines(), 1):
                if call.search(line):
                    hits.append(Diagnostic(str(f.relative_to(src)), i, "error", msg))
    return hits[:5] or [Diagnostic("<link>", 0, "error", msg)]


class Builder:
    def __init__(self, src: Path, tc: Toolchain, cfg: BuildConfig, log_dir: Path):
        self.src = src
        self.tc = tc
        self.cfg = cfg
        self.system = detect_system(src, cfg)
        self.build_dir = src / "build-qnx" if self.system == "cmake" else src
        self.log_dir = log_dir
        self.configured = False
        self.attempt = 0
        jobs = cfg.jobs or os.cpu_count() or 2
        self.jobs = str(jobs)

    def _env(self) -> dict[str, str]:
        env = dict(os.environ)
        env.update(self.tc.env)
        env.update(self.cfg.env)
        return env

    def _sh(self, cmd: list[str] | str, cwd: Path, phase: str = "build") -> tuple[int, str]:
        env = self._env()
        env["QPA_PHASE"] = phase
        r = subprocess.run(cmd, cwd=cwd, env=env, shell=isinstance(cmd, str),
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
        shown = cmd if isinstance(cmd, str) else " ".join(shlex.quote(c) for c in cmd)
        return r.returncode, f"$ {shown}\n{r.stdout}"

    def _configure(self) -> tuple[int, str]:
        tcfile = self.tc.cmake_toolchain
        if self.system == "cmake":
            cmd = ["cmake", "-S", str(self.src), "-B", str(self.build_dir), "-DCMAKE_BUILD_TYPE=Release",
                   f"-DCMAKE_C_COMPILER={self.tc.env['CC']}", f"-DCMAKE_CXX_COMPILER={self.tc.env['CXX']}"]
            if tcfile:
                cmd.append(f"-DCMAKE_TOOLCHAIN_FILE={tcfile}")
            return self._sh(cmd + self.cfg.cmake_args, self.src, "configure")
        if self.system == "autotools":
            log = ""
            if not (self.src / "configure").exists():
                gen = ["./autogen.sh"] if (self.src / "autogen.sh").exists() else ["autoreconf", "-fi"]
                rc, out = self._sh(gen, self.src, "configure")
                log += out
                if rc:
                    return rc, log
            cmd = ["./configure"]
            if self.tc.target.host_triple:
                cmd.append(f"--host={self.tc.target.host_triple}")
            rc, out = self._sh(cmd + self.cfg.configure_args, self.src, "configure")
            return rc, log + out
        return 0, ""

    def _compile(self) -> tuple[int, str]:
        if self.system == "cmake":
            # -k: keep going past the first failing file so every error is seen at once
            return self._sh(["cmake", "--build", str(self.build_dir), "-j", self.jobs, "--", "-k"], self.src)
        if self.system in ("autotools", "make"):
            env = self.tc.env
            return self._sh(["make", "-k", "-j", self.jobs, f"CC={env['CC']}", f"CXX={env['CXX']}",
                             f"AR={env['AR']}", *self.cfg.make_args], self.src)
        log, rc = "", 0
        for c in self.cfg.commands:
            rc, out = self._sh(c, self.src)
            log += out
            if rc:
                break
        return rc, log

    def build(self) -> BuildResult:
        """Configure once, then (re)build. Later calls only rebuild."""
        self.attempt += 1
        t0 = time.monotonic()
        log = ""
        if not self.configured:
            rc, log = self._configure()
            if rc:
                return self._done(False, "configure", log, t0)
            self.configured = True
        rc, out = self._compile()
        return self._done(rc == 0, "build", log + out, t0)

    def _done(self, ok: bool, step: str, log: str, t0: float) -> BuildResult:
        self.log_dir.mkdir(parents=True, exist_ok=True)
        (self.log_dir / f"build-{self.attempt:02d}.log").write_text(log)
        errs = [] if ok else parse_errors(log, self.src)
        if not ok and not errs:
            tail = "\n".join(log.strip().splitlines()[-15:])
            errs = [Diagnostic(f"<{step}>", 0, "error", tail)]
        return BuildResult(ok, self.system, round(time.monotonic() - t0, 1), errs, log, step)
