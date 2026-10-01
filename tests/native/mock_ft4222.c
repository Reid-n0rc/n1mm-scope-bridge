/*
 * SPDX-License-Identifier: GPL-3.0-only
 * SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
 *
 * Mock FTDI D2XX + LibFT4222 library for automated tests (issue #37).
 *
 * TEST INFRASTRUCTURE ONLY: never shipped. Contains no FTDI code; it only
 * exports functions with the same names and C signatures the bridge calls, so
 * the real ctypes binding, DLL search, and calling convention are exercised
 * without a radio or FTDI's proprietary libraries.
 *
 * Build (tests/mock_ftdi.py does this):
 *   Windows (MSVC): ftd2xx.dll (FT_* exports, -DMOCK_D2XX) and
 *                   LibFT4222-64.dll (FT4222_* exports, -DMOCK_FT4222).
 *                   FTDI's exports are __stdcall (FTAPI).
 *   Linux/macOS:    libft4222.so / libft4222.dylib with everything (-DMOCK_D2XX
 *                   -DMOCK_FT4222), like FTDI's combined Linux library.
 *
 * Environment:
 *   N1MM_MOCK_FT4222_CAPTURE  raw SPI byte stream served by SingleRead (looped)
 *   N1MM_MOCK_FT4222_LOG      optional file; one line per call is appended
 *
 * Every parameter wfview uses is checked; a wrong value returns
 * FT_INVALID_PARAMETER (6) so a regression in the binding fails loudly.
 */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifdef _WIN32
#include <windows.h>
#define EXPORT __declspec(dllexport)
#define FTAPI __stdcall
#else
#define EXPORT __attribute__((visibility("default")))
#define FTAPI
#endif

typedef uint32_t FT_STATUS;
typedef void *FT_HANDLE;

enum {
    FT_OK = 0,
    FT_INVALID_HANDLE = 1,
    FT_DEVICE_NOT_FOUND = 2,
    FT_DEVICE_NOT_OPENED = 3,
    FT_IO_ERROR = 4,
    FT_INVALID_PARAMETER = 6,
    FT_OPEN_BY_DESCRIPTION = 2
};

#define MOCK_MAGIC 0x4E314D4Du /* "N1MM" */

/* Shared by both DLLs on Windows: the handle points at this struct. Memory is
 * allocated and freed only in the D2XX half (FT_OpenEx / FT_Close). */
typedef struct {
    uint32_t magic;
    unsigned char *data;
    size_t size;
    size_t pos;
    int timeouts_ok, latency_ok, spi_ok, clock_ok;
    char log_path[1024];
} mock_device;

/* Read the process environment directly: on Windows the test process may use a
 * different C runtime than this DLL, so getenv() could miss runtime changes. */
static const char *mock_getenv(const char *name) {
#ifdef _WIN32
    static char value[2][1024];
    static int slot = 0;
    slot ^= 1;
    DWORD n = GetEnvironmentVariableA(name, value[slot], (DWORD)sizeof value[slot]);
    return (n > 0 && n < sizeof value[slot]) ? value[slot] : NULL;
#else
    return getenv(name);
#endif
}

static void mock_log(const mock_device *dev, const char *line) {
    const char *path = dev ? dev->log_path : mock_getenv("N1MM_MOCK_FT4222_LOG");
    if (!path || !*path) return;
    FILE *f = fopen(path, "a");
    if (!f) return;
    fprintf(f, "%s\n", line);
    fclose(f);
}

static mock_device *device(FT_HANDLE h) {
    mock_device *dev = (mock_device *)h;
    return (dev && dev->magic == MOCK_MAGIC) ? dev : NULL;
}

#ifdef MOCK_D2XX
EXPORT FT_STATUS FTAPI FT_OpenEx(void *arg, uint32_t flags, FT_HANDLE *handle) {
    char line[256];
    snprintf(line, sizeof line, "FT_OpenEx %s %u", arg ? (const char *)arg : "(null)", flags);
    mock_log(NULL, line);
    if (!handle || flags != FT_OPEN_BY_DESCRIPTION) return FT_INVALID_PARAMETER;
    *handle = NULL;
    if (!arg || strcmp((const char *)arg, "FT4222 A") != 0) return FT_DEVICE_NOT_FOUND;
    const char *capture = mock_getenv("N1MM_MOCK_FT4222_CAPTURE");
    if (!capture) return FT_DEVICE_NOT_FOUND;
    FILE *f = fopen(capture, "rb");
    if (!f) return FT_DEVICE_NOT_FOUND;
    mock_device *dev = (mock_device *)calloc(1, sizeof *dev);
    if (!dev) { fclose(f); return FT_IO_ERROR; }
    fseek(f, 0, SEEK_END);
    long size = ftell(f);
    fseek(f, 0, SEEK_SET);
    dev->data = size > 0 ? (unsigned char *)malloc((size_t)size) : NULL;
    if (size <= 0 || !dev->data || fread(dev->data, 1, (size_t)size, f) != (size_t)size) {
        fclose(f);
        free(dev->data);
        free(dev);
        return FT_IO_ERROR;
    }
    fclose(f);
    dev->size = (size_t)size;
    dev->magic = MOCK_MAGIC;
    const char *log = mock_getenv("N1MM_MOCK_FT4222_LOG");
    if (log) snprintf(dev->log_path, sizeof dev->log_path, "%s", log);
    *handle = dev;
    return FT_OK;
}

EXPORT FT_STATUS FTAPI FT_Close(FT_HANDLE h) {
    mock_device *dev = device(h);
    mock_log(dev, "FT_Close");
    if (!dev) return FT_INVALID_HANDLE;
    dev->magic = 0;
    free(dev->data);
    free(dev);
    return FT_OK;
}

EXPORT FT_STATUS FTAPI FT_SetTimeouts(FT_HANDLE h, uint32_t read_ms, uint32_t write_ms) {
    mock_device *dev = device(h);
    mock_log(dev, "FT_SetTimeouts");
    if (!dev) return FT_INVALID_HANDLE;
    if (read_ms != 100 || write_ms != 100) return FT_INVALID_PARAMETER;
    dev->timeouts_ok = 1;
    return FT_OK;
}

EXPORT FT_STATUS FTAPI FT_SetLatencyTimer(FT_HANDLE h, unsigned char ms) {
    mock_device *dev = device(h);
    mock_log(dev, "FT_SetLatencyTimer");
    if (!dev) return FT_INVALID_HANDLE;
    if (ms != 2) return FT_INVALID_PARAMETER;
    dev->latency_ok = 1;
    return FT_OK;
}
#endif /* MOCK_D2XX */

#ifdef MOCK_FT4222
EXPORT FT_STATUS FTAPI FT4222_SPIMaster_Init(FT_HANDLE h, int mode, int clk, int cpol, int cpha,
                                             unsigned char sso) {
    mock_device *dev = device(h);
    mock_log(dev, "FT4222_SPIMaster_Init");
    if (!dev) return FT_INVALID_HANDLE;
    /* wfview: SPI_IO_SINGLE, CLK_DIV_64, CLK_IDLE_HIGH, CLK_LEADING, SS mask 0x01 */
    if (mode != 1 || clk != 6 || cpol != 1 || cpha != 0 || sso != 1) return FT_INVALID_PARAMETER;
    dev->spi_ok = 1;
    return FT_OK;
}

EXPORT FT_STATUS FTAPI FT4222_SetClock(FT_HANDLE h, int clock) {
    mock_device *dev = device(h);
    mock_log(dev, "FT4222_SetClock");
    if (!dev) return FT_INVALID_HANDLE;
    if (clock != 1) return FT_INVALID_PARAMETER; /* SYS_CLK_24 */
    dev->clock_ok = 1;
    return FT_OK;
}

EXPORT FT_STATUS FTAPI FT4222_SPIMaster_SingleRead(FT_HANDLE h, unsigned char *buffer,
                                                   uint16_t size, uint16_t *got,
                                                   int end_transaction) {
    mock_device *dev = device(h);
    if (!dev) return FT_INVALID_HANDLE;
    if (!buffer || !got || end_transaction != 0) return FT_INVALID_PARAMETER;
    if (!(dev->timeouts_ok && dev->latency_ok && dev->spi_ok && dev->clock_ok)) {
        return FT_DEVICE_NOT_OPENED; /* read before the wfview setup sequence */
    }
    for (uint16_t i = 0; i < size; i++) {
        buffer[i] = dev->data[dev->pos];
        dev->pos = (dev->pos + 1) % dev->size; /* loop the capture like a live radio */
    }
    *got = size;
    return FT_OK;
}

EXPORT FT_STATUS FTAPI FT4222_UnInitialize(FT_HANDLE h) {
    mock_device *dev = device(h);
    mock_log(dev, "FT4222_UnInitialize");
    return dev ? FT_OK : FT_INVALID_HANDLE;
}
#endif /* MOCK_FT4222 */
