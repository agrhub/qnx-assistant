/*
 * libqlinux: small Linux/glibc extensions for QNX.
 *
 * Two ways to use it:
 *   - #include it after the system socket/unistd headers; or
 *   - force-include it for a whole build with
 *       -DQLINUX_FORCE_INCLUDE -include qlinux/compat.h
 *     In that mode it includes no system header at all, so it cannot fix the
 *     libc feature macros (_GNU_SOURCE, ...) before the program sets its own.
 *
 * Each replacement is only mapped when the platform does not already provide
 * the call: define QLINUX_HAVE_ACCEPT4, QLINUX_HAVE_PIPE2 or QLINUX_HAVE_DUP3
 * when it does (qpa probes the target for these).
 */
#ifndef QLINUX_COMPAT_H
#define QLINUX_COMPAT_H

#ifdef __cplusplus
extern "C" {
#endif

#ifdef QLINUX_FORCE_INCLUDE

struct sockaddr;
/* socklen_t is a 32-bit unsigned int on both QNX and glibc */
int qlinux_accept4(int fd, struct sockaddr *addr, unsigned int *len, int flags);
int qlinux_pipe2(int fds[2], int flags);
int qlinux_dup3(int oldfd, int newfd, int flags);

#else

#include <fcntl.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <unistd.h>

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

#if !defined(QLINUX_NO_RENAME) && defined(QLINUX_SOCK_FLAGS_EMULATED)
#define socket qlinux_socket
#endif

#endif /* QLINUX_FORCE_INCLUDE */

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
#endif

#ifdef __cplusplus
}
#endif

#endif /* QLINUX_COMPAT_H */
