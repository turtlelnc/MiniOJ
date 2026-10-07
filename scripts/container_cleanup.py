import os, signal, time
# Bounded repeated scans close the race where a process forks during cleanup.
for _ in range(10):
    victims=[int(p) for p in os.listdir('/proc') if p.isdigit() and int(p) not in (1,os.getpid())]
    if not victims: break
    for pid in victims:
        try: os.kill(pid,signal.SIGKILL)
        except (ProcessLookupError,PermissionError): pass
    time.sleep(.03)
