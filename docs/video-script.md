# Demo video script (under 3:00)

Record at 1920×1080 with a large terminal font (18 pt or more). Use no third-party music or logos; the QNX name in commands and on screen is the platform being demonstrated. Upload to YouTube as Public.

| Time | Screen | Voice-over |
| --- | --- | --- |
| 0:00–0:15 | Title card: "QNX Port Assistant: Linux C/C++ to QNX 8.0, checked by the compiler". | "QNX 8.0 is free to build on. The software you want to bring with you is written for Linux. Porting it by hand means hunting for epoll, /proc, systemctl, one compiler error at a time." |
| 0:15–0:40 | `qpa scan bench/.cache/mosquitto` then the HTML report: level cards, open the epoll row (guarded by WITH_EPOLL), a command row. | "qpa reads the whole project on the syntax tree. Mosquitto: 116 thousand lines in about a second. Every Linux-only spot, sorted by how hard it is, with what to use on QNX. It knows the epoll code is already behind a build option, and it finds the commands a program launches, which no compiler will ever flag." |
| 0:40–1:30 | `eval "$(qpa vm up)"` (cut the boot wait), then `qpa port examples/linux-sysmon -t qnx-x86_64` running; the report: rule-fix diff, AI rounds table, test output from the VM. | "Now port a Linux service. Mechanical changes are made exactly: statfs to statvfs, CLOCK_BOOTTIME, prctl. epoll and eventfd keep working through our libqlinux shim. What is left goes to a language model, but the QNX compiler is the referee. An edit stays only if the next QNX build gets further. Then qpa copies the binary to a QNX 8.0 VM and runs the project's own test there. Pass." |
| 1:30–1:50 | `git apply qnx-port.patch` on the original, `cc` + `./sysmon --selftest` on Linux; show the `#ifdef __QNX__ ThreadCtl` hunk. | "One patch. Linux keeps working, QNX gets ThreadCtl for CPU affinity. Ready to send upstream." |
| 1:50–2:25 | `bench/results` table; `nm mosquitto \| grep qlinux_epoll`; mosquitto pub/sub passing on the target. | "On real projects: inih, libyaml, iperf3 and mosquitto pass with no source changes. Mosquitto's broker runs its event loop on our epoll shim and passes publish and subscribe. Redis needs the repair loop. htop is reported for what it is: a new platform backend." |
| 2:25–2:50 | The CamOS scan report (blocker: NPU SDK, hard: GStreamer, nmcli…). | "We built it for our own 67-thousand-line camera gateway. qpa showed us in a second what moves to QNX as is, what needs a redesign, and what would only have failed at run time." |
| 2:50–3:00 | Repo URL, codelab URL. | "qpa is open source. The codelab ports a Linux service to QNX in 30 minutes." |

Checklist before recording:
- Run `./scripts/qnx-e2e.sh` once so the VM image and benchmark results exist.
- Set `ANTHROPIC_API_KEY` (or `OPENAI_API_KEY`) and `QPA_MODEL` so the AI rounds are real model output. Do not use the replay fixture in the video.
- Clear the terminal; hide usernames, hostnames and API keys.
