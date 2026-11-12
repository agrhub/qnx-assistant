"""qpa port: scan -> rule fixes -> build -> AI repair -> test -> report, in one run."""
from __future__ import annotations

import json
import shutil
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .build import Builder, BuildResult
from .config import load_config
from .fix import Change, RuleFixer, ai_repair, unified
from .llm import Provider
from .report import write_html, write_json
from .rules import LEVELS, RuleSet
from .runner import Device, TestResult, run_local, run_remote
from .scanner import Scanner
from .target import make_target, prepare

COPY_IGNORE = shutil.ignore_patterns(".git", ".qpa", "build-qnx", "node_modules", "__pycache__", "*.o", "*.a")


@dataclass
class PortResult:
    project: str
    target: str
    out: str
    phases: dict = field(default_factory=dict)       # name -> seconds
    findings_before: dict = field(default_factory=dict)
    findings_after: dict = field(default_factory=dict)
    changes: list[dict] = field(default_factory=list)
    rounds: list[dict] = field(default_factory=list)
    build: dict = field(default_factory=dict)
    test: dict | None = None
    blocked_headers: list[str] = field(default_factory=list)
    shim_have: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def build_ok(self) -> bool:
        return bool(self.build.get("ok"))


def open_findings(scan, rules: RuleSet, shim: bool) -> dict:
    """Findings still to handle: not behind a Linux #if and not covered by libqlinux."""
    out = {lv: 0 for lv in LEVELS}
    for f in scan.findings:
        r = rules.rules[f.rule]
        if f.guard or (shim and r.fix == "shim"):
            continue
        out[r.level] += 1
    return out


def _build_dict(b: BuildResult, attempts: int) -> dict:
    return {"ok": b.ok, "system": b.system, "step": b.step, "attempts": attempts,
            "errors": [asdict(e) for e in b.errors[:50]], "error_count": len(b.errors),
            "log_tail": "\n".join(b.log.strip().splitlines()[-40:])}


def port(project: Path, out: Path, rules: RuleSet, *, target_name: str = "emulate", provider: Provider | None = None,
         max_rounds: int = 6, fix: bool = True, run_tests: bool = True, device: Device | None = None,
         config_path: Path | None = None, shim: bool = True, title: str | None = None) -> PortResult:
    project = project.resolve()
    cfg = load_config(project, config_path)
    out.mkdir(parents=True, exist_ok=True)
    src = out / "src"
    if src.exists():
        shutil.rmtree(src)
    shutil.copytree(project, src, ignore=COPY_IGNORE, symlinks=True)
    res = PortResult(project.name, target_name, str(out))
    t_all = time.monotonic()

    # 1. scan
    t0 = time.monotonic()
    scanner = Scanner(rules, set(cfg.exclude))
    scan = scanner.scan(src)
    res.findings_before = open_findings(scan, rules, shim)
    res.phases["scan"] = round(time.monotonic() - t0, 2)

    # 2. deterministic fixes
    changes: list[Change] = []
    if fix:
        t0 = time.monotonic()
        changes += RuleFixer(scanner).apply(src, scan.findings)
        res.phases["rule fixes"] = round(time.monotonic() - t0, 2)

    # 3. toolchain + build
    t0 = time.monotonic()
    target = make_target(target_name)
    # every Linux header the project names, guarded or not: a configure check for it must fail as on QNX
    includes = {f.symbol for f in scan.findings if f.kind == "include"}
    tc = prepare(target, src, includes, shim=shim)
    res.blocked_headers, res.shim_have = tc.blocked, tc.have
    builder = Builder(src, tc, cfg.build, out / "logs")
    first = builder.build()
    res.phases["build"] = round(time.monotonic() - t0, 2)

    # 4. AI repair loop
    final = first
    if fix and not first.ok:
        t0 = time.monotonic()
        log = ai_repair(builder, src, rules, scan.findings, provider, max_rounds, out / "ai", first)
        changes += log.changes
        res.rounds = log.rounds
        final = log.final or first
        if log.note:
            res.notes.append(log.note)
        res.phases["AI repair"] = round(time.monotonic() - t0, 2)
    res.build = _build_dict(final, builder.attempt)
    res.changes = [asdict(c) for c in changes]

    # 5. tests
    if run_tests and final.ok and cfg.test.command:
        t0 = time.monotonic()
        if target.is_qnx:
            if device is None:
                res.notes.append("tests not run: no QNX device (use --device user@host or `qpa vm up`)")
            else:
                tr = run_remote(src, cfg.test, device, project.name)
                res.test = asdict(tr)
        else:
            res.test = asdict(run_local(src, cfg.test))
        res.phases["test"] = round(time.monotonic() - t0, 2)
    elif run_tests and not cfg.test.command:
        res.notes.append("no test command configured (test.command in qpa.yaml)")

    # 6. what is left, the patch and the reports
    after = scanner.scan(src)
    res.findings_after = open_findings(after, rules, shim)
    # one diff per file, original -> final, so `git apply` takes it in one go
    patch = "".join(unified(f, (project / f).read_text(errors="replace"), (src / f).read_text(errors="replace"))
                    for f in sorted({c.file for c in changes}))
    (out / "qnx-port.patch").write_text(patch)
    res.phases["total"] = round(time.monotonic() - t_all, 2)
    data = asdict(res)
    (out / "port.json").write_text(json.dumps(data, indent=2, ensure_ascii=False))
    write_json(scan, rules, out / "report.json")
    write_html(scan, rules, out / "report.html", title or project.name, port=data)
    return res


def test_ok(res: PortResult) -> bool:
    t = res.test
    return bool(t and t.get("ok"))


__all__ = ["port", "PortResult", "TestResult", "test_ok"]
