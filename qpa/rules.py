"""Load the Linux -> QNX rule set (YAML) into lookup tables for the scanner."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

RULES_DIR = Path(__file__).parent / "rules"
LEVELS = ["blocker", "hard", "medium", "easy", "review"]


@dataclass
class Rule:
    id: str
    title: str
    level: str
    qnx: str
    fix: str = "report"
    confidence: str = "unverified"
    shim: str | None = None
    verified_on: str | None = None
    calls: list[str] = field(default_factory=list)
    call_prefixes: list[str] = field(default_factory=list)
    includes: list[str] = field(default_factory=list)
    identifiers: list[str] = field(default_factory=list)
    paths: list[str] = field(default_factory=list)


@dataclass
class RuleSet:
    rules: dict[str, Rule]
    calls: dict[str, str]          # function name -> rule id
    call_prefixes: list[tuple[str, str]]
    identifiers: dict[str, str]    # identifier -> rule id
    includes_exact: dict[str, str]
    includes_prefix: list[tuple[str, str]]
    paths: list[tuple[str, str]]   # (prefix, rule id), longest first
    commands: dict[str, str]       # command name -> rule id
    wrappers: set[str]

    def match_call(self, name: str) -> str | None:
        rid = self.calls.get(name)
        if rid:
            return rid
        for prefix, rid in self.call_prefixes:
            if name.startswith(prefix):
                return rid
        return None

    def match_include(self, header: str) -> str | None:
        if header in self.includes_exact:
            return self.includes_exact[header]
        for prefix, rid in self.includes_prefix:
            if header.startswith(prefix):
                return rid
        return None

    def match_path(self, literal: str) -> str | None:
        for prefix, rid in self.paths:
            if literal.startswith(prefix):
                return rid
        return None


def load(rules_dir: Path = RULES_DIR) -> RuleSet:
    rules: dict[str, Rule] = {}
    calls: dict[str, str] = {}
    call_prefixes: list[tuple[str, str]] = []
    idents: dict[str, str] = {}
    inc_exact: dict[str, str] = {}
    inc_prefix: list[tuple[str, str]] = []
    paths: list[tuple[str, str]] = []

    for item in yaml.safe_load((rules_dir / "linux_api.yaml").read_text()):
        m = item.get("match", {})
        r = Rule(
            id=item["id"], title=item["title"], level=item["level"], qnx=item["qnx"],
            fix=item.get("fix", "report"), confidence=item.get("confidence", "unverified"),
            shim=item.get("shim"), verified_on=item.get("verified_on"),
            calls=m.get("calls", []), call_prefixes=m.get("call_prefixes", []), includes=m.get("includes", []),
            identifiers=m.get("identifiers", []), paths=m.get("paths", []),
        )
        if r.level not in LEVELS:
            raise ValueError(f"rule {r.id}: unknown level {r.level}")
        rules[r.id] = r
        for c in r.calls:
            calls[c] = r.id
        for c in r.call_prefixes:
            call_prefixes.append((c, r.id))
        for i in r.identifiers:
            idents[i] = r.id
        for h in r.includes:
            if h.endswith("*"):
                inc_prefix.append((h[:-1], r.id))
            else:
                inc_exact[h] = r.id
        for p in r.paths:
            paths.append((p, r.id))
    paths.sort(key=lambda t: -len(t[0]))

    cmd_doc = yaml.safe_load((rules_dir / "commands.yaml").read_text())
    commands: dict[str, str] = {}
    for n, group in enumerate(cmd_doc["commands"]):
        rid = f"cmd-{group['names'][0]}"
        rules[rid] = Rule(
            id=rid, title="command: " + ", ".join(group["names"]), level=group["level"],
            qnx=group["qnx"], fix="report" if group["level"] in ("hard", "blocker") else "ai",
            confidence="high",
        )
        for name in group["names"]:
            commands[name] = rid
    rules["cmd-other"] = Rule(
        id="cmd-other", title="other external commands", level="review",
        qnx="confirm each command exists on the QNX target image", fix="report", confidence="high",
    )

    return RuleSet(rules, calls, call_prefixes, idents, inc_exact, inc_prefix, paths, commands,
                   set(cmd_doc.get("wrappers", [])))
