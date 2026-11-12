CC ?= cc
CFLAGS ?= -O2 -Wall

sysmon: sysmon.c
	$(CC) $(CFLAGS) -o $@ sysmon.c $(LDFLAGS)

test: sysmon
	./sysmon --selftest

clean:
	rm -f sysmon

.PHONY: test clean
