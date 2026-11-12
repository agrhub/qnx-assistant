"""Per-project settings, read from qpa.yaml in the project root (all optional).

Example:

    build:
      system: cmake            # auto | cmake | autotools | make | custom
      cmake_args: [-DWITH_TLS=OFF]
      make_args: [-C, src]
      commands: []             # custom: shell commands run in the source tree
      env: {}                  # extra environment variables
    test:
      command: ./run-tests.sh  # run in the test directory on the target
      files: [build/test_*]    # copied to the target (globs, relative to the work tree)
      timeout: 300
    exclude: [docs, examples]
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class BuildConfig:
    system: str = "auto"
    cmake_args: list[str] = field(default_factory=list)
    configure_args: list[str] = field(default_factory=list)
    make_args: list[str] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    jobs: int = 0


@dataclass
class TestConfig:
    command: str | None = None
    files: list[str] = field(default_factory=list)
    timeout: int = 300


@dataclass
class ProjectConfig:
    build: BuildConfig = field(default_factory=BuildConfig)
    test: TestConfig = field(default_factory=TestConfig)
    exclude: list[str] = field(default_factory=list)


def load_config(project: Path, explicit: Path | None = None) -> ProjectConfig:
    path = explicit or (project / "qpa.yaml")
    if not path.is_file():
        return ProjectConfig()
    raw = yaml.safe_load(path.read_text()) or {}
    b = raw.get("build", {}) or {}
    t = raw.get("test", {}) or {}
    return ProjectConfig(
        build=BuildConfig(
            system=b.get("system", "auto"),
            cmake_args=list(b.get("cmake_args", [])),
            configure_args=list(b.get("configure_args", [])),
            make_args=list(b.get("make_args", [])),
            commands=list(b.get("commands", [])),
            env={k: str(v) for k, v in (b.get("env") or {}).items()},
            jobs=int(b.get("jobs", 0)),
        ),
        test=TestConfig(
            command=t.get("command"),
            files=list(t.get("files", [])),
            timeout=int(t.get("timeout", 300)),
        ),
        exclude=list(raw.get("exclude", [])),
    )
