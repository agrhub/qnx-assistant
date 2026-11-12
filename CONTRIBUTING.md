# Contributing

## Commit rules

- One commit per feature or fix, with a clear subject and a short body that explains why. No "wip", "fix typo" or "update" commits: fold small follow-ups into the commit they belong to before pushing.
- Author and committer: `Tan Do <dmtan90@gmail.com>`.
- No tool or assistant attribution in commit messages, trailers or file contents.
- Before pushing: `python -m pytest tests` and `make -C libqlinux test` pass.

## Layout

| Path | What |
| --- | --- |
| `qpa/scanner.py`, `qpa/rules/*.yaml` | syntax-tree scan and the Linux → QNX rule set |
| `qpa/target.py`, `qpa/build.py` | QNX and emulate targets, compiler wrappers, build and error parsing |
| `qpa/fix.py`, `qpa/llm.py` | rule fixes and the build-checked repair loop |
| `qpa/port.py`, `qpa/runner.py`, `qpa/vm.py`, `qpa/report.py`, `qpa/cli.py` | `qpa port`, on-target tests, QNX VM, reports, CLI |
| `libqlinux/` | epoll / eventfd / accept4 / pipe2 / dup3 shim for QNX |
| `bench/` | benchmark projects (`projects.yaml`), runner, results |
| `docs/` | architecture, testing, codelab, Devpost text, video script, checklist |
| `scripts/qnx-e2e.sh` | end-to-end run on a QNX 8.0 VM |

## Next steps (hackathon deadline: 15 Dec 2026, 2:00 pm EST)

1. **First run on real QNX 8.0.** On an Ubuntu host with QNX SDP 8.0 and QEMU (KVM recommended):
   `source ~/qnx800/qnxsdp-env.sh && ./scripts/qnx-e2e.sh`.
   Fix what fails. Untested so far on a real SDP: the `mkqnximage --ssh-ident` argument form in `qpa/vm.py`, the SDP compiler names chosen in `qpa/target.py`, the CMake toolchain file, and libqlinux on QNX (its FIFO-based eventfd and `O_RDWR` FIFO open in particular).
2. **Verify rules.** For each rule proven by a QNX build, set `verified_on: qnx-8.0` in `qpa/rules/linux_api.yaml`. Re-check rules marked `confidence: unverified` (`accept4`, `inotify`, `prctl`, `sysinfo`, socket flags, `/proc` details).
3. **Benchmark on QNX.** `python bench/run.py --target qnx-x86_64` with `QPA_DEVICE` set. Commit `bench/results/qnx-x86_64.md`. mosquitto needs a cJSON built for QNX in the sysroot (or `find_package` pointed at one).
4. **Repair loop with a real model.** Set `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` and `QPA_MODEL`, then run the benchmark without `--no-ai`. Redis (11 errors on emulate) and linux-sysmon are the targets. Keep the transcripts in `bench/.work/<target>/<project>/ai/` for the video.
5. **Raspberry Pi 5.** `qpa port examples/linux-sysmon -t qnx-aarch64le -d root@<pi-ip>`.
6. **Update the docs with real numbers.** Use the QNX results in `README.md`, `docs/testing.md` and `docs/devpost-submission.md`, then go through `docs/submission-checklist.md`.
7. **Record the video** from `docs/video-script.md`, using real model output and no replay fixture.
