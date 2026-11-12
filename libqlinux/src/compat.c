/* libqlinux: accept4/pipe2/dup3 and SOCK_* type flags through fcntl(). */
#define QLINUX_NO_RENAME
#include "compat.h"

#include <errno.h>

static int apply(int fd, int nonblock, int cloexec)
{
	if (nonblock) {
		int fl = fcntl(fd, F_GETFL);
		if (fl < 0 || fcntl(fd, F_SETFL, fl | O_NONBLOCK) < 0)
			return -1;
	}
	if (cloexec && fcntl(fd, F_SETFD, FD_CLOEXEC) < 0)
		return -1;
	return 0;
}

static int close_keep_errno(int fd)
{
	int e = errno;
	close(fd);
	errno = e;
	return -1;
}

int qlinux_accept4(int fd, struct sockaddr *addr, socklen_t *len, int flags)
{
	if (flags & ~(SOCK_NONBLOCK | SOCK_CLOEXEC)) {
		errno = EINVAL;
		return -1;
	}
	int c = accept(fd, addr, len);
	if (c < 0)
		return -1;
	if (apply(c, flags & SOCK_NONBLOCK, flags & SOCK_CLOEXEC) < 0)
		return close_keep_errno(c);
	return c;
}

int qlinux_pipe2(int fds[2], int flags)
{
	if (flags & ~(O_NONBLOCK | O_CLOEXEC)) {
		errno = EINVAL;
		return -1;
	}
	if (pipe(fds) < 0)
		return -1;
	for (int i = 0; i < 2; i++) {
		if (apply(fds[i], flags & O_NONBLOCK, flags & O_CLOEXEC) < 0) {
			int e = errno;
			close(fds[0]);
			close(fds[1]);
			errno = e;
			return -1;
		}
	}
	return 0;
}

int qlinux_dup3(int oldfd, int newfd, int flags)
{
	if (oldfd == newfd || (flags & ~O_CLOEXEC)) {
		errno = EINVAL;
		return -1;
	}
	if (dup2(oldfd, newfd) < 0)
		return -1;
	if (apply(newfd, 0, flags & O_CLOEXEC) < 0)
		return close_keep_errno(newfd);
	return newfd;
}

int qlinux_socket(int domain, int type, int protocol)
{
	int nonblock = type & SOCK_NONBLOCK, cloexec = type & SOCK_CLOEXEC;
#ifdef QLINUX_SOCK_FLAGS_EMULATED
	type &= ~(SOCK_NONBLOCK | SOCK_CLOEXEC);
#endif
	int s = socket(domain, type, protocol);
	if (s < 0)
		return -1;
#ifdef QLINUX_SOCK_FLAGS_EMULATED
	if (apply(s, nonblock, cloexec) < 0)
		return close_keep_errno(s);
#else
	(void)nonblock;
	(void)cloexec;
#endif
	return s;
}
