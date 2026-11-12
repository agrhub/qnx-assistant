#!/usr/bin/env python3
"""Run `qpa port` over the benchmark projects and tabulate the results.

    python bench/run.py                       # all projects, emulate target
    python bench/run.py --only inih libyaml
    python bench/run.py --target qnx-x86_64   # with the QNX SDP sourced and QPA_DEVICE set

Results go to bench/results/<target>.json and bench/results/<target>.md.
A language model is used when ANTHROPIC_API_KEY / OPENAI_API_KEY and QPA_MODEL are set.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from qpa.llm import get_provider  # noqa: E402
from qpa.port import port  # noqa: E402
from qpa.rules import load  # noqa: E402
from qpa.runner import device_from_env  # noqa: E402
from qpa.scanner import Scanner  # noqa: E402


def fetch(p: dict, cache: Path) -> Path:
    if "path" in p:
        return ROOT / p["path"]
    d = cache / p["name"]
    if not d.exists():
        subprocess.run(["git", "clone", "-q", "--depth", "1", p["url"], str(d)], check=True)
    ref = p.get("ref")
    if ref and subprocess.run(["git", "-C", str(d), "rev-parse", "HEAD"], capture_output=True,
                              text=True).stdout.strip() != ref:
        subprocess.run(["git", "-C", str(d), "fetch", "-q", "--depth", "1", "origin", ref], check=True)
        subprocess.run(["git", "-C", str(d), "checkout", "-q", ref], check=True)
    return d


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default="emulate")
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--cache", type=Path, default=ROOT / "bench" / ".cache")
    ap.add_argument("--work", type=Path, default=ROOT / "bench" / ".work")
    ap.add_argument("--max-rounds", type=int, default=6)
    ap.add_argument("--no-ai", action="store_true")
    args = ap.parse_args()

    rules = load()
    provider = None if args.no_ai else get_provider()
    device = device_from_env()
    projects = yaml.safe_load((ROOT / "bench" / "projects.yaml").read_text())["projects"]
    args.cache.mkdir(parents=True, exist_ok=True)
    rows = []
    for p in projects:
        if args.only and p["name"] not in args.only:
            continue
        print(f"== {p['name']}", flush=True)
        src = fetch(p, args.cache)
        work = args.work / args.target / p["name"]
        cfg_path = None
        if p.get("qpa"):
            cfg_path = args.work / args.target / f"{p['name']}.qpa.yaml"
            cfg_path.parent.mkdir(parents=True, exist_ok=True)
            cfg_path.write_text(yaml.safe_dump(p["qpa"]))
        scan = Scanner(rules).scan(src)
        t0 = time.monotonic()
        try:
            res = port(src, work, rules, target_name=args.target, provider=provider, max_rounds=args.max_rounds,
                       device=device, config_path=cfg_path, title=p["name"])
            r = res.__dict__
            row = {
                "project": p["name"], "tier": p["tier"], "files": scan.files, "lines": scan.lines,
                "open_before": sum(v for k, v in res.findings_before.items() if k != "review"),
                "open_after": sum(v for k, v in res.findings_after.items() if k != "review"),
                "hard_blocker_after": res.findings_after["hard"] + res.findings_after["blocker"],
                "rule_fixes": sum(1 for c in r["changes"] if c["origin"].startswith("rule")),
                "ai_rounds": len(r["rounds"]), "ai_kept": sum(1 for x in r["rounds"] if x.get("accepted")),
                "build": "pass" if res.build_ok else "fail", "errors_left": r["build"]["error_count"],
                "test": ("pass" if r["test"]["ok"] else "fail") if r["test"] and r["test"]["ran"] else "not run",
                "seconds": round(time.monotonic() - t0, 1), "notes": r["notes"],
            }
        except Exception as e:  # keep going: one broken project must not stop the run
            row = {"project": p["name"], "tier": p["tier"], "files": scan.files, "lines": scan.lines,
                   "build": "error", "test": "not run", "error": str(e)[:300], "seconds": round(time.monotonic() - t0, 1)}
        print("   ", {k: row.get(k) for k in ("build", "test", "rule_fixes", "ai_kept", "errors_left", "seconds")},
              flush=True)
        rows.append(row)

    out = ROOT / "bench" / "results"
    out.mkdir(exist_ok=True)
    meta = {"target": args.target, "date": dt.date.today().isoformat(), "ai": provider.name if provider else "off"}
    (out / f"{args.target}.json").write_text(json.dumps({"meta": meta, "projects": rows}, indent=2))
    lines = [f"# Benchmark: target `{args.target}`, AI {meta['ai']}, {meta['date']}", "",
             "| Project | Tier | Lines | Open findings before → after | Rule fixes | AI rounds kept | Build | Tests | Time |",
             "| --- | --- | ---: | --- | ---: | --- | --- | --- | ---: |"]
    for r in rows:
        lines.append(f"| {r['project']} | {r['tier']} | {r['lines']:,} | {r.get('open_before', '–')} → "
                     f"{r.get('open_after', '–')} | {r.get('rule_fixes', '–')} | {r.get('ai_kept', 0)}/"
                     f"{r.get('ai_rounds', 0)} | {r['build']}"
                     + (f" ({r['errors_left']} errors)" if r.get("errors_left") else "")
                     + f" | {r['test']} | {r['seconds']}s |")
    (out / f"{args.target}.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
