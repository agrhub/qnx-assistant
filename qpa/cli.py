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
