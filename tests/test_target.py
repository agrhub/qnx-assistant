"""The QNX target path, driven by a stand-in toolchain (ntox86_64-* -> host tools).

This checks qpa's own plumbing (compiler choice, probes, wrappers, CMake
toolchain file), not QNX itself; real QNX builds need the SDP.
"""
import shutil
from pathlib import Path

import pytest

from qpa.target import make_target, prepare

pytestmark = pytest.mark.skipif(not shutil.which("cc"), reason="needs a C compiler")


@pytest.fixture
def fake_sdp(tmp_path: Path, monkeypatch):
    bin_dir = tmp_path / "sdp" / "bin"
    bin_dir.mkdir(parents=True)
    for tool, real in (("gcc", "cc"), ("g++", "c++"), ("ar", "ar"), ("ranlib", "ranlib")):
        f = bin_dir / f"ntox86_64-{tool}"
        f.write_text(f'#!/bin/sh\nexec {real} "$@"\n')
        f.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:{__import__('os').environ['PATH']}")
    monkeypatch.setenv("QNX_TARGET", str(tmp_path / "sdp" / "target"))
    return bin_dir


def test_qnx_target_prefers_nto_gcc(fake_sdp):
    t = make_target("qnx-x86_64")
    assert t.is_qnx and t.cc == ["ntox86_64-gcc"] and t.ar == "ntox86_64-ar"
    assert t.host_triple == "x86_64-pc-nto-qnx8.0.0"


def test_prepare_qnx(fake_sdp, tmp_path: Path):
    tc = prepare(make_target("qnx-x86_64"), tmp_path / "work", set())
    assert tc.shim_lib and tc.shim_lib.exists()
    assert set(tc.have) == {"ACCEPT4", "PIPE2", "DUP3"}           # the stand-in libc has them
    wrapper = Path(tc.env["CC"]).read_text()
    assert "-DQLINUX_FORCE_INCLUDE" in wrapper and "-DQLINUX_HAVE_ACCEPT4" in wrapper
    cmake = tc.cmake_toolchain.read_text()
    assert "set(CMAKE_SYSTEM_NAME QNX)" in cmake and tc.env["CC"] in cmake


def test_prepare_emulate_blocks_linux_headers(tmp_path: Path):
    tc = prepare(make_target("emulate"), tmp_path / "work", {"linux/input.h", "sys/epoll.h", "linux/types.h"})
    assert "linux/input.h" in tc.blocked and "sys/sysinfo.h" in tc.blocked
    assert "sys/epoll.h" not in tc.blocked                       # provided by libqlinux
    assert "#error" in (tc.root / "stubs" / "linux" / "input.h").read_text()
    wrapper = Path(tc.env["CC"]).read_text()
    assert "-U__linux__" in wrapper and "-Wl,--wrap=sched_setaffinity" in wrapper
    assert "linux/types.h" not in tc.blocked        # the host libc includes it itself


def test_unknown_target():
    with pytest.raises(ValueError):
        make_target("qnx-mips")
