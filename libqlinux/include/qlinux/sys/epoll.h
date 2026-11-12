/*
 * libqlinux: epoll for QNX, built on poll().
 *
 * Put libqlinux/include/qlinux on the include path so that an unchanged
 * `#include <sys/epoll.h>` resolves here, and link libqlinux.
 *
 * Differences from Linux (also in libqlinux/README.md):
 *   - EPOLLET is accepted but behaves level-triggered.
 *   - EPOLLEXCLUSIVE and EPOLLWAKEUP are accepted and ignored.
 *   - A file descriptor that is closed while registered is dropped at the next
 *     epoll_wait(), as on Linux, but only after poll() reports it invalid.
 *   - epoll_pwait() swaps the signal mask around poll(); this is not atomic.
 */
#ifndef QLINUX_SYS_EPOLL_H
#define QLINUX_SYS_EPOLL_H

#include <fcntl.h>
#include <signal.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define EPOLLIN      0x001u
#define EPOLLPRI     0x002u
#define EPOLLOUT     0x004u
#define EPOLLERR     0x008u
#define EPOLLHUP     0x010u
#define EPOLLRDNORM  0x040u
#define EPOLLRDBAND  0x080u
#define EPOLLWRNORM  0x100u
#define EPOLLWRBAND  0x200u
#define EPOLLMSG     0x400u
#define EPOLLRDHUP   0x2000u
#define EPOLLEXCLUSIVE (1u << 28)
#define EPOLLWAKEUP    (1u << 29)
#define EPOLLONESHOT   (1u << 30)
#define EPOLLET        (1u << 31)

#define EPOLL_CTL_ADD 1
#define EPOLL_CTL_DEL 2
#define EPOLL_CTL_MOD 3

#define EPOLL_CLOEXEC O_CLOEXEC

typedef union epoll_data {
	void *ptr;
	int fd;
	uint32_t u32;
	uint64_t u64;
} epoll_data_t;

struct epoll_event {
	uint32_t events;
	epoll_data_t data;
};

int qlinux_epoll_create(int size);
int qlinux_epoll_create1(int flags);
int qlinux_epoll_ctl(int epfd, int op, int fd, struct epoll_event *event);
int qlinux_epoll_wait(int epfd, struct epoll_event *events, int maxevents, int timeout);
int qlinux_epoll_pwait(int epfd, struct epoll_event *events, int maxevents, int timeout,
                       const sigset_t *sigmask);

#ifndef QLINUX_NO_RENAME
#define epoll_create  qlinux_epoll_create
#define epoll_create1 qlinux_epoll_create1
#define epoll_ctl     qlinux_epoll_ctl
#define epoll_wait    qlinux_epoll_wait
#define epoll_pwait   qlinux_epoll_pwait
#endif

#ifdef __cplusplus
}
#endif

#endif /* QLINUX_SYS_EPOLL_H */
