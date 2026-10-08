"""Exec-only child launcher: avoids preexec_fn in the threaded server."""
import json, os, resource, sys, signal

def main():
    limits=json.loads(sys.argv[1]); argv=sys.argv[2:]
    resource.setrlimit(resource.RLIMIT_CPU,(limits['cpu'],limits['cpu']+1))
    resource.setrlimit(resource.RLIMIT_FSIZE,(limits['output'],limits['output']))
    resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    resource.setrlimit(resource.RLIMIT_NOFILE,(64,64))
    if sys.platform.startswith('linux'):
        # RSS is monitored separately. Allow mappings while bounding address space.
        address=(limits['memory_mb']*2+32)*1024*1024
        resource.setrlimit(resource.RLIMIT_AS,(address,address))
        resource.setrlimit(resource.RLIMIT_NPROC,(64,64))
    # macOS RLIMIT_AS is not a dependable RSS bound, and NPROC is per host UID.
    # Python ignores SIGPIPE/SIGXFSZ at startup. An exec-only launcher must
    # restore their normal dispositions before handing control to user code.
    for name in ('SIGPIPE','SIGXFZ','SIGXFSZ'):
        if hasattr(signal,name):signal.signal(getattr(signal,name),signal.SIG_DFL)
    os.execv(argv[0],argv)

if __name__=='__main__': main()
