/* libqlinux: eventfd on an anonymous read-write FIFO. See sys/eventfd.h. */
#include "sys/eventfd.h"

#include <errno.h>
#include <limits.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

/* Which descriptors were created with EFD_SEMAPHORE (eventfd_read semantics differ). */
static pthread_mutex_t g_mu = PTHREAD_MUTEX_INITIALIZER;
static unsigned char *g_sem;
static int g_cap;

static void remember_mode(int fd, int sem)
{
	pthread_mutex_lock(&g_mu);
	if (fd >= g_cap) {
		int cap = g_cap ? g_cap : 64;
		while (cap <= fd)
			cap *= 2;
		unsigned char *t = realloc(g_sem, (size_t)cap);
		if (t) {
			memset(t + g_cap, 0, (size_t)(cap - g_cap));
			g_sem = t;
			g_cap = cap;
		}
	}
	if (fd < g_cap)
		g_sem[fd] = (unsigned char)sem;
	pthread_mutex_unlock(&g_mu);
}

static int is_sem(int fd)
{
	pthread_mutex_lock(&g_mu);
	int s = fd >= 0 && fd < g_cap && g_sem[fd];
	pthread_mutex_unlock(&g_mu);
	return s;
}

static int put(int fd, eventfd_t v)
{
	ssize_t r = write(fd, &v, sizeof v);
	return r == (ssize_t)sizeof v ? 0 : -1;
}

int qlinux_eventfd(unsigned int initval, int flags)
{
	if (flags & ~(EFD_SEMAPHORE | EFD_CLOEXEC | EFD_NONBLOCK)) {
		errno = EINVAL;
		return -1;
	}
	const char *tmp = getenv("TMPDIR");
	char dir[PATH_MAX - 16], path[PATH_MAX];
	snprintf(dir, sizeof dir, "%s/qlinux-efd-XXXXXX", tmp && *tmp ? tmp : "/tmp");
	if (!mkdtemp(dir))
		return -1;
	snprintf(path, sizeof path, "%s/fifo", dir);
	int fd = -1, err = 0;
	if (mkfifo(path, 0600) == 0) {
		fd = open(path, O_RDWR | O_NONBLOCK | (flags & EFD_CLOEXEC ? O_CLOEXEC : 0));
		err = errno;
		unlink(path);
	} else {
		err = errno;
	}
	rmdir(dir);
	if (fd < 0) {
		errno = err;
		return -1;
	}

	int sem = flags & EFD_SEMAPHORE;
	for (unsigned int i = 0; i < (sem ? initval : (initval ? 1u : 0u)); i++) {
		if (put(fd, sem ? 1 : initval) < 0) {
			err = errno;
			close(fd);
			errno = err;
			return -1;
		}
	}
	if (!(flags & EFD_NONBLOCK)) {
		int fl = fcntl(fd, F_GETFL);
		fcntl(fd, F_SETFL, fl & ~O_NONBLOCK);
	}
	remember_mode(fd, sem);
	return fd;
}

int qlinux_eventfd_write(int fd, eventfd_t value)
{
	if (value == UINT64_MAX) {
		errno = EINVAL;
		return -1;
	}
	if (is_sem(fd)) { /* a semaphore counts units: one message per unit */
		for (eventfd_t i = 0; i < value; i++)
			if (put(fd, 1) < 0)
				return -1;
		return 0;
	}
	return put(fd, value);
}

int qlinux_eventfd_read(int fd, eventfd_t *value)
{
	eventfd_t v;
	if (read(fd, &v, sizeof v) != (ssize_t)sizeof v)
		return -1;
	if (is_sem(fd)) {
		*value = 1;
		return 0;
	}
	/* Counter mode: take every pending write, as Linux returns the whole count. */
	int fl = fcntl(fd, F_GETFL);
	if (fl >= 0 && !(fl & O_NONBLOCK))
		fcntl(fd, F_SETFL, fl | O_NONBLOCK);
	eventfd_t more;
	while (read(fd, &more, sizeof more) == (ssize_t)sizeof more)
		v += more;
	if (fl >= 0 && !(fl & O_NONBLOCK))
		fcntl(fd, F_SETFL, fl);
	*value = v;
	return 0;
}
