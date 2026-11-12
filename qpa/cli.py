"""qpa – QNX Port Assistant command line."""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import typer

from . import __version__
from .report import LEVEL_LABEL, summarize, write_html, write_json
from .rules import LEVELS, load
from .scanner import Scanner
from .target import TARGETS

app = typer.Typer(add_completion=False, no_args_is_help=True,
                  help="Find, fix and verify what keeps a Linux C/C++ project from running on QNX 8.0.")


@app.command()
def scan(
    path: Path = typer.Argument(..., exists=True, help="Project directory or a single source file."),
    out: Path = typer.Option(Path("qpa-report"), "--out", "-o", help="Directory for report.html and report.json."),
    exclude: list[str] = typer.Option([], "--exclude", "-x", help="Extra directory names to skip (repeatable)."),
    title: str = typer.Option(None, help="Project name shown in the report."),
    fail_on: str = typer.Option(None, help="Exit with status 1 if any finding is at this level or harder "
                                           "(blocker, hard, medium, easy). Useful in CI."),
):
    """Scan a project for Linux-specific code and write a porting report."""
    rules = load()
    res = Scanner(rules, set(exclude)).scan(path)
    out.mkdir(parents=True, exist_ok=True)
    write_json(res, rules, out / "report.json")
    write_html(res, rules, out / "report.html", title)

    s = summarize(res, rules)
    typer.echo(f"Scanned {s['files']} files, {s['lines']:,} lines.")
    for lv in LEVELS:
        typer.echo(f"  {LEVEL_LABEL[lv]:<8} {s['by_level'][lv]:>5}")
    for p in s["plan"][:8]:
        typer.echo(f"  - [{p['level']}] {p['title']}: {p['occurrences']} in {p['files']} file(s)")
    typer.echo(f"Report: {out / 'report.html'}")

    if fail_on:
        if fail_on not in LEVELS:
            raise typer.BadParameter(f"--fail-on must be one of {', '.join(LEVELS[:-1])}")
        worst = LEVELS[: LEVELS.index(fail_on) + 1]
        if any(s["by_level"][lv] for lv in worst):
            raise typer.Exit(1)


@app.command()
def port(
    path: Path = typer.Argument(..., exists=True, file_okay=False, help="Project directory (left untouched)."),
    out: Path = typer.Option(Path("qpa-port"), "--out", "-o", help="Work directory: ported copy, logs, patch, report."),
    target: str = typer.Option("emulate", "--target", "-t", help=f"One of: {', '.join(TARGETS)}."),
    device: str = typer.Option(None, "--device", "-d", help="QNX device for tests, user@host[:port] "
                                                         "(default $QPA_DEVICE)."),
    identity: str = typer.Option(None, "--identity", "-i", help="ssh private key for the device."),
    ai: bool = typer.Option(True, "--ai/--no-ai", help="Use a language model for errors the rules do not fix."),
    max_rounds: int = typer.Option(6, help="Most AI repair rounds."),
    fix: bool = typer.Option(True, "--fix/--no-fix", help="Apply fixes (off: only build and test as-is)."),
    test: bool = typer.Option(True, "--test/--no-test", help="Run the project's tests after a good build."),
    shim: bool = typer.Option(True, "--shim/--no-shim", help="Link libqlinux (epoll, eventfd, accept4, ...)."),
    config: Path = typer.Option(None, "--config", "-c", help="qpa.yaml to use instead of <project>/qpa.yaml."),
    title: str = typer.Option(None, help="Project name shown in the report."),
):
    """Port a project: scan, fix, build for QNX, repair with AI, run its tests, report."""
    from .llm import LLMError, get_provider
    from .port import port as run_port
    from .runner import Device, device_from_env

    provider = None
    if ai:
        try:
            provider = get_provider()
        except LLMError as e:
            raise typer.BadParameter(str(e))
    dev = Device.parse(device, identity) if device else device_from_env()
    res = run_port(path, out, load(), target_name=target, provider=provider, max_rounds=max_rounds, fix=fix,
                   run_tests=test, device=dev, config_path=config, shim=shim, title=title)

    b, t = res.build, res.test
    rule_n = sum(1 for c in res.changes if c["origin"].startswith("rule"))
    ai_n = sum(1 for c in res.changes if c["origin"] == "ai")
    typer.echo(f"{res.project} -> {res.target}")
    typer.echo(f"  fixes      {rule_n} rule, {ai_n} AI ({len(res.rounds)} AI round(s))")
    typer.echo(f"  build      {'OK' if b['ok'] else 'FAILED'} ({b['system']}, {b['attempts']} attempt(s)"
               + ("" if b["ok"] else f", {b['error_count']} error(s) left") + ")")
    typer.echo(f"  tests      {('PASS' if t['ok'] else 'FAIL') + ' on ' + t['where'] if t and t['ran'] else 'not run'}")
    for n in res.notes:
        typer.echo(f"  note       {n}")
    typer.echo(f"  report     {out / 'report.html'}")
    typer.echo(f"  patch      {out / 'qnx-port.patch'}")
    if not b["ok"] or (t is not None and not t["ok"]):
        raise typer.Exit(1)


vm_app = typer.Typer(help="Start or stop a QNX 8.0 QEMU virtual machine (needs the QNX SDP).")
app.add_typer(vm_app, name="vm")


@vm_app.command("up")
def vm_up(arch: str = typer.Option("x86_64", help="x86_64 or aarch64le")):
    """Build (first time) and boot a headless QNX VM; prints the --device to use."""
    from . import vm
    dev = vm.up(arch)
    typer.echo(f"QNX VM is up at {dev.host}; use: eval \"$(qpa vm up)\"", err=True)
    typer.echo(f"export QPA_DEVICE={dev.user}@{dev.host} QPA_SSH_IDENTITY={dev.identity}")


@vm_app.command("down")
def vm_down(arch: str = typer.Option("x86_64", help="x86_64 or aarch64le")):
    """Stop the QNX VM."""
    from . import vm
    vm.down(arch)


@app.command()
def rules():
    """List the Linux -> QNX rules the scanner knows."""
    rs = load()
    for lv in LEVELS:
        for r in rs.rules.values():
            if r.level == lv:
                typer.echo(f"[{lv:<7}] {r.id:<22} {r.title}  ->  {r.qnx}")


@app.command()
def doctor():
    """Check that the QNX SDP 8.0 toolchain is available for build and test."""
    ok = True
    for var in ("QNX_HOST", "QNX_TARGET"):
        val = os.environ.get(var)
        typer.echo(f"{var:<11} {val or 'not set'}")
        ok &= bool(val)
    for tool in ("qcc", "q++", "ntox86_64-gcc", "ntoaarch64-gcc"):
        typer.echo(f"{tool:<15} {shutil.which(tool) or 'not found'}")
    if not ok:
        typer.echo("\nSource the SDP environment first, for example:\n  source ~/qnx800/qnxsdp-env.sh")
        raise typer.Exit(1)


@app.callback(invoke_without_command=True)
def main(version: bool = typer.Option(False, "--version", help="Print the version and exit.")):
    if version:
        typer.echo(f"qpa {__version__}")
        raise typer.Exit()


if __name__ == "__main__":
    sys.exit(app())
