"""Write a scan as JSON (for tools/CI) and a self-contained HTML page (for people)."""
from __future__ import annotations

import datetime as dt
import html
import json
from collections import defaultdict
from pathlib import Path

from . import __version__
from .rules import LEVELS, RuleSet
from .scanner import ScanResult

LEVEL_LABEL = {"blocker": "Blocker", "hard": "Hard", "medium": "Medium", "easy": "Easy", "review": "Review"}
LEVEL_HELP = {
    "blocker": "no QNX equivalent: needs a different design",
    "hard": "rewrite against a QNX service or driver API",
    "medium": "local rewrite or the libqlinux shim",
    "easy": "mechanical change",
    "review": "check it exists on the target",
}
FIX_LABEL = {"auto": "auto-fix", "shim": "libqlinux shim", "ai": "AI rewrite + build check", "report": "redesign"}


def summarize(res: ScanResult, rules: RuleSet) -> dict:
    groups: dict[str, list] = defaultdict(list)
    for f in res.findings:
        groups[f.rule].append(f)
    plan = []
    for rid, fs in groups.items():
        r = rules.rules[rid]
        plan.append({
            "rule": rid, "title": r.title, "level": r.level, "fix": r.fix, "qnx": r.qnx,
            "confidence": r.confidence, "verified_on": r.verified_on, "shim": r.shim,
            "occurrences": len(fs), "files": len({f.file for f in fs}),
            "guarded": sum(1 for f in fs if f.guard),
            "symbols": sorted({f.symbol for f in fs}),
        })
    plan.sort(key=lambda p: (LEVELS.index(p["level"]), -p["occurrences"]))
    files_hit = len({f.file for f in res.findings})
    return {
        "tool": f"qpa {__version__}",
        "generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "target": "QNX SDP 8.0",
        "root": res.root,
        "files": res.files, "lines": res.lines, "files_with_findings": files_hit,
        "parse_warnings": len(res.parse_errors),
        "by_level": res.by_level(rules),
        "plan": plan,
    }


def write_json(res: ScanResult, rules: RuleSet, path: Path) -> None:
    data = summarize(res, rules)
    data["findings"] = [f.__dict__ for f in res.findings]
    data["parse_warning_files"] = res.parse_errors
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def write_html(res: ScanResult, rules: RuleSet, path: Path, title: str | None = None) -> None:
    s = summarize(res, rules)
    e = html.escape
    name = title or Path(res.root).name
    by_rule: dict[str, list] = defaultdict(list)
    for f in res.findings:
        by_rule[f.rule].append(f)

    cards = "".join(
        f'<div class="card lv-{lv}"><div class="n">{s["by_level"][lv]}</div>'
        f'<div class="k">{LEVEL_LABEL[lv]}</div><div class="h">{LEVEL_HELP[lv]}</div></div>'
        for lv in LEVELS)

    rows = []
    for p in s["plan"]:
        occ = by_rule[p["rule"]]
        items = "".join(
            f'<tr><td class="loc">{e(f.file)}:{f.line}</td><td><code>{e(f.snippet)}</code>'
            + (f'<div class="guard">already behind <code>{e(f.guard)}</code></div>' if f.guard else "")
            + ('<span class="likely">likely</span>' if f.certainty == "likely" else "")
            + "</td></tr>"
            for f in occ[:200])
        more = f'<p class="muted">… {len(occ) - 200} more in the JSON report</p>' if len(occ) > 200 else ""
        conf = ("verified on " + e(p["verified_on"])) if p["verified_on"] else e(p["confidence"])
        rows.append(f"""
<details class="rule lv-{p['level']}">
  <summary>
    <span class="pill lv-{p['level']}">{LEVEL_LABEL[p['level']]}</span>
    <span class="t">{e(p['title'])}</span>
    <span class="cnt">{p['occurrences']} in {p['files']} file{'s' if p['files'] != 1 else ''}</span>
    <span class="fix">{FIX_LABEL.get(p['fix'], p['fix'])}</span>
  </summary>
  <div class="body">
    <p><b>On QNX:</b> {e(p['qnx'])}</p>
    <p class="muted">Symbols: {e(', '.join(p['symbols']))} · confidence: {conf}
    {('· shim header <code>' + e(p['shim']) + '</code>') if p['shim'] else ''}
    {('· ' + str(p['guarded']) + ' already behind a Linux #if') if p['guarded'] else ''}</p>
    <table class="occ">{items}</table>{more}
  </div>
</details>""")

    doc = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>QNX port report – {e(name)}</title>
<style>
:root {{ --bg:#fbfaf7; --fg:#1d1d1b; --muted:#6b6a65; --line:#e4e1d8; --card:#ffffff;
  --blocker:#b42318; --hard:#c4320a; --medium:#b54708; --easy:#067647; --review:#475467; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#161614; --fg:#ecebe6; --muted:#a3a29b; --line:#2e2d29;
  --card:#1f1e1b; --blocker:#f97066; --hard:#fd853a; --medium:#fdb022; --easy:#47cd89; --review:#98a2b3; }} }}
* {{ box-sizing:border-box }}
body {{ margin:0; background:var(--bg); color:var(--fg); font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif }}
main {{ max-width:1080px; margin:0 auto; padding:32px 16px 64px }}
h1 {{ font-size:26px; margin:0 0 4px }} h2 {{ font-size:18px; margin:32px 0 12px }}
.muted {{ color:var(--muted) }} code {{ font:13px/1.4 ui-monospace,SFMono-Regular,Menlo,monospace }}
.meta {{ color:var(--muted); font-size:14px }}
.cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; margin-top:20px }}
.card {{ background:var(--card); border:1px solid var(--line); border-top:4px solid; border-radius:8px; padding:12px 14px }}
.card .n {{ font-size:28px; font-weight:700 }} .card .k {{ font-weight:600 }} .card .h {{ color:var(--muted); font-size:13px }}
.lv-blocker {{ border-top-color:var(--blocker) }} .lv-hard {{ border-top-color:var(--hard) }}
.lv-medium {{ border-top-color:var(--medium) }} .lv-easy {{ border-top-color:var(--easy) }} .lv-review {{ border-top-color:var(--review) }}
details.rule {{ background:var(--card); border:1px solid var(--line); border-radius:8px; margin:8px 0 }}
summary {{ cursor:pointer; padding:10px 14px; display:flex; gap:12px; align-items:center; flex-wrap:wrap; list-style:none }}
summary::-webkit-details-marker {{ display:none }}
.pill {{ font-size:12px; font-weight:700; padding:2px 8px; border-radius:999px; color:#fff }}
.pill.lv-blocker {{ background:var(--blocker) }} .pill.lv-hard {{ background:var(--hard) }} .pill.lv-medium {{ background:var(--medium) }}
.pill.lv-easy {{ background:var(--easy) }} .pill.lv-review {{ background:var(--review) }}
@media (prefers-color-scheme: dark) {{ .pill {{ color:#161614 }} }}
.t {{ font-weight:600; flex:1 1 220px }} .cnt, .fix {{ color:var(--muted); font-size:13px }}
.body {{ padding:0 14px 12px; border-top:1px solid var(--line) }}
table.occ {{ width:100%; border-collapse:collapse; font-size:13px }}
table.occ td {{ border-top:1px solid var(--line); padding:6px 8px; vertical-align:top }}
td.loc {{ white-space:nowrap; color:var(--muted); width:1% }}
table.occ code {{ white-space:pre-wrap; word-break:break-word }}
.guard {{ color:var(--easy); font-size:12px }} .likely {{ font-size:11px; color:var(--muted); margin-left:6px }}
@media (max-width:600px) {{ td.loc {{ white-space:normal }} }}
</style></head>
<body><main>
<h1>QNX port report: {e(name)}</h1>
<div class="meta">{s['files']} source files · {s['lines']:,} lines · {s['files_with_findings']} files need changes · target {e(s['target'])} · {e(s['tool'])} · {e(s['generated'])}</div>
<div class="cards">{cards}</div>
<h2>Porting plan</h2>
<p class="muted">One row per issue type, hardest first. Open a row to see every place in the code.</p>
{''.join(rows) or '<p>No Linux-specific code found.</p>'}
<p class="muted" style="margin-top:24px">{s['parse_warnings']} file(s) contain syntax the parser could not fully read (often heavy macros); findings there may be incomplete.</p>
</main></body></html>"""
    path.write_text(doc)
