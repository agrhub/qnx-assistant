from pathlib import Path

from qpa.fix import RuleFixer, parse_reply
from qpa.rules import load
from qpa.scanner import Scanner

SRC = """\
#include <sys/statfs.h>
#include <sys/prctl.h>
#include <time.h>
long f(void) {
    struct timespec t;
    clock_gettime(CLOCK_BOOTTIME, &t);
    struct statfs s;
    statfs("/", &s);
    prctl(PR_SET_NAME, "worker", 0, 0, 0);
    return t.tv_sec + (long)s.f_bsize;
}
#ifdef CLOCK_BOOTTIME
long g(void) { struct timespec t; return clock_gettime(CLOCK_BOOTTIME, &t); }
#endif
#ifdef __linux__
long h(void) { struct timespec t; clock_gettime(CLOCK_BOOTTIME, &t); return t.tv_sec; }
#endif
"""


def test_rule_fixer(tmp_path: Path):
    (tmp_path / "a.c").write_text(SRC)
    scanner = Scanner(load())
    res = scanner.scan(tmp_path)
    changes = RuleFixer(scanner).apply(tmp_path, res.findings)
    out = (tmp_path / "a.c").read_text()
    assert len(changes) == 1 and changes[0].diff.startswith("--- a/a.c")
    assert "clock_gettime(CLOCK_MONOTONIC, &t);\n    struct statvfs s;" in out
    assert 'statvfs("/", &s);' in out and "#include <sys/statvfs.h>" in out
    assert 'pthread_setname_np(pthread_self(), "worker");' in out and "#include <pthread.h>" in out
    assert "#ifdef CLOCK_BOOTTIME" in out                        # a condition is not rewritten
    assert "return clock_gettime(CLOCK_BOOTTIME, &t); }" in out  # nor code that already tests for it
    assert "{ struct timespec t; clock_gettime(CLOCK_BOOTTIME, &t)" in out   # Linux branch left alone


def test_prctl_include_kept_when_other_options_remain(tmp_path: Path):
    (tmp_path / "b.c").write_text('#include <sys/prctl.h>\nvoid f(void){ prctl(PR_SET_NAME,"a"); '
                                  'prctl(PR_SET_DUMPABLE,0); }\n')
    scanner = Scanner(load())
    RuleFixer(scanner).apply(tmp_path, scanner.scan(tmp_path).findings)
    out = (tmp_path / "b.c").read_text()
    assert "#include <sys/prctl.h>" in out and "prctl(PR_SET_DUMPABLE,0)" in out


def test_parse_reply_accepts_fenced_json():
    data = parse_reply('Here you go:\n```json\n{"edits": [{"file": "a.c", "search": "x", "replace": "y"}]}\n```')
    assert data["edits"][0]["replace"] == "y"
