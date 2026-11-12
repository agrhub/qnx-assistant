# libqlinux

Drop-in replacements for Linux-only calls, so code that uses them builds on QNX 8.0 without source changes.

| Header | Provides | How |
| --- | --- | --- |
| `sys/epoll.h` | `epoll_create`, `epoll_create1`, `epoll_ctl`, `epoll_wait`, `epoll_pwait` | `poll()`; the epoll fd is a pipe that also wakes a blocked `epoll_wait()` when the interest list changes |
| `sys/eventfd.h` | `eventfd`, `eventfd_read`, `eventfd_write` | an anonymous FIFO opened read-write: one fd you can read, write, poll and close |
| `compat.h` | `accept4`, `pipe2`, `dup3`, `SOCK_NONBLOCK` / `SOCK_CLOEXEC` on `socket()` | the plain call followed by `fcntl()`, only where the platform lacks it |

## Use

```sh
make qnx ARCH=x86_64        # or ARCH=aarch64le for Raspberry Pi 5
```

Add `-I<path>/libqlinux/include/qlinux` so that `#include <sys/epoll.h>` and `<sys/eventfd.h>` resolve here, and link `build/qnx-<ARCH>/libqlinux.a`. For `compat.h`, add `-include qlinux/compat.h` (with `-I<path>/libqlinux/include`) and define `QLINUX_HAVE_ACCEPT4`, `QLINUX_HAVE_PIPE2` or `QLINUX_HAVE_DUP3` for calls the QNX libc already has.

## Known differences from Linux

- **epoll:** `EPOLLET` behaves level-triggered; `EPOLLEXCLUSIVE` and `EPOLLWAKEUP` are ignored. Polling the epoll fd itself does not report pending events. `epoll_pwait()` swaps the signal mask around `poll()`, which is not atomic.
- **eventfd:** a raw `read()` in counter mode returns one write's value instead of the sum (use `eventfd_read()`, or `EFD_SEMAPHORE`, for exact behaviour). Pending writes are limited by the FIFO buffer rather than a 64-bit counter.

## Tests

```sh
make test                    # host: checks the emulation logic (77 checks)
make qnx-test ARCH=x86_64    # QNX: copy build/qnx-x86_64/test_qlinux to the target and run it
```

Status: the tests pass on a Linux host, including under AddressSanitizer, UndefinedBehaviorSanitizer and ThreadSanitizer. They have not been run on a QNX 8.0 target yet.
