"""Run a project's tests on the target: locally (emulate) or on a QNX device over ssh."""
from __future__ import annotations

import glob
import os
import shlex
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from .config import TestConfig

SSH_OPTS = ["-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=ERROR",
            "-o", "ConnectTimeout=15", "-o", "BatchMode=yes"]


@dataclass
class TestResult:
    ran: bool
    ok: bool
    where: str
    seconds: float
    output: str
    exit_code: int | None = None


@dataclass
class Device:
    user: str
    host: str
    port: int = 22
    identity: str | None = None

    @classmethod
    def parse(cls, spec: str, identity: str | None = None) -> "Device":
        user, _, rest = spec.rpartition("@")
        host, _, port = rest.partition(":")
        return cls(user or "root", host, int(port or 22), identity)

    def ssh(self, remote_cmd: str) -> list[str]:
        cmd = ["ssh", *SSH_OPTS, "-p", str(self.port)]
        if self.identity:
            cmd += ["-i", self.identity]
        return cmd + [f"{self.user}@{self.host}", remote_cmd]

    def scp(self, local: Path, remote: str) -> list[str]:
        cmd = ["scp", *SSH_OPTS, "-r", "-P", str(self.port)]
        if self.identity:
            cmd += ["-i", self.identity]
        return cmd + [str(local), f"{self.user}@{self.host}:{remote}"]

    def __str__(self) -> str:
        return f"{self.user}@{self.host}:{self.port}"


def _stage(src: Path, patterns: list[str], dest: Path) -> list[str]:
    copied = []
    for pat in patterns:
        for p in glob.glob(str(src / pat), recursive=True):
            rel = Path(p).relative_to(src)
            out = dest / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            if Path(p).is_dir():
                shutil.copytree(p, out, dirs_exist_ok=True)
            else:
                shutil.copy2(p, out)
            copied.append(str(rel))
    return copied


def run_local(src: Path, cfg: TestConfig) -> TestResult:
    t0 = time.monotonic()
    try:
        r = subprocess.run(cfg.command, shell=True, cwd=src, capture_output=True, text=True,
                           errors="replace", timeout=cfg.timeout)
        out, code = r.stdout + r.stderr, r.returncode
    except subprocess.TimeoutExpired as e:
        out, code = f"{e.stdout or ''}{e.stderr or ''}\n[timed out after {cfg.timeout}s]", None
    return TestResult(True, code == 0, "host (emulate)", round(time.monotonic() - t0, 1), out, code)


def run_remote(src: Path, cfg: TestConfig, dev: Device, name: str) -> TestResult:
    """Copy the test files to /tmp/qpa/<name> on the device and run the test command there."""
    t0 = time.monotonic()
    remote = f"/tmp/qpa/{name}"
    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp) / name
        stage.mkdir()
        files = _stage(src, cfg.files, stage)
        if not files:
            return TestResult(False, False, str(dev), 0.0, f"no files matched {cfg.files}")
        steps = [dev.ssh(f"rm -rf {shlex.quote(remote)} && mkdir -p /tmp/qpa"), dev.scp(stage, "/tmp/qpa/")]
        for cmd in steps:
            r = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=120)
            if r.returncode:
                return TestResult(False, False, str(dev), round(time.monotonic() - t0, 1),
                                  f"$ {' '.join(cmd)}\n{r.stdout}{r.stderr}", r.returncode)
    try:
        r = subprocess.run(dev.ssh(f"cd {shlex.quote(remote)} && {cfg.command}"), capture_output=True,
                           text=True, errors="replace", timeout=cfg.timeout)
        out, code = r.stdout + r.stderr, r.returncode
    except subprocess.TimeoutExpired as e:
        out, code = f"{e.stdout or ''}{e.stderr or ''}\n[timed out after {cfg.timeout}s]", None
    return TestResult(True, code == 0, str(dev), round(time.monotonic() - t0, 1), out, code)


def device_from_env() -> Device | None:
    spec = os.environ.get("QPA_DEVICE")
    return Device.parse(spec, os.environ.get("QPA_SSH_IDENTITY")) if spec else None
