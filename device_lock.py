# -*- coding: utf-8 -*-
"""device_lock.py —— 跨进程串行化 HID 读取。

托盘和面板是两个进程，可能在同一秒刷新；键盘 RDR 是“开始会话/读电量/结束”
的请求-响应协议，两个进程同时发会把会话打乱。这里用一个命名互斥体
（Local\\ 命名空间，同一登录会话内可见）把整次读取串起来。
"""
from __future__ import annotations

import contextlib
import ctypes
import functools
from ctypes import wintypes

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.CreateMutexW.restype = ctypes.c_void_p
kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.WaitForSingleObject.restype = wintypes.DWORD
kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, wintypes.DWORD]
kernel32.ReleaseMutex.restype = wintypes.BOOL
kernel32.ReleaseMutex.argtypes = [ctypes.c_void_p]
kernel32.CloseHandle.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [ctypes.c_void_p]

MUTEX_NAME = "Local\\ExtBatteryHidReadLock"
WAIT_OBJECT_0 = 0
WAIT_ABANDONED = 0x80


@contextlib.contextmanager
def read_lock(timeout_ms: int = 15000):
    handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if not handle:
        yield
        return
    result = kernel32.WaitForSingleObject(handle, timeout_ms)
    acquired = result in (WAIT_OBJECT_0, WAIT_ABANDONED)
    try:
        yield
    finally:
        if acquired:
            kernel32.ReleaseMutex(handle)
        kernel32.CloseHandle(handle)


def locked(func):
    """给 read_battery() 加上跨进程锁。"""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        with read_lock():
            return func(*args, **kwargs)
    return wrapper
