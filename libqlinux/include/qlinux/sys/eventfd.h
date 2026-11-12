/*
 * libqlinux: eventfd for QNX.
 *
 * The descriptor is an anonymous FIFO opened read-write, so one fd can be
 * written, read, polled and closed like a Linux eventfd. Each 8-byte write is
 * one message on the FIFO.
 *
 * Exact Linux behaviour:
 *   - EFD_SEMAPHORE with writes of 1 (a counting semaphore / message queue).
 *   - eventfd_read() / eventfd_write() in either mode (eventfd_read() sums all
 *     pending writes, as a Linux counter read does).
 * Differences:
 *   - A raw read() in counter mode returns one write's value, not the sum.
 *   - Pending writes are bounded by the FIFO buffer (about PIPE_BUF / 8); past
 *     that, write() blocks or fails with EAGAIN instead of adding to a counter.
 */
#ifndef QLINUX_SYS_EVENTFD_H
#define QLINUX_SYS_EVENTFD_H

#include <fcntl.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define EFD_SEMAPHORE 1
#define EFD_CLOEXEC   O_CLOEXEC
#define EFD_NONBLOCK  O_NONBLOCK

typedef uint64_t eventfd_t;

int qlinux_eventfd(unsigned int initval, int flags);
int qlinux_eventfd_read(int fd, eventfd_t *value);
int qlinux_eventfd_write(int fd, eventfd_t value);

#ifndef QLINUX_NO_RENAME
#define eventfd       qlinux_eventfd
#define eventfd_read  qlinux_eventfd_read
#define eventfd_write qlinux_eventfd_write
#endif

#ifdef __cplusplus
}
#endif

#endif /* QLINUX_SYS_EVENTFD_H */
