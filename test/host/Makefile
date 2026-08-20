# Builds the pure firmware modules + test shim into a host shared library that
# the pytest suite loads via ctypes. No Pico SDK involved — these modules are
# hardware-agnostic by design.
#
# Unlike the keypad project's Makefile, the library also depends on the module
# HEADERS, so a header-only edit (struct layout, enum order) rebuilds the .so
# instead of leaving pytest running against stale code.
SRC := ../../firmware/src
CFLAGS := -std=c11 -O2 -fPIC -Wall -Wextra -I$(SRC)

SRCS := \
	$(SRC)/buttons/buttons.c \
	$(SRC)/rings/rings.c \
	$(SRC)/protocol/protocol.c \
	shim.c

HDRS := \
	$(SRC)/buttons/buttons.h \
	$(SRC)/rings/rings.h \
	$(SRC)/protocol/protocol.h

libpanelcore.so: $(SRCS) $(HDRS)
	$(CC) $(CFLAGS) -shared $(SRCS) -o $@

.PHONY: clean
clean:
	rm -f libpanelcore.so
