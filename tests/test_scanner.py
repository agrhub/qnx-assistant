from pathlib import Path

import pytest

from qpa.rules import load
from qpa.scanner import Scanner

FIXTURE = Path(__file__).parent / "fixtures" / "sample.c"


@pytest.fixture(scope="module")
def findings():
    res = Scanner(load()).scan(FIXTURE)
    return res.findings


def lines(findings, rule):
    return sorted(f.line for f in findings if f.rule == rule)


def test_includes(findings):
    assert lines(findings, "epoll") and lines(findings, "linux-headers") and lines(findings, "gstreamer")


def test_comments_and_strings_are_not_code(findings):
    # epoll_wait appears only in a comment and in a printf string
    assert not [f for f in findings if f.symbol == "epoll_wait"]


def test_json_key_is_not_a_command(findings):
    assert not [f for f in findings if f.rule == "cmd-ip"]


def test_launched_commands(findings):
    cmds = {(f.symbol, f.certainty) for f in findings if f.kind == "command"}
    assert ("nmcli", "certain") in cmds          # NULL-terminated argv array
    assert ("systemctl", "certain") in cmds      # system("systemctl ...")
    assert ("curl", "certain") in cmds           # execlp
    assert ("ping", "certain") in cmds           # argv behind timeout, passed to execvp
    assert ("parted", "likely") in cmds          # run("parted", ...) wrapper


def test_string_tables_are_not_argv(findings):
    assert not [f for f in findings if f.kind == "command" and f.symbol in ("yes", "no")]


def test_paths(findings):
    sysfs = [f for f in findings if f.rule == "sysfs"]
    assert sysfs and sysfs[0].symbol.startswith("/sys/class/net/")   # concatenated literal
    assert lines(findings, "proc-fs")


def test_call_prefix_and_identifiers(findings):
    assert [f for f in findings if f.rule == "gstreamer" and f.symbol == "gst_init"]
    assert [f for f in findings if f.rule == "socket-flags" and f.symbol == "MSG_NOSIGNAL"]


def test_linux_guard(findings):
    ev = sorted((f for f in findings if f.rule == "eventfd"), key=lambda f: f.line)
    assert len(ev) == 2
    assert ev[0].guard and "__linux__" in ev[0].guard   # inside #ifdef __linux__
    assert ev[1].guard is None                          # the #else branch


def test_every_rule_loads():
    rs = load()
    assert "epoll" in rs.rules and rs.match_call("gst_parse_launch") == "gstreamer"
    assert rs.match_include("linux/videodev2.h") in ("v4l2", "linux-headers")
