/*
 * libqlinux tests. Run on the build host (`make test`) to check the
 * emulation logic, and on a QNX 8.0 target to check it where it matters.
 */
#include <sys/epoll.h>   /* resolves to libqlinux/include/qlinux/sys/epoll.h */
#include <sys/eventfd.h> /* resolves to libqlinux/include/qlinux/sys/eventfd.h */
#include "compat.h"

#include <errno.h>
#include <poll.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/un.h>
#include <time.h>
#include <unistd.h>

static int failures, checks;

#define CHECK(cond) do { \
	checks++; \
	if (!(cond)) { failures++; fprintf(stderr, "FAIL %s:%d: %s (errno %d: %s)\n", \
		__FILE__, __LINE__, #cond, errno, strerror(errno)); } \
} while (0)

static long long ms(void)
{
	struct timespec ts;
	clock_gettime(CLOCK_MONOTONIC, &ts);
	return (long long)ts.tv_sec * 1000 + ts.tv_nsec / 1000000;
}

static void test_epoll_basic(void)
{
	int ep = epoll_create1(EPOLL_CLOEXEC), p[2];
	CHECK(ep >= 0);
	CHECK(fcntl(ep, F_GETFD) & FD_CLOEXEC);
	CHECK(pipe(p) == 0);

	struct epoll_event ev = { .events = EPOLLIN, .data.u64 = 0x1122334455667788ull }, out[4];
	CHECK(epoll_ctl(ep, EPOLL_CTL_ADD, p[0], &ev) == 0);
	CHECK(epoll_ctl(ep, EPOLL_CTL_ADD, p[0], &ev) == -1 && errno == EEXIST);
	CHECK(epoll_wait(ep, out, 4, 0) == 0);

	CHECK(write(p[1], "x", 1) == 1);
	CHECK(epoll_wait(ep, out, 4, 100) == 1);
	CHECK(out[0].events == EPOLLIN && out[0].data.u64 == 0x1122334455667788ull);

	/* write end is always writable */
	struct epoll_event wev = { .events = EPOLLOUT, .data.fd = p[1] };
	CHECK(epoll_ctl(ep, EPOLL_CTL_ADD, p[1], &wev) == 0);
	CHECK(epoll_wait(ep, out, 4, 0) == 2);

	CHECK(epoll_ctl(ep, EPOLL_CTL_DEL, p[1], NULL) == 0);
	CHECK(epoll_ctl(ep, EPOLL_CTL_DEL, p[1], NULL) == -1 && errno == ENOENT);
	CHECK(epoll_ctl(ep, EPOLL_CTL_MOD, p[1], &wev) == -1 && errno == ENOENT);
	CHECK(epoll_ctl(ep, EPOLL_CTL_ADD, ep, &ev) == -1 && errno == EINVAL);
	CHECK(epoll_ctl(ep, 99, p[0], &ev) == -1 && errno == EINVAL);
	CHECK(epoll_wait(ep, out, 0, 0) == -1 && errno == EINVAL);
	CHECK(epoll_wait(p[0], out, 4, 0) == -1 && errno == EINVAL);
	CHECK(epoll_wait(-1, out, 4, 0) == -1 && errno == EBADF);
	CHECK(epoll_create(0) == -1 && errno == EINVAL);

	close(p[0]);
	close(p[1]);
	close(ep);
}

static void test_epoll_oneshot_and_hup(void)
{
	int ep = epoll_create(1), p[2];
	CHECK(pipe(p) == 0);
	struct epoll_event ev = { .events = EPOLLIN | EPOLLONESHOT | EPOLLRDHUP, .data.fd = p[0] }, out[2];
	CHECK(epoll_ctl(ep, EPOLL_CTL_ADD, p[0], &ev) == 0);
	CHECK(write(p[1], "ab", 2) == 2);
	CHECK(epoll_wait(ep, out, 2, 100) == 1);
	CHECK(epoll_wait(ep, out, 2, 0) == 0);             /* disabled until MOD */
	CHECK(epoll_ctl(ep, EPOLL_CTL_MOD, p[0], &ev) == 0);
	CHECK(epoll_wait(ep, out, 2, 0) == 1);

	char b[2];
	CHECK(read(p[0], b, 2) == 2);
	CHECK(epoll_ctl(ep, EPOLL_CTL_MOD, p[0], &ev) == 0);
	close(p[1]);                                        /* writer gone: hang-up */
	CHECK(epoll_wait(ep, out, 2, 100) == 1);
	CHECK(out[0].events & EPOLLHUP);
	CHECK(out[0].events & EPOLLRDHUP);
	close(p[0]);
	close(ep);
}

static void test_epoll_closed_fd_dropped(void)
{
	int ep = epoll_create1(0), p[2];
	CHECK(pipe(p) == 0);
	struct epoll_event ev = { .events = EPOLLIN, .data.fd = p[0] }, out[2];
	CHECK(epoll_ctl(ep, EPOLL_CTL_ADD, p[0], &ev) == 0);
	close(p[0]);
	CHECK(epoll_wait(ep, out, 2, 50) == 0);
	/* the number is free again and may be registered anew */
	int q[2];
	CHECK(pipe(q) == 0);
	ev.data.fd = q[0];
	CHECK(epoll_ctl(ep, EPOLL_CTL_ADD, q[0], &ev) == 0);
	close(q[0]);
	close(q[1]);
	close(p[1]);
	close(ep);
}

struct waiter { int ep; int got; long long took; };

static void *wait_thread(void *arg)
{
	struct waiter *w = arg;
	struct epoll_event out[2];
	long long t0 = ms();
	w->got = epoll_wait(w->ep, out, 2, 3000);
	w->took = ms() - t0;
	return NULL;
}

/* A thread blocked in epoll_wait() must see an fd added after it started. */
static void test_epoll_add_wakes_waiter(void)
{
	struct waiter w = { epoll_create1(0), -1, 0 };
	int p[2];
	CHECK(pipe(p) == 0);
	CHECK(write(p[1], "x", 1) == 1);
	pthread_t t;
	pthread_create(&t, NULL, wait_thread, &w);
	usleep(100 * 1000);
	struct epoll_event ev = { .events = EPOLLIN, .data.fd = p[0] };
	CHECK(epoll_ctl(w.ep, EPOLL_CTL_ADD, p[0], &ev) == 0);
	pthread_join(t, NULL);
	CHECK(w.got == 1);
	CHECK(w.took < 1000);
	close(p[0]);
	close(p[1]);
	close(w.ep);
}

static void test_epoll_timeout(void)
{
	int ep = epoll_create1(0);
	struct epoll_event out[1];
	long long t0 = ms();
	CHECK(epoll_wait(ep, out, 1, 120) == 0);
	long long took = ms() - t0;
	CHECK(took >= 110 && took < 1000);
	close(ep);
	/* the closed descriptor is no longer an epoll instance */
	CHECK(epoll_wait(ep, out, 1, 0) == -1 && errno == EBADF);
}

static void test_eventfd(void)
{
	eventfd_t v = 0;
	int c = eventfd(0, EFD_NONBLOCK | EFD_CLOEXEC);
	CHECK(c >= 0);
	CHECK(fcntl(c, F_GETFD) & FD_CLOEXEC);
	CHECK(eventfd_read(c, &v) == -1 && errno == EAGAIN);
	CHECK(eventfd_write(c, 2) == 0);
	CHECK(eventfd_write(c, 3) == 0);
	struct pollfd pf = { c, POLLIN, 0 };
	CHECK(poll(&pf, 1, 0) == 1 && (pf.revents & POLLIN));
	CHECK(eventfd_read(c, &v) == 0 && v == 5);          /* counter: the sum */
	CHECK(eventfd_read(c, &v) == -1 && errno == EAGAIN);
	CHECK(eventfd_write(c, UINT64_MAX) == -1 && errno == EINVAL);
	close(c);

	int s = eventfd(2, EFD_SEMAPHORE | EFD_NONBLOCK);
	CHECK(s >= 0);
	uint64_t one = 1;
	CHECK(write(s, &one, sizeof one) == sizeof one);    /* raw write, as message queues do */
	CHECK(eventfd_read(s, &v) == 0 && v == 1);
	CHECK(read(s, &v, sizeof v) == sizeof v && v == 1);
	CHECK(eventfd_read(s, &v) == 0 && v == 1);
	CHECK(eventfd_read(s, &v) == -1 && errno == EAGAIN);
	close(s);

	/* blocking descriptor */
	int b = eventfd(7, 0);
	CHECK(b >= 0 && !(fcntl(b, F_GETFL) & O_NONBLOCK));
	CHECK(eventfd_read(b, &v) == 0 && v == 7);
	close(b);
	CHECK(eventfd(0, 0x40000000) == -1 && errno == EINVAL);
}

static void test_compat(void)
{
	int p[2];
	CHECK(qlinux_pipe2(p, O_NONBLOCK | O_CLOEXEC) == 0);
	CHECK(fcntl(p[0], F_GETFL) & O_NONBLOCK);
	CHECK(fcntl(p[1], F_GETFD) & FD_CLOEXEC);
	CHECK(qlinux_pipe2(p + 0, 0x40000000) == -1 && errno == EINVAL);

	int d = qlinux_dup3(p[0], 100, O_CLOEXEC);
	CHECK(d == 100 && (fcntl(d, F_GETFD) & FD_CLOEXEC));
	CHECK(qlinux_dup3(p[0], p[0], 0) == -1 && errno == EINVAL);
	close(d);
	close(p[0]);
	close(p[1]);

	char dir[] = "/tmp/qlinux-test-XXXXXX";
	CHECK(mkdtemp(dir) != NULL);
	struct sockaddr_un a = { .sun_family = AF_UNIX };
	snprintf(a.sun_path, sizeof a.sun_path, "%s/s", dir);
	int l = qlinux_socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0);
	CHECK(l >= 0 && (fcntl(l, F_GETFD) & FD_CLOEXEC));
	CHECK(bind(l, (struct sockaddr *)&a, sizeof a) == 0 && listen(l, 1) == 0);
	int c = socket(AF_UNIX, SOCK_STREAM, 0);
	CHECK(connect(c, (struct sockaddr *)&a, sizeof a) == 0);
	int s = qlinux_accept4(l, NULL, NULL, SOCK_NONBLOCK | SOCK_CLOEXEC);
	CHECK(s >= 0);
	CHECK(fcntl(s, F_GETFL) & O_NONBLOCK);
	CHECK(fcntl(s, F_GETFD) & FD_CLOEXEC);
	CHECK(qlinux_accept4(l, NULL, NULL, 0x40000000) == -1 && errno == EINVAL);
	close(s);
	close(c);
	close(l);
	unlink(a.sun_path);
	rmdir(dir);
}

int main(void)
{
	test_epoll_basic();
	test_epoll_oneshot_and_hup();
	test_epoll_closed_fd_dropped();
	test_epoll_add_wakes_waiter();
	test_epoll_timeout();
	test_eventfd();
	test_compat();
	printf("libqlinux: %d checks, %d failed\n", checks, failures);
	return failures ? 1 : 0;
}
