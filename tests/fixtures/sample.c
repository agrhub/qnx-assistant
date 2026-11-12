/* Fixture for the scanner tests. Not meant to compile.
 * A comment that mentions epoll_wait() and nmcli must not count. */
#include <stdio.h>
#include <sys/epoll.h>
#include <linux/input.h>
#include <gst/gst.h>

#define IFACE "wlan0"

static int run(const char *a, const char *b, const char *c, const char *d);

void json(cJSON *n, const char *ip)
{
	cJSON_AddStringToObject(n, "ip", ip);           /* a JSON key, not the ip command */
	printf("call epoll_wait now\n");                 /* text inside a string */
}

void launch(void)
{
	char *const argv[] = { (char *)"nmcli", "-t", "con", "show", NULL };
	char *const wrapped[] = { "timeout", "15", "ping", "-c", "4", NULL };
	static const char *labels[] = { "yes", "no", NULL };   /* an option table, not an argv */
	execvp(wrapped[0], wrapped);
	system("systemctl restart camos-gatewayd");
	execlp("curl", "curl", "-s", NULL);
	run("parted", "-s", "/dev/sda", "mklabel");
	FILE *f = fopen("/sys/class/net/" IFACE "/address", "r");
	FILE *g = fopen("/proc/net/route", "r");
	int ep = epoll_create1(0);
	gst_init(NULL, NULL);
	send(3, "x", 1, MSG_NOSIGNAL);
}

#ifdef __linux__
static int linux_only(void) { return eventfd(0, 0); }
#else
static int other(void) { return eventfd(0, 0); }
#endif
