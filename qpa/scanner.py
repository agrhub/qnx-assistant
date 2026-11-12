"""Find Linux-specific code in a C/C++ tree by walking its syntax tree.

Working on the syntax tree (tree-sitter) instead of plain text means:
  * comments and string contents are never mistaken for API calls,
  * an external command is only reported where a program actually launches it
    (system/popen/exec*, a NULL-terminated argv array, or a run("cmd", ...) style
    wrapper), so a JSON key such as "ip" is not taken for the `ip` command,
  * code already behind `#ifdef __linux__` (or HAVE_EPOLL, ...) is marked as
    guarded: it usually needs a QNX branch or a build option, not a rewrite.
"""
from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

import tree_sitter_c
import tree_sitter_cpp
from tree_sitter import Language, Node, Parser

from .rules import LEVELS, RuleSet

C_EXT = {".c", ".h"}
CPP_EXT = {".cc", ".cpp", ".cxx", ".hpp", ".hh", ".hxx", ".inl"}
DEFAULT_EXCLUDES = {".git", "node_modules", "third_party", "thirdparty", "3rdparty", "vendor",
                    "build", "out", "dist", ".venv", "venv", "__pycache__"}

LAUNCH_SHELL = {"system", "popen"}
LAUNCH_EXEC = {"execl", "execlp", "execle", "execv", "execvp", "execve", "execvpe", "posix_spawnp"}
LAUNCHER_NAME = re.compile(r"exec|spawn|run|launch|cmd|command|shell|popen|system", re.I)
COMMAND_WORD = re.compile(r"^[A-Za-z0-9_./+-]*[A-Za-z][A-Za-z0-9_./+-]*$")
NOT_A_WRAPPER = re.compile(r"printf|puts|log|err|warn|str|mem|json|cJSON|add|set|get|cmp|equal", re.I)
PLATFORM_GUARD = re.compile(
    r"__linux__|__gnu_linux__|\blinux\b|\bLINUX\b|HAVE_(SYS_)?EPOLL|HAVE_EVENTFD|HAVE_INOTIFY|"
    r"HAVE_TIMERFD|HAVE_SIGNALFD|USE_EPOLL|WITH_EPOLL|HAVE_LINUX_\w+")

_C = Language(tree_sitter_c.language())
_CPP = Language(tree_sitter_cpp.language())


@dataclass
class Finding:
    rule: str
    file: str
    line: int
    kind: str           # call | include | identifier | path | command
    symbol: str
    snippet: str
    guard: str | None = None
    certainty: str = "certain"   # certain | likely


@dataclass
class ScanResult:
    root: str
    files: int = 0
    lines: int = 0
    parse_errors: list[str] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)

    def by_level(self, rules: RuleSet) -> dict[str, int]:
        out = {lv: 0 for lv in LEVELS}
        for f in self.findings:
            out[rules.rules[f.rule].level] += 1
        return out

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


def _text(node: Node) -> str:
    return node.text.decode("utf-8", "replace")


def _string_value(node: Node | None) -> str | None:
    """Value of a C string literal, a concatenation's leading literal, or a cast of one."""
    if node is None:
        return None
    if node.type == "cast_expression":
        return _string_value(node.child_by_field_name("value"))
    if node.type == "parenthesized_expression" and node.named_child_count == 1:
        return _string_value(node.named_children[0])
    if node.type == "concatenated_string":
        lits = [c for c in node.named_children if c.type == "string_literal"]
        return _string_value(lits[0]) if lits else None
    if node.type == "string_literal":
        return "".join(_text(c) for c in node.named_children if c.type in ("string_content", "escape_sequence"))
    return None


def _func_name(call: Node) -> str | None:
    fn = call.child_by_field_name("function")
    if fn is None:
        return None
    if fn.type == "identifier":
        return _text(fn)
    if fn.type == "qualified_identifier":
        name = fn.child_by_field_name("name")
        return _text(name) if name is not None else None
    return None


def _is_null(node: Node) -> bool:
    t = _text(node).strip()
    return node.type in ("null", "nullptr") or t in ("NULL", "nullptr", "0", "(char *)NULL", "(char *)0")


def _guard(node: Node) -> str | None:
    """Condition of an enclosing #if/#ifdef branch that already selects Linux."""
    child, parent = node, node.parent
    while parent is not None:
        if parent.type in ("preproc_if", "preproc_ifdef", "preproc_elif"):
            alt = parent.child_by_field_name("alternative")
            in_alt = alt is not None and alt.start_byte <= child.start_byte and child.end_byte <= alt.end_byte
            cond = parent.child_by_field_name("condition") or parent.child_by_field_name("name")
            cond_text = _text(cond) if cond is not None else ""
            negated = _text(parent).startswith("#ifndef") or cond_text.lstrip().startswith("!")
            if PLATFORM_GUARD.search(cond_text) and (in_alt == negated):
                return ("#ifndef " if negated else "#if ") + cond_text.strip()[:80]
        child, parent = parent, parent.parent
    return None


class Scanner:
    def __init__(self, rules: RuleSet, excludes: set[str] | None = None):
        self.rules = rules
        self.excludes = DEFAULT_EXCLUDES | (excludes or set())
        self._parsers = {"c": Parser(_C), "cpp": Parser(_CPP)}

    # ---------- files ----------
    def iter_files(self, root: Path):
        for d, dirs, files in os.walk(root):
            dirs[:] = sorted(x for x in dirs if x not in self.excludes)
            for f in sorted(files):
                ext = os.path.splitext(f)[1].lower()
                if ext in C_EXT or ext in CPP_EXT:
                    yield Path(d) / f

    def scan(self, root: Path) -> ScanResult:
        root = root.resolve()
        res = ScanResult(root=str(root))
        target = [root] if root.is_file() else self.iter_files(root)
        for path in target:
            self.scan_file(path, root if root.is_dir() else root.parent, res)
        res.findings.sort(key=lambda f: (LEVELS.index(self.rules.rules[f.rule].level), f.rule, f.file, f.line))
        return res

    def scan_file(self, path: Path, root: Path, res: ScanResult) -> None:
        src = path.read_bytes()
        lang = "cpp" if path.suffix.lower() in CPP_EXT else "c"
        tree = self._parsers[lang].parse(src)
        rel = str(path.relative_to(root))
        lines = src.decode("utf-8", "replace").splitlines()
        res.files += 1
        res.lines += len(lines)
        if tree.root_node.has_error:
            res.parse_errors.append(rel)
        seen: set[tuple] = set()

        def add(rule: str, node: Node, kind: str, symbol: str, certainty: str = "certain") -> None:
            line = node.start_point[0] + 1
            key = (rule, line, symbol)
            if key in seen:
                return
            seen.add(key)
            snippet = lines[line - 1].strip()[:160] if line - 1 < len(lines) else ""
            res.findings.append(Finding(rule, rel, line, kind, symbol, snippet, _guard(node), certainty))

        stack = [tree.root_node]
        while stack:
            n = stack.pop()
            t = n.type
            if t == "comment":
                continue
            if t == "preproc_include":
                p = n.child_by_field_name("path")
                if p is not None:
                    header = _text(p).strip("<>\"")
                    rid = self.rules.match_include(header)
                    if rid:
                        add(rid, n, "include", header)
            elif t == "call_expression":
                self._on_call(n, add)
            elif t == "initializer_list":
                self._on_argv(n, add)
            elif t in ("identifier", "type_identifier"):
                rid = self.rules.identifiers.get(_text(n))
                if rid:
                    add(rid, n, "identifier", _text(n))
            elif t in ("string_literal", "concatenated_string"):
                if not (t == "string_literal" and n.parent is not None and n.parent.type == "concatenated_string"):
                    val = _string_value(n)
                    if val:
                        rid = self.rules.match_path(val)
                        if rid:
                            add(rid, n, "path", val[:80])
                if t == "string_literal":
                    continue
            stack.extend(reversed(n.children))

    # ---------- calls and launched commands ----------
    def _command_rule(self, name: str) -> str:
        return self.rules.commands.get(os.path.basename(name), "cmd-other")

    def _resolve_wrapped(self, words: list[str]) -> str | None:
        """First real command in an argv, skipping timeout/sudo/nice and their options."""
        i = 0
        while i < len(words):
            w = os.path.basename(words[i])
            if w in self.rules.wrappers:
                i += 1
                while i < len(words) and (words[i].startswith("-") or words[i].replace(".", "").isdigit()
                                          or "=" in words[i]):
                    i += 1
                continue
            return w or None
        return None

    def _on_call(self, n: Node, add) -> None:
        name = _func_name(n)
        if not name:
            return
        rid = self.rules.match_call(name)
        if rid:
            add(rid, n, "call", name)
        args = n.child_by_field_name("arguments")
        argv = [a for a in args.named_children if a.type != "comment"] if args is not None else []
        if not argv:
            return
        if name in LAUNCH_SHELL:
            s = _string_value(argv[0])
            if s:
                cmd = self._resolve_wrapped(s.split())
                if cmd:
                    add(self._command_rule(cmd), n, "command", cmd)
            return
        if name in LAUNCH_EXEC:
            s = _string_value(argv[0])
            if s and not s.startswith("/proc/self"):
                add(self._command_rule(s), n, "command", os.path.basename(s))
            return
        # run("parted", ...) style wrappers: only trust names we know are commands
        if NOT_A_WRAPPER.search(name):
            return
        words = []
        for a in argv:
            v = _string_value(a)
            if v is None:
                break
            words.append(v)
        cmd = self._resolve_wrapped(words) if words else None
        if cmd and cmd in self.rules.commands:
            add(self.rules.commands[cmd], n, "command", cmd, "likely")

    def _on_argv(self, n: Node, add) -> None:
        items = [c for c in n.named_children if c.type != "comment"]
        if len(items) < 2 or not _is_null(items[-1]):
            return
        words = []
        for a in items[:-1]:
            v = _string_value(a)
            if v is None:
                break
            words.append(v)
        if not words:
            return
        cmd = self._resolve_wrapped(words)
        if not cmd or not COMMAND_WORD.match(cmd):
            return
        if cmd in self.rules.commands:
            add(self.rules.commands[cmd], n, "command", cmd)
            return
        # Any other NULL-terminated string list counts only when the array is handed to
        # something that launches a process; option tables and UI labels look the same.
        launcher = self._array_launcher(n)
        if launcher:
            certainty = "certain" if launcher in LAUNCH_EXEC or launcher.startswith("posix_spawn") else "likely"
            add("cmd-other", n, "command", cmd, certainty)

    @staticmethod
    def _array_launcher(init: Node) -> str | None:
        """Name of the call that launches a process with this argv array, if any."""
        decl = init.parent
        if decl is None or decl.type != "init_declarator":
            return None
        d = decl.child_by_field_name("declarator")
        while d is not None and d.type != "identifier":
            d = d.child_by_field_name("declarator")
        if d is None:
            return None
        name = _text(d)
        scope = decl
        while scope.parent is not None and scope.type not in ("function_definition", "translation_unit"):
            scope = scope.parent
        stack = [scope]
        while stack:
            x = stack.pop()
            if x.type == "call_expression" and x.start_byte > decl.end_byte:
                args = x.child_by_field_name("arguments")
                fn = _func_name(x)
                if fn and args is not None and any(
                        _text(a) == name or _text(a).startswith(name + "[") for a in args.named_children):
                    if fn in LAUNCH_EXEC or LAUNCHER_NAME.search(fn):
                        return fn
            stack.extend(x.named_children)
        return None
