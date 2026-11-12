/*
 * libqlinux: small Linux/glibc extensions for QNX.
 *
 * Include this after the system socket/unistd headers, or force-include it
 * with `-include qlinux/compat.h`. Each replacement is only mapped when the
 * platform does not already provide the call: define QLINUX_HAVE_ACCEPT4,
 * QLINUX_HAVE_PIPE2 or QLINUX_HAVE_DUP3 when it does (the qpa build step
 * probes for these).
 */
#ifndef QLINUX_COMPAT_H
#define QLINUX_COMPAT_H

#include <fcntl.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <unistd.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Linux values; only used when the platform has no definition of its own. */
#ifndef SOCK_NONBLOCK
#define SOCK_NONBLOCK 0x00000800
#define QLINUX_SOCK_FLAGS_EMULATED 1
#endif
#ifndef SOCK_CLOEXEC
#define SOCK_CLOEXEC 0x00080000
#define QLINUX_SOCK_FLAGS_EMULATED 1
#endif

int qlinux_accept4(int fd, struct sockaddr *addr, socklen_t *len, int flags);
int qlinux_pipe2(int fds[2], int flags);
int qlinux_dup3(int oldfd, int newfd, int flags);
int qlinux_socket(int domain, int type, int protocol);

#ifndef QLINUX_NO_RENAME
#ifndef QLINUX_HAVE_ACCEPT4
#define accept4 qlinux_accept4
#endif
#ifndef QLINUX_HAVE_PIPE2
#define pipe2 qlinux_pipe2
#endif
#ifndef QLINUX_HAVE_DUP3
#define dup3 qlinux_dup3
#endif
#ifdef QLINUX_SOCK_FLAGS_EMULATED
#define socket qlinux_socket
#endif
#endif

#ifdef __cplusplus
}
#endif

#endif /* QLINUX_COMPAT_H */
