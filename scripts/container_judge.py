"""Bounded testcase supervisor; source is passed by the host, never from workspace.

PR_SET_DUMPABLE=0 protects the reporting pipe from same-UID /proc/ptrace
access. Contestants can kill this supervisor, but that yields SE, never a
fabricated contestant exit record. All original container restrictions remain.
"""
import base64
import ctypes
import json
import os
import resource
import selectors
import signal
import subprocess
import sys
import time


def run(time_ms, output_limit, wall_ms=None):
    wall_ms=time_ms if wall_ms is None else wall_ms
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(4, 0, 0, 0, 0) != 0:  # PR_SET_DUMPABLE
        raise OSError(ctypes.get_errno(), 'cannot protect Judge reporting pipe')

    def limits():
        cpu = max(1, (time_ms + 999) // 1000) + 1
        resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu + 1))
        resource.setrlimit(resource.RLIMIT_FSIZE, (output_limit, output_limit))
        resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

    start = time.monotonic()
    p = subprocess.Popen(['/workspace/main'], stdin=sys.stdin.buffer,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         start_new_session=True, preexec_fn=limits, close_fds=True)
    out, err = bytearray(), bytearray()
    reason = None
    try:
        # The kernel RLIMIT_CPU guard can fire slightly before its nominal
        # second due to tick accounting. Enforce the requested CPU budget from
        # the child's own process CPU clock; keep RLIMIT_CPU as a later guard.
        # No shared/container cgroup CPU time is attributed to this process.
        clockid=ctypes.c_int()
        error=libc.clock_getcpuclockid(p.pid,ctypes.byref(clockid))
        if error:raise OSError(error,'contestant CPU clock unavailable')
        usage=None
        def cpu_expired():
            if p.returncode is not None:
                return usage is not None and (usage.ru_utime+usage.ru_stime)*1000 >= time_ms
            return time.clock_gettime(clockid.value)*1000 >= time_ms
        def reap():
            nonlocal usage
            if p.returncode is None:
                pid,status,ru=os.wait4(p.pid,os.WNOHANG)
                if pid:
                    p.returncode=os.waitstatus_to_exitcode(status);usage=ru
            return p.returncode is None
        with selectors.DefaultSelector() as selector:
            for pipe, target in ((p.stdout, out), (p.stderr, err)):
                os.set_blocking(pipe.fileno(), False)
                selector.register(pipe, selectors.EVENT_READ, target)
            while selector.get_map():
                events=selector.select(.002)
                for key, _ in events:
                    chunk = os.read(key.fd, 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    remaining = output_limit - len(out) - len(err)
                    key.data.extend(chunk[:remaining])
                    if len(chunk) > remaining:
                        reason = 'output_limit'
                        break
                if reason:break
                expired=cpu_expired()
                live=reap()
                if expired:
                    reason='cpu_timeout'
                    break
                # Preserve a completed exit/signal when the supervisor itself
                # was descheduled. Drain buffered output before the deadline
                # check; never overwrite a reaped status with a wall timeout.
                if not live and not events:break
                if (time.monotonic()-start)*1000 >= wall_ms:
                    if reap():reason='timeout'
                    break
        # Pipes can be closed by a still-running contestant.
        while reason is None and p.returncode is None:
            expired=cpu_expired()
            live=reap()
            if expired:
                reason='cpu_timeout'
                break
            if not live:break
            if (time.monotonic()-start)*1000 >= wall_ms:
                if reap():reason='timeout'
                break
            time.sleep(.002)
        if reason and p.returncode is None:
            try:os.killpg(p.pid,signal.SIGKILL)
            except ProcessLookupError:pass
            _,status,usage=os.wait4(p.pid,0)
            p.returncode=os.waitstatus_to_exitcode(status)
        sig = -p.returncode if p.returncode < 0 else None
        if reason is None and sig == signal.SIGXCPU and (usage.ru_utime+usage.ru_stime)*1000 >= time_ms:
            reason = 'cpu_timeout'
        return {'version': 1, 'returncode': p.returncode, 'termination_signal': sig,
                'reason': reason, 'runtime_ms': round((time.monotonic()-start)*1000, 3),
                'stdout_b64': base64.b64encode(out).decode(),
                'stderr_b64': base64.b64encode(err).decode()}
    finally:
        if p.returncode is None:
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            p.wait()
        p.stdout.close()
        p.stderr.close()


if __name__ == '__main__':
    print(json.dumps(run(int(sys.argv[1]), int(sys.argv[2]),int(sys.argv[3]) if len(sys.argv)>3 else None)), flush=True)
