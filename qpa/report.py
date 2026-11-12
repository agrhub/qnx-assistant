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


def _diff_html(diff: str) -> str:
    out = []
    for line in diff.splitlines():
        cls = ("add" if line.startswith("+") and not line.startswith("+++") else
               "del" if line.startswith("-") and not line.startswith("---") else
               "hunk" if line.startswith("@@") else "")
        out.append(f'<span class="{cls}">{html.escape(line)}</span>' if cls else html.escape(line))
    return "\n".join(out)


def _status(ok: bool | None, yes: str = "pass", no: str = "fail") -> str:
    if ok is None:
        return '<span class="st none">not run</span>'
    return f'<span class="st {"ok" if ok else "bad"}">{yes if ok else no}</span>'


def _port_section(port: dict) -> str:
    e = html.escape
    b, t = port["build"], port.get("test")
    rule_n = sum(1 for c in port["changes"] if c["origin"].startswith("rule"))
    ai_n = sum(1 for c in port["changes"] if c["origin"] == "ai")
    accepted = sum(1 for r in port["rounds"] if r.get("accepted"))
    phases = " · ".join(f"{k} {v}s" for k, v in port["phases"].items())
    tiles = f"""
<div class="cards port">
  <div class="card"><div class="k">Build for {e(port['target'])}</div><div class="n">{_status(b['ok'])}</div>
    <div class="h">{e(b['system'])}, {b['attempts']} attempt(s){'' if b['ok'] else ', ' + str(b['error_count']) + ' error(s) left'}</div></div>
  <div class="card"><div class="k">Tests</div><div class="n">{_status(t['ok'] if t and t.get('ran') else None)}</div>
    <div class="h">{e(t['where']) + ', ' + str(t['seconds']) + 's' if t else 'no test run'}</div></div>
  <div class="card"><div class="k">Rule fixes</div><div class="n">{rule_n}</div><div class="h">files changed mechanically</div></div>
  <div class="card"><div class="k">AI repairs</div><div class="n">{ai_n}</div>
    <div class="h">{accepted} of {len(port['rounds'])} round(s) kept by the compiler</div></div>
</div>
<p class="meta">{e(phases)}</p>"""
    notes = "".join(f"<li>{e(n)}</li>" for n in port.get("notes", []))
    changes = "".join(f"""
<details class="rule"><summary><span class="pill {'ai' if c['origin'] == 'ai' else 'rulefix'}">{'AI' if c['origin'] == 'ai' else 'rule'}</span>
<span class="t">{e(c['file'])}</span><span class="cnt">{e(c['reason'])}</span></summary>
<div class="body"><pre class="diff">{_diff_html(c['diff'])}</pre></div></details>""" for c in port["changes"])
    rounds = "".join(
        f"<tr><td>{r['round']}</td><td>{r.get('errors_before', '')}</td><td>{r.get('errors_after', '–')}</td>"
        f"<td>{r.get('applied', 0)}</td><td>{'kept' if r.get('accepted') else 'reverted' if r.get('applied') else 'no edit'}</td>"
        f"<td>{e(r.get('notes') or r.get('error') or '')}</td></tr>" for r in port["rounds"])
    left = ""
    if not b["ok"]:
        errs = "".join(f"<tr><td class='loc'>{e(x['file'])}:{x['line']}</td><td><code>{e(x['message'])}</code></td></tr>"
                       for x in b["errors"][:30])
        left = f"<h2>Errors left</h2><table class='occ'>{errs}</table>"
    test_out = f"<h2>Test output</h2><pre class='log'>{e(t['output'][-6000:])}</pre>" if t and t.get("output") else ""
    before, after = port["findings_before"], port["findings_after"]
    trend = " · ".join(f"{LEVEL_LABEL[lv]} {before.get(lv, 0)} → {after.get(lv, 0)}" for lv in LEVELS)
    return f"""{tiles}
{('<ul class="notes">' + notes + '</ul>') if notes else ''}
<p class="muted">Open findings before → after the port: {e(trend)}. Code behind a Linux <code>#if</code> and calls
covered by libqlinux are not counted. What is left is mostly launched commands and runtime paths
(<code>/proc</code>, <code>/sys</code>) that no compiler can see; check them on the target.</p>
<h2>Changes ({len(port['changes'])})</h2>
<p class="muted">Also saved as <code>qnx-port.patch</code>; apply it to the original tree with <code>git apply</code>.</p>
{changes or '<p>No source changes were needed.</p>'}
{('<h2>AI repair rounds</h2><table class="occ"><tr><th>Round</th><th>Errors before</th><th>after</th><th>Edits</th><th>Result</th><th>Notes</th></tr>' + rounds + '</table>') if rounds else ''}
{left}{test_out}"""


def write_html(res: ScanResult, rules: RuleSet, path: Path, title: str | None = None,
               port: dict | None = None) -> None:
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
.st {{ font-size:20px; font-weight:700 }} .st.ok {{ color:var(--easy) }} .st.bad {{ color:var(--blocker) }} .st.none {{ color:var(--muted) }}
.cards.port .card {{ border-top-color:var(--line) }}
.pill.ai {{ background:#6941c6 }} .pill.rulefix {{ background:var(--review) }}
pre.diff, pre.log {{ font:12.5px/1.45 ui-monospace,SFMono-Regular,Menlo,monospace; overflow:auto; background:var(--bg);
  border:1px solid var(--line); border-radius:6px; padding:10px; margin:10px 0 }}
pre.diff .add {{ color:var(--easy) }} pre.diff .del {{ color:var(--blocker) }} pre.diff .hunk {{ color:var(--muted) }}
ul.notes {{ color:var(--medium) }} table.occ th {{ text-align:left; font-size:12px; color:var(--muted); padding:4px 8px }}
</style></head>
<body><main>
<h1>QNX port report: {e(name)}</h1>
{_port_section(port) if port else ''}
{'<h2>Porting plan (scan of the original code)</h2>' if port else ''}
<div class="meta">{s['files']} source files · {s['lines']:,} lines · {s['files_with_findings']} files need changes · target {e(s['target'])} · {e(s['tool'])} · {e(s['generated'])}</div>
<div class="cards">{cards}</div>
{'' if port else '<h2>Porting plan</h2>'}
<p class="muted">One row per issue type, hardest first. Open a row to see every place in the code.</p>
{''.join(rows) or '<p>No Linux-specific code found.</p>'}
<p class="muted" style="margin-top:24px">{s['parse_warnings']} file(s) contain syntax the parser could not fully read (often heavy macros); findings there may be incomplete.</p>
</main></body></html>"""
    path.write_text(doc)
