/*
 * libqlinux: epoll emulation on poll().
 *
 * An epoll instance is the read end of a pipe. Its descriptor is what the
 * program gets back, so close() works as usual, and the pipe doubles as a
 * wake-up channel: epoll_ctl() writes a byte to it so that a thread already
 * blocked in epoll_wait() picks up the new interest list immediately.
 */
#include "sys/epoll.h"

#include <errno.h>
#include <poll.h>
#include <pthread.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

struct item {
	int fd;
	uint32_t events;
	epoll_data_t data;
	int disabled; /* EPOLLONESHOT fired, waiting for EPOLL_CTL_MOD */
};

struct inst {
	int rfd, wfd;       /* pipe: rfd is the epoll fd handed out */
	dev_t dev;
	ino_t ino;
	pthread_mutex_t mu;
	struct item *items;
	int n, cap;
	unsigned rot;       /* round-robin start so busy fds cannot starve others */
	int refs;
	int dead;
};

static pthread_mutex_t g_mu = PTHREAD_MUTEX_INITIALIZER;
static struct inst **g_tab;
static int g_cap;

static void inst_free(struct inst *in)
{
	close(in->wfd);
	pthread_mutex_destroy(&in->mu);
	free(in->items);
	free(in);
}

/* g_mu held. Drop table entries whose descriptor was closed or reused. */
static void drop_entry(int fd)
{
	struct inst *in = g_tab[fd];
	g_tab[fd] = NULL;
	in->dead = 1;
	if (in->refs == 0)
		inst_free(in);
}

static int still_ours(const struct inst *in)
{
	struct stat st;
	return fstat(in->rfd, &st) == 0 && st.st_dev == in->dev && st.st_ino == in->ino;
}

static void sweep(void)
{
	for (int i = 0; i < g_cap; i++)
		if (g_tab[i] && !still_ours(g_tab[i]))
			drop_entry(i);
}

static struct inst *inst_get(int epfd)
{
	struct inst *in = NULL;
	pthread_mutex_lock(&g_mu);
	if (epfd >= 0 && epfd < g_cap && g_tab[epfd]) {
		if (still_ours(g_tab[epfd])) {
			in = g_tab[epfd];
			in->refs++;
		} else {
			drop_entry(epfd);
		}
	}
	pthread_mutex_unlock(&g_mu);
	if (!in)
		errno = fcntl(epfd, F_GETFD) < 0 ? EBADF : EINVAL;
	return in;
}

static void inst_put(struct inst *in)
{
	pthread_mutex_lock(&g_mu);
	if (--in->refs == 0 && in->dead)
		inst_free(in);
	pthread_mutex_unlock(&g_mu);
}

static int set_fl(int fd, int cloexec)
{
	int fl = fcntl(fd, F_GETFL);
	if (fl < 0 || fcntl(fd, F_SETFL, fl | O_NONBLOCK) < 0)
		return -1;
	if (cloexec && fcntl(fd, F_SETFD, FD_CLOEXEC) < 0)
		return -1;
	return 0;
}

int qlinux_epoll_create1(int flags)
{
	if (flags & ~EPOLL_CLOEXEC) {
		errno = EINVAL;
		return -1;
	}
	int p[2];
	if (pipe(p) < 0)
		return -1;
	struct inst *in = calloc(1, sizeof *in);
	struct stat st;
	if (!in || set_fl(p[0], flags & EPOLL_CLOEXEC) < 0 || set_fl(p[1], 1) < 0 || fstat(p[0], &st) < 0) {
		int e = in ? errno : ENOMEM;
		free(in);
		close(p[0]);
		close(p[1]);
		errno = e;
		return -1;
	}
	in->rfd = p[0];
	in->wfd = p[1];
	in->dev = st.st_dev;
	in->ino = st.st_ino;
	pthread_mutex_init(&in->mu, NULL);

	pthread_mutex_lock(&g_mu);
	sweep();
	if (p[0] >= g_cap) {
		int cap = g_cap ? g_cap : 64;
		while (cap <= p[0])
			cap *= 2;
		struct inst **t = realloc(g_tab, (size_t)cap * sizeof *t);
		if (!t) {
			pthread_mutex_unlock(&g_mu);
			inst_free(in);
			close(p[0]);
			errno = ENOMEM;
			return -1;
		}
		memset(t + g_cap, 0, (size_t)(cap - g_cap) * sizeof *t);
		g_tab = t;
		g_cap = cap;
	}
	g_tab[p[0]] = in;
	pthread_mutex_unlock(&g_mu);
	return p[0];
}

int qlinux_epoll_create(int size)
{
	if (size <= 0) {
		errno = EINVAL;
		return -1;
	}
	return qlinux_epoll_create1(0);
}

static int find(const struct inst *in, int fd)
{
	for (int i = 0; i < in->n; i++)
		if (in->items[i].fd == fd)
			return i;
	return -1;
}

static void wake(const struct inst *in)
{
	ssize_t r = write(in->wfd, "", 1); /* EAGAIN: the pipe is already full of wake-ups */
	(void)r;
}

int qlinux_epoll_ctl(int epfd, int op, int fd, struct epoll_event *ev)
{
	if (fcntl(fd, F_GETFD) < 0) {
		errno = EBADF;
		return -1;
	}
	struct inst *in = inst_get(epfd);
	if (!in)
		return -1;
	int rc = 0, err = 0;
	pthread_mutex_lock(&in->mu);
	int i = find(in, fd);
	if (fd == epfd) {
		err = EINVAL;
	} else if (op == EPOLL_CTL_ADD) {
		if (!ev) {
			err = EFAULT;
		} else if (i >= 0) {
			err = EEXIST;
		} else {
			if (in->n == in->cap) {
				int cap = in->cap ? in->cap * 2 : 16;
				struct item *t = realloc(in->items, (size_t)cap * sizeof *t);
				if (!t) {
					err = ENOMEM;
					goto out;
				}
				in->items = t;
				in->cap = cap;
			}
			in->items[in->n++] = (struct item){ fd, ev->events, ev->data, 0 };
		}
	} else if (op == EPOLL_CTL_MOD) {
		if (!ev)
			err = EFAULT;
		else if (i < 0)
			err = ENOENT;
		else
			in->items[i] = (struct item){ fd, ev->events, ev->data, 0 };
	} else if (op == EPOLL_CTL_DEL) {
		if (i < 0)
			err = ENOENT;
		else
			in->items[i] = in->items[--in->n];
	} else {
		err = EINVAL;
	}
out:
	pthread_mutex_unlock(&in->mu);
	if (err) {
		errno = err;
		rc = -1;
	} else {
		wake(in);
	}
	inst_put(in);
	return rc;
}

static short to_poll(uint32_t e)
{
	short p = 0;
	if (e & EPOLLIN) p |= POLLIN;
	if (e & EPOLLPRI) p |= POLLPRI;
	if (e & EPOLLOUT) p |= POLLOUT;
	if (e & EPOLLRDNORM) p |= POLLRDNORM;
	if (e & EPOLLRDBAND) p |= POLLRDBAND;
	if (e & EPOLLWRNORM) p |= POLLWRNORM;
	if (e & EPOLLWRBAND) p |= POLLWRBAND;
	return p;
}

static uint32_t from_poll(short p, uint32_t wanted)
{
	uint32_t e = 0;
	if (p & POLLIN) e |= EPOLLIN;
	if (p & POLLPRI) e |= EPOLLPRI;
	if (p & POLLOUT) e |= EPOLLOUT;
	if (p & POLLRDNORM) e |= EPOLLRDNORM;
	if (p & POLLRDBAND) e |= EPOLLRDBAND;
	if (p & POLLWRNORM) e |= EPOLLWRNORM;
	if (p & POLLWRBAND) e |= EPOLLWRBAND;
	if (p & POLLERR) e |= EPOLLERR;
	if (p & POLLHUP) e |= EPOLLHUP | (wanted & EPOLLRDHUP);
	return e & (wanted | EPOLLERR | EPOLLHUP);
}

static long long now_ms(void)
{
	struct timespec ts;
	clock_gettime(CLOCK_MONOTONIC, &ts);
	return (long long)ts.tv_sec * 1000 + ts.tv_nsec / 1000000;
}

int qlinux_epoll_pwait(int epfd, struct epoll_event *evs, int maxevents, int timeout,
                       const sigset_t *sigmask)
{
	if (maxevents <= 0 || !evs) {
		errno = maxevents <= 0 ? EINVAL : EFAULT;
		return -1;
	}
	struct inst *in = inst_get(epfd);
	if (!in)
		return -1;
	long long deadline = timeout > 0 ? now_ms() + timeout : 0;
	struct pollfd *pfd = NULL;
	int cap = 0, count = 0, rc;

	for (;;) {
		pthread_mutex_lock(&in->mu);
		int n = in->n;
		if (n + 1 > cap) {
			struct pollfd *t = realloc(pfd, (size_t)(n + 1) * sizeof *t);
			if (!t) {
				pthread_mutex_unlock(&in->mu);
				errno = ENOMEM;
				rc = -1;
				goto done;
			}
			pfd = t;
			cap = n + 1;
		}
		pfd[0] = (struct pollfd){ in->rfd, POLLIN, 0 };
		for (int i = 0; i < n; i++) {
			const struct item *it = &in->items[i];
			pfd[i + 1] = (struct pollfd){ it->disabled ? -1 : it->fd, to_poll(it->events), 0 };
		}
		pthread_mutex_unlock(&in->mu);

		int wait_ms = timeout;
		if (timeout > 0) {
			long long left = deadline - now_ms();
			wait_ms = left > 0 ? (int)left : 0;
		}
		sigset_t old;
		if (sigmask)
			pthread_sigmask(SIG_SETMASK, sigmask, &old);
		int r = poll(pfd, (nfds_t)(n + 1), wait_ms);
		int perr = errno;
		if (sigmask)
			pthread_sigmask(SIG_SETMASK, &old, NULL);
		if (r < 0) {
			errno = perr;
			rc = -1;
			goto done;
		}
		if (pfd[0].revents & POLLIN) {
			char buf[64];
			while (read(in->rfd, buf, sizeof buf) > 0)
				;
		}

		pthread_mutex_lock(&in->mu);
		unsigned start = n ? in->rot++ % (unsigned)n : 0;
		for (int k = 0; k < n && count < maxevents; k++) {
			const struct pollfd *p = &pfd[1 + (start + (unsigned)k) % (unsigned)n];
			if (p->fd < 0 || !p->revents)
				continue;
			int i = find(in, p->fd);
			if (i < 0)
				continue; /* removed while we were polling */
			struct item *it = &in->items[i];
			if (p->revents & POLLNVAL) { /* closed behind our back: Linux drops it too */
				in->items[i] = in->items[--in->n];
				continue;
			}
			uint32_t e = from_poll(p->revents, it->events);
			if (!e || it->disabled)
				continue;
			evs[count].events = e;
			evs[count].data = it->data;
			count++;
			if (it->events & EPOLLONESHOT)
				it->disabled = 1;
		}
		pthread_mutex_unlock(&in->mu);

		if (count > 0 || timeout == 0 || (timeout > 0 && now_ms() >= deadline)) {
			rc = count;
			goto done;
		}
	}
done:
	{
		int e = errno;
		free(pfd);
		inst_put(in);
		errno = e;
	}
	return rc;
}

int qlinux_epoll_wait(int epfd, struct epoll_event *evs, int maxevents, int timeout)
{
	return qlinux_epoll_pwait(epfd, evs, maxevents, timeout, NULL);
}
