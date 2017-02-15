import os
import signal
import threading
import queue as stdlib_queue

import pytest

from .. import _core
from .._signals import *

def kill_self(signum):
    if os.name == "nt":
        # On windows, os.kill exists but is really weird.
        #
        # If you give it CTRL_C_EVENT or CTRL_BREAK_EVENT, it tries to deliver
        # those using GenerateConsoleCtrlEvent. But I found that when I tried
        # to run my test normally, it would freeze waiting... unless I added
        # print statements, in which case the test suddenly worked. So I guess
        # these signals are only delivered if/when you access the console? I
        # don't really know what was going on there. From reading the
        # GenerateConsoleCtrlEvent docs I don't know how it worked at all.
        #
        # OTOH, if you pass os.kill any *other* signal number... then CPython
        # just calls TerminateProcess (wtf).
        #
        # So, anyway, os.kill is not so useful for testing purposes. Instead
        # we use raise():
        #
        #   https://msdn.microsoft.com/en-us/library/dwwzkt4c.aspx
        #
        # Have to import cffi inside the 'if os.name' block because we don't
        # depend on cffi on non-Windows platforms. (It would be easy to switch
        # this to ctypes though if we ever remove the cffi dependency.)
        #
        # Some more information:
        #   https://bugs.python.org/issue26350
        import cffi
        ffi = cffi.FFI()
        ffi.cdef("int raise(int);")
        lib = ffi.dlopen("api-ms-win-crt-runtime-l1-1-0.dll")
        getattr(lib, "raise")(signum)
    else:
        os.kill(os.getpid(), signum)

async def test_catch_signals():
    print = lambda *args: None
    orig = signal.getsignal(signal.SIGILL)
    print(orig)
    with catch_signals([signal.SIGILL]) as queue:
        # Raise it a few times, to exercise signal coalescing, both at the
        # call_soon level and at the SignalQueue level
        kill_self(signal.SIGILL)
        kill_self(signal.SIGILL)
        await _core.wait_run_loop_idle()
        kill_self(signal.SIGILL)
        await _core.wait_run_loop_idle()
        async for batch in queue:  # pragma: no branch
            assert batch == {signal.SIGILL}
            break
        kill_self(signal.SIGILL)
        async for batch in queue:  # pragma: no branch
            assert batch == {signal.SIGILL}
            break
    assert signal.getsignal(signal.SIGILL) is orig

def test_catch_signals_wrong_thread():
    threadqueue = stdlib_queue.Queue()
    async def naughty():
        try:
            with catch_signals([signal.SIGINT]) as _:
                pass  # pragma: no cover
        except Exception as exc:
            threadqueue.put(exc)
        else:  # pragma: no cover
            threadqueue.put(None)
    thread = threading.Thread(target=_core.run, args=(naughty,))
    thread.start()
    thread.join()
    exc = threadqueue.get_nowait()
    assert type(exc) is RuntimeError
