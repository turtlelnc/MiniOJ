"""PID 1 reaps orphaned children so repeated commands cannot fill PID slots."""
import os, time
while True:
    try:
        while os.waitpid(-1,os.WNOHANG)[0]: pass
    except ChildProcessError: pass
    time.sleep(.05)
