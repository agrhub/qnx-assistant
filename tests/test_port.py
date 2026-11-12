"""End-to-end runs of `qpa port` on the bundled example, on the emulate target."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from qpa.llm import Replay
from qpa.port import port
from qpa.rules import load

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "examples" / "linux-sysmon"
REPLAY = ROOT / "tests" / "fixtures" / "sysmon-replay.json"

pytestmark = pytest.mark.skipif(not shutil.which("cc"), reason="needs a C compiler")


def test_port_with_repairs_builds_tests_and_patches(tmp_path: Path):
    res = port(EXAMPLE, tmp_path / "out", load(), provider=Replay(REPLAY))
    assert res.build_ok and res.test and res.test["ok"]
    assert [r["accepted"] for r in res.rounds] == [True, True]
    assert res.findings_after["easy"] == 0 and res.findings_before["easy"] > 0
    assert "64 of 64" in res.test["output"]

    # the patch applies to the untouched original and keeps the Linux build working
    work = tmp_path / "apply"
    shutil.copytree(EXAMPLE, work)
    subprocess.run(["git", "init", "-q"], cwd=work, check=True)
    subprocess.run(["git", "apply", str(tmp_path / "out" / "qnx-port.patch")], cwd=work, check=True)
    subprocess.run(["cc", "-O2", "-o", "sysmon", "sysmon.c"], cwd=work, check=True)
    assert subprocess.run(["./sysmon", "--selftest"], cwd=work).returncode == 0

    report = (tmp_path / "out" / "report.html").read_text()
    assert "QNX port report" in report and "AI repair rounds" in report
    assert json.loads((tmp_path / "out" / "port.json").read_text())["build"]["ok"] is True


def test_port_without_model_stops_with_a_clear_note(tmp_path: Path):
    res = port(EXAMPLE, tmp_path / "out", load(), provider=None)
    assert not res.build_ok and res.test is None
    assert any("no language model" in n for n in res.notes)
    msgs = " ".join(e["message"] for e in res.build["errors"])
    assert "sys/sysinfo.h" in msgs


def test_bad_edits_are_reverted(tmp_path: Path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps([
        {"edits": [{"file": "sysmon.c", "search": "does not exist", "replace": "x"}]},
        {"edits": [{"file": "sysmon.c", "search": "int main(int argc, char **argv)\n{",
                    "replace": "int main(int argc, char **argv)\n{ undeclared_thing();"}]},
    ]))
    res = port(EXAMPLE, tmp_path / "out", load(), provider=Replay(bad), max_rounds=2)
    assert not res.build_ok
    assert res.rounds[0]["applied"] == 0 and "found 0 times" in res.rounds[0]["problems"][0]
    assert res.rounds[1]["applied"] == 1 and res.rounds[1]["accepted"] is False
    assert "undeclared_thing" not in (tmp_path / "out" / "src" / "sysmon.c").read_text()
    assert not [c for c in res.changes if c["origin"] == "ai"]


def test_original_project_is_never_modified(tmp_path: Path):
    before = (EXAMPLE / "sysmon.c").read_text()
    port(EXAMPLE, tmp_path / "out", load(), provider=Replay(REPLAY))
    assert (EXAMPLE / "sysmon.c").read_text() == before
    assert not (EXAMPLE / "sysmon").exists()


@pytest.mark.skipif(not os.environ.get("QPA_TEST_DEVICE"), reason="set QPA_TEST_DEVICE=user@host[:port] "
                    "(and QPA_SSH_IDENTITY) to run the ssh test runner against a real device")
def test_remote_runner(tmp_path: Path):
    from qpa.config import load_config
    from qpa.runner import Device, run_remote
    res = port(EXAMPLE, tmp_path / "out", load(), provider=Replay(REPLAY), run_tests=False)
    assert res.build_ok
    dev = Device.parse(os.environ["QPA_TEST_DEVICE"], os.environ.get("QPA_SSH_IDENTITY"))
    tr = run_remote(tmp_path / "out" / "src", load_config(EXAMPLE).test, dev, "linux-sysmon")
    assert tr.ran and tr.ok, tr.output
