"""Repairs: deterministic rule fixes first, then a build-verified AI loop.

Rule fixes are syntax-tree edits for changes that are always the same
(statfs -> statvfs, CLOCK_BOOTTIME -> CLOCK_MONOTONIC, prctl(PR_SET_NAME) ->
pthread_setname_np). Code that sits behind a Linux #if is left alone: the QNX
build already takes the other branch.

The AI loop sends the compiler's errors, the code around them and the matching
rules to a language model and asks for exact search/replace edits. An edit is
kept only if the next build has fewer errors or clears the first one; otherwise
it is reverted and the model is told why. The compiler is the referee.
"""
from __future__ import annotations

import difflib
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from tree_sitter import Node

from .build import BuildResult, Builder, Diagnostic
from .llm import LLMError, Provider
from .rules import RuleSet
from .scanner import CPP_EXT, Finding, Scanner, _func_name, _guard, _text

CLOCKS = {"CLOCK_BOOTTIME": "CLOCK_MONOTONIC", "CLOCK_MONOTONIC_RAW": "CLOCK_MONOTONIC",
          "CLOCK_MONOTONIC_COARSE": "CLOCK_MONOTONIC", "CLOCK_REALTIME_COARSE": "CLOCK_REALTIME"}
STATFS = {"statfs": "statvfs", "fstatfs": "fstatvfs"}
STATFS_HEADERS = {"sys/vfs.h", "sys/statfs.h"}


@dataclass
class Change:
    file: str
    origin: str          # rule:<id> | ai
    reason: str
    diff: str
    round: int = 0


@dataclass
class RepairLog:
    rounds: list[dict] = field(default_factory=list)
    changes: list[Change] = field(default_factory=list)
    final: BuildResult | None = None
    ai_used: bool = False
    note: str = ""


def unified(path: str, before: str, after: str) -> str:
    return "".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                                        f"a/{path}", f"b/{path}"))


def _in_condition(node: Node) -> bool:
    p = node.parent
    while p is not None:
        if p.type in ("preproc_if", "preproc_ifdef", "preproc_elif"):
            cond = p.child_by_field_name("condition") or p.child_by_field_name("name")
            if cond is not None and cond.start_byte <= node.start_byte and node.end_byte <= cond.end_byte:
                return True
        p = p.parent
    return False


def _walk(node: Node):
    stack = [node]
    while stack:
        n = stack.pop()
        yield n
        stack.extend(reversed(n.children))


class RuleFixer:
    """Applies the rules marked `fix: auto` (plus prctl name calls) to a source tree."""

    def __init__(self, scanner: Scanner):
        self.scanner = scanner

    def _edits(self, root: Node, src: bytes) -> list[tuple[int, int, str, str]]:
        edits: list[tuple[int, int, str, str]] = []
        prctl_total = prctl_fixed = 0
        prctl_include = None
        for n in _walk(root):
            t = n.type
            if t == "identifier" and _text(n) in CLOCKS and not _in_condition(n) and not _guard(n, _text(n)):
                edits.append((n.start_byte, n.end_byte, CLOCKS[_text(n)], "clock-boottime"))
            elif t == "call_expression":
                name = _func_name(n)
                fn = n.child_by_field_name("function")
                if name in STATFS and not _guard(n, name):
                    edits.append((fn.start_byte, fn.end_byte, STATFS[name], "statfs"))
                elif name == "prctl":
                    prctl_total += 1
                    args = [a for a in n.child_by_field_name("arguments").named_children if a.type != "comment"]
                    if len(args) >= 2 and not _guard(n, "prctl"):
                        opt, val = _text(args[0]), _text(args[1])
                        if opt == "PR_SET_NAME":
                            edits.append((n.start_byte, n.end_byte,
                                          f"pthread_setname_np(pthread_self(), {val})", "prctl"))
                            prctl_fixed += 1
                        elif opt == "PR_GET_NAME":
                            edits.append((n.start_byte, n.end_byte,
                                          f"pthread_getname_np(pthread_self(), {val}, 16)", "prctl"))
                            prctl_fixed += 1
            elif t == "struct_specifier":
                name = n.child_by_field_name("name")
                if name is not None and _text(name) == "statfs" and not _guard(n, "statfs"):
                    edits.append((name.start_byte, name.end_byte, "statvfs", "statfs"))
            elif t == "preproc_include":
                p = n.child_by_field_name("path")
                header = _text(p).strip("<>\"") if p is not None else ""
                if header in STATFS_HEADERS and not _guard(n):
                    edits.append((p.start_byte, p.end_byte, "<sys/statvfs.h>", "statfs"))
                elif header == "sys/prctl.h":
                    prctl_include = p
        if prctl_include is not None and prctl_total and prctl_fixed == prctl_total and not _guard(prctl_include):
            edits.append((prctl_include.start_byte, prctl_include.end_byte, "<pthread.h>", "prctl"))
        return edits

    def apply(self, src_root: Path, findings: list[Finding]) -> list[Change]:
        targets = sorted({f.file for f in findings if f.rule in ("clock-boottime", "statfs", "prctl")})
        changes = []
        for rel in targets:
            path = src_root / rel
            data = path.read_bytes()
            lang = "cpp" if path.suffix.lower() in CPP_EXT else "c"
            tree = self.scanner._parsers[lang].parse(data)
            edits = self._edits(tree.root_node, data)
            if not edits:
                continue
            out = data
            for s, e, rep, _ in sorted(edits, key=lambda x: -x[0]):
                out = out[:s] + rep.encode() + out[e:]
            before, after = data.decode("utf-8", "replace"), out.decode("utf-8", "replace")
            path.write_bytes(out)
            rules = sorted({r for *_, r in edits})
            changes.append(Change(rel, "rule:" + ",".join(rules),
                                  f"{len(edits)} mechanical edit(s): {', '.join(rules)}", unified(rel, before, after)))
        return changes


SYSTEM_PROMPT = """You port C and C++ programs from Linux to QNX 8.0 (a POSIX RTOS).
You receive compiler errors from a build for QNX, the code around each error and porting notes.
Reply with ONLY a JSON object, no prose:
{"edits": [{"file": "<path as given>", "search": "<exact text copied from the file>",
            "replace": "<new text>", "reason": "<one line>"}],
 "notes": "<what still needs a human, if anything>"}
Rules:
- "search" must be copied exactly from the file and occur exactly once in it; keep it short but unique.
- Keep the Linux code path: wrap Linux-only code in `#ifdef __linux__` and put the QNX/POSIX version in
  `#else`, or replace it with portable POSIX code when that is equivalent.
- QNX-only APIs (ThreadCtl, <sys/neutrino.h>) go behind `#ifdef __QNX__` with a POSIX fallback in `#else`.
- epoll, eventfd, accept4, pipe2 and dup3 are already provided by a compatibility library: do not rewrite them.
- Do not delete functionality to make an error go away. If something cannot be ported, say so in "notes".
- Fix the root cause; do not silence errors with casts or by commenting code out."""


def _context(src: Path, errs: list[Diagnostic], budget: int = 24000) -> str:
    by_file: dict[str, list[int]] = {}
    for e in errs:
        if (src / e.file).is_file():
            by_file.setdefault(e.file, []).append(e.line)
    parts = []
    for f, lines in by_file.items():
        text = (src / f).read_text(errors="replace").splitlines()
        lo, hi = max(1, min(lines) - 30), min(len(text), max(lines) + 30)
        body = "\n".join(f"{i:5d} | {text[i - 1]}" for i in range(lo, hi + 1))
        parts.append(f"--- {f} (lines {lo}-{hi} of {len(text)})\n{body}")
    out = "\n\n".join(parts)
    return out[:budget]


def _hints(rules: RuleSet, findings: list[Finding], files: set[str]) -> str:
    seen = {}
    for f in findings:
        if f.file in files and f.rule not in seen:
            r = rules.rules[f.rule]
            seen[f.rule] = f"- {r.title}: on QNX use {r.qnx}"
    return "\n".join(seen.values()) or "- (no matching rules)"


def parse_reply(text: str) -> dict:
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    raw = m.group(1) if m else text[text.find("{"): text.rfind("}") + 1]
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise LLMError(f"reply is not JSON: {e}") from e
    if not isinstance(data.get("edits", []), list):
        raise LLMError("reply has no edits list")
    return data


def _better(old: BuildResult, new: BuildResult) -> bool:
    if new.ok:
        return True
    if new.step == "configure" and old.step == "build":
        return False
    first = old.errors[0].key if old.errors else None
    new_keys = {e.key for e in new.errors}
    return len(new.errors) < len(old.errors) or (len(new.errors) <= len(old.errors) and first not in new_keys)


def ai_repair(builder: Builder, src: Path, rules: RuleSet, findings: list[Finding], provider: Provider | None,
              max_rounds: int, transcript_dir: Path, first: BuildResult) -> RepairLog:
    log = RepairLog(final=first)
    current = first
    if current.ok:
        return log
    if provider is None:
        log.note = "no language model configured; set ANTHROPIC_API_KEY or OPENAI_API_KEY and QPA_MODEL"
        return log
    log.ai_used = True
    feedback: list[str] = []
    transcript_dir.mkdir(parents=True, exist_ok=True)
    for rnd in range(1, max_rounds + 1):
        errs = [e for e in current.errors if (src / e.file).is_file()][:12]
        if not errs:
            log.note = "remaining errors are not tied to a source file (configure or link step)"
            if current.errors:
                errs_text = "\n".join(e.message for e in current.errors[:5])
                log.note += f":\n{errs_text}"
            break
        files = {e.file for e in errs}
        prompt = (
            f"Target: QNX 8.0 ({builder.tc.target.name}); build system: {builder.system}.\n\n"
            "Compiler errors:\n" + "\n".join(f"{e.file}:{e.line}: {e.message}" for e in errs) +
            "\n\nPorting notes for these files:\n" + _hints(rules, findings, files) +
            ("\n\nPrevious attempts that did not help:\n" + "\n".join(feedback[-4:]) if feedback else "") +
            "\n\nCode:\n" + _context(src, errs))
        t0 = time.monotonic()
        entry = {"round": rnd, "errors_before": len(current.errors), "applied": 0, "accepted": False}
        (transcript_dir / f"round-{rnd:02d}-prompt.txt").write_text(prompt)
        try:
            reply = provider.complete(SYSTEM_PROMPT, prompt)
            (transcript_dir / f"round-{rnd:02d}-reply.txt").write_text(reply)
            data = parse_reply(reply)
        except LLMError as e:
            entry["error"] = str(e)
            log.rounds.append(entry)
            feedback.append(f"round {rnd}: the reply could not be used ({e})")
            continue

        originals: dict[str, str] = {}
        applied: list[tuple[str, str]] = []
        problems = []
        for ed in data.get("edits", []):
            f, search, rep = ed.get("file", ""), ed.get("search", ""), ed.get("replace", "")
            path = (src / f).resolve()
            if not str(path).startswith(str(src.resolve())) or not path.is_file() or not search:
                problems.append(f"{f}: unknown file or empty search")
                continue
            text = path.read_text(errors="replace")
            if text.count(search) != 1:
                problems.append(f"{f}: search text found {text.count(search)} times, needs exactly 1")
                continue
            originals.setdefault(f, text)
            path.write_text(text.replace(search, rep, 1))
            applied.append((f, ed.get("reason", "")))
        entry["applied"] = len(applied)
        entry["notes"] = data.get("notes", "")
        if not applied:
            entry["problems"] = problems
            log.rounds.append(entry)
            feedback.append(f"round {rnd}: no edit applied ({'; '.join(problems) or 'empty edits'})")
            continue

        new = builder.build()
        entry["errors_after"] = 0 if new.ok else len(new.errors)
        entry["seconds"] = round(time.monotonic() - t0, 1)
        if _better(current, new):
            entry["accepted"] = True
            reasons = {}
            for f, why in applied:
                reasons.setdefault(f, []).append(why)
            for f, before in originals.items():
                after = (src / f).read_text(errors="replace")
                log.changes.append(Change(f, "ai", "; ".join(r for r in reasons[f] if r) or "AI repair",
                                          unified(f, before, after), rnd))
            current = new
        else:
            for f, before in originals.items():
                (src / f).write_text(before)
            first_err = current.errors[0] if current.errors else None
            feedback.append(
                f"round {rnd}: edits to {', '.join(sorted(originals))} were reverted because the build got no "
                f"better ({len(current.errors)} -> {len(new.errors)} errors"
                + (f"; still failing at {first_err.file}:{first_err.line}" if first_err else "") + ")")
        log.rounds.append(entry)
        if current.ok:
            break
    if not current.ok and log.ai_used and builder.attempt and log.rounds and not log.rounds[-1].get("accepted"):
        current = builder.build()   # make sure logs reflect the files as they are now
    log.final = current
    return log
