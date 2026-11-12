"""Start and stop a QNX 8.0 QEMU virtual machine with the SDP's mkqnximage.

The image is built in ~/.qpa/vm/<arch> (or $QPA_VM_DIR). mkqnximage images log
in as root over ssh; an ssh key is generated and installed with --ssh-ident so
qpa can copy and run tests without a password.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from .runner import Device


def vm_dir(arch: str) -> Path:
    return Path(os.environ.get("QPA_VM_DIR", Path.home() / ".qpa" / "vm")) / arch


def _key(d: Path) -> Path:
    key = d / "id_qpa"
    if not key.exists():
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)], check=True)
    return key


def _mk(d: Path, *args: str, capture: bool = False) -> subprocess.CompletedProcess:
    if not shutil.which("mkqnximage"):
        raise RuntimeError("mkqnximage not found: source the QNX SDP 8.0 environment (qnxsdp-env.sh)")
    return subprocess.run(["mkqnximage", *args], cwd=d, check=True, text=True,
                          capture_output=capture)


def up(arch: str = "x86_64") -> Device:
    d = vm_dir(arch)
    d.mkdir(parents=True, exist_ok=True)
    key = _key(d)
    _mk(d, "--type=qemu", f"--arch={arch}", f"--ssh-ident={key}.pub", "--run=-h")
    ip = _mk(d, "--getip", capture=True).stdout.strip().splitlines()[-1]
    return Device("root", ip, 22, str(key))


def down(arch: str = "x86_64") -> None:
    _mk(vm_dir(arch), "--stop")
