from pathlib import Path

from qpa.build import parse_errors

LOG = """\
In file included from sysmon.c:22:
/work/.qpa/stubs/sys/sysinfo.h:1:2: error: #error "sys/sysinfo.h is not available on QNX 8.0 (qpa emulate target)"
sysmon.c:46:24: error: storage size of 'si' isn't known
sysmon.c:57:9: warning: unused variable 'x' [-Wunused-variable]
sysmon.c:57:16: error: attempt to use poisoned "sched_setaffinity"
sysmon.c:57:16: error: attempt to use poisoned "sched_setaffinity"
/usr/bin/ld: sysmon.o: in function `main':
sysmon.c:(.text+0x1a): undefined reference to `CPU_ZERO'
/usr/bin/ld: sysmon.o: in function `pin':
sysmon.c:(.text+0x2b): undefined reference to `__wrap_sched_setaffinity'
other.o: undefined reference to `missing_fn'
"""


def test_parse_errors_maps_stub_headers_to_the_include(tmp_path: Path):
    (tmp_path / "sysmon.c").write_text("x\nint pin(void) {\n  return sched_setaffinity(0, 1, 0);\n}\n")
    errs = parse_errors(LOG, tmp_path)
    assert errs[0].file == "sysmon.c" and errs[0].line == 22
    assert "sys/sysinfo.h" in errs[0].message and "not available" in errs[0].message
    keys = [(e.file, e.line) for e in errs]
    assert ("sysmon.c", 46) in keys and ("sysmon.c", 57) in keys
    assert keys.count(("sysmon.c", 57)) == 1                       # duplicates collapsed, warnings dropped
    link = {(e.file, e.line, e.message) for e in errs if "CPU_ZERO" in e.message or "sched_" in e.message
            or "missing_fn" in e.message}
    assert ("sysmon.c", 3, "sched_setaffinity() is not available on QNX 8.0") in link   # traced to the call
    assert ("<link>", 0, "undefined reference to missing_fn") in link                    # no source known
