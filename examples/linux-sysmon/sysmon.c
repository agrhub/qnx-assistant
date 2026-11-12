/*
 * sysmon: a small Linux system monitor, written the way Linux services often
 * are. It is the example project for the qpa codelab: it uses epoll, eventfd,
 * statfs, CLOCK_BOOTTIME, prctl, sysinfo and CPU affinity, none of which
 * exist as such on QNX 8.0.
 *
 *   ./sysmon             print one report
 *   ./sysmon --selftest  run the checks used by `make test`
 */
#define _GNU_SOURCE
#include <errno.h>
#include <pthread.h>
#include <sched.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/epoll.h>
#include <sys/eventfd.h>
#include <sys/prctl.h>
#include <sys/statfs.h>
#include <sys/sysinfo.h>
#include <time.h>
#include <unistd.h>

#define EVENTS 64

static long long uptime_ms(void)
{
	struct timespec ts;
	if (clock_gettime(CLOCK_BOOTTIME, &ts) != 0)
		return -1;
	return (long long)ts.tv_sec * 1000 + ts.tv_nsec / 1000000;
}

static unsigned long long disk_free_kb(const char *path)
{
	struct statfs st;
	if (statfs(path, &st) != 0)
		return 0;
	return (unsigned long long)st.f_bavail * st.f_bsize / 1024;
}

static unsigned long long total_ram_kb(void)
{
	struct sysinfo si;
	if (sysinfo(&si) != 0)
		return 0;
	return (unsigned long long)si.totalram * si.mem_unit / 1024;
}

static int pin_to_cpu0(void)
{
	cpu_set_t set;
	CPU_ZERO(&set);
	CPU_SET(0, &set);
	return sched_setaffinity(0, sizeof set, &set);
}

static void load_average(char *out, size_t len)
{
	FILE *f = fopen("/proc/loadavg", "r");
	if (!f || !fgets(out, (int)len, f))
		snprintf(out, len, "n/a");
	if (f)
		fclose(f);
	out[strcspn(out, "\n")] = 0;
}

/* A worker posts EVENTS notifications through an eventfd; the main loop
 * collects them with epoll, as an event-driven service would. */
static int efd;

static void *worker(void *arg)
{
	(void)arg;
	prctl(PR_SET_NAME, "sysmon-worker", 0, 0, 0);
	for (int i = 0; i < EVENTS; i++) {
		uint64_t one = 1;
		if (write(efd, &one, sizeof one) != sizeof one)
			return NULL;
		if (i % 8 == 0)
			usleep(1000);
	}
	return NULL;
}

static int event_loop(void)
{
	efd = eventfd(0, EFD_NONBLOCK | EFD_CLOEXEC);
	int ep = epoll_create1(EPOLL_CLOEXEC);
	if (efd < 0 || ep < 0)
		return -1;
	struct epoll_event ev = { .events = EPOLLIN, .data.fd = efd };
	if (epoll_ctl(ep, EPOLL_CTL_ADD, efd, &ev) != 0)
		return -1;

	pthread_t t;
	pthread_create(&t, NULL, worker, NULL);
	uint64_t got = 0;
	long long deadline = uptime_ms() + 5000;
	while (got < EVENTS && uptime_ms() < deadline) {
		struct epoll_event out[4];
		int n = epoll_wait(ep, out, 4, 500);
		for (int i = 0; i < n; i++) {
			uint64_t v;
			while (read(out[i].data.fd, &v, sizeof v) == sizeof v)
				got += v;
		}
	}
	pthread_join(t, NULL);
	close(ep);
	close(efd);
	return (int)got;
}

int main(int argc, char **argv)
{
	int selftest = argc > 1 && strcmp(argv[1], "--selftest") == 0;
	prctl(PR_SET_NAME, "sysmon", 0, 0, 0);
	int pinned = pin_to_cpu0() == 0;

	char load[64];
	load_average(load, sizeof load);
	long long up = uptime_ms();
	unsigned long long disk = disk_free_kb("/");
	unsigned long long ram = total_ram_kb();
	int events = event_loop();

	printf("uptime      %lld ms\n", up);
	printf("disk free   %llu kB on /\n", disk);
	printf("total RAM   %llu kB\n", ram);
	printf("load        %s\n", load);
	printf("cpu pinned  %s\n", pinned ? "yes" : "no");
	printf("events      %d of %d\n", events, EVENTS);

	if (!selftest)
		return 0;
	int fails = 0;
	fails += up <= 0;
	fails += disk == 0;
	fails += ram == 0;
	fails += events != EVENTS;
	printf("selftest    %s\n", fails ? "FAIL" : "PASS");
	return fails ? 1 : 0;
}
