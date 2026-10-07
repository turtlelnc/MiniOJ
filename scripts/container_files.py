"""No symlink traversal, including intermediate path components and races."""
import base64, json, os, sys
MAX=262144

def open_parent(path):
    parts=path.split('/')
    if not parts or len(parts)>12 or any(p in ('','.','..') or len(p)>255 for p in parts): raise ValueError('Invalid relative path')
    fd=os.open('/workspace',os.O_RDONLY|os.O_DIRECTORY)
    try:
        for part in parts[:-1]:
            new=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
            os.close(fd); fd=new
        return fd,parts[-1]
    except BaseException:
        os.close(fd); raise

def walk(fd,prefix='',depth=0):
    result=[]
    if depth>8: return result
    for name in sorted(os.listdir(fd))[:200]:
        st=os.stat(name,dir_fd=fd,follow_symlinks=False)
        import stat
        if stat.S_ISREG(st.st_mode): result.append({'path':prefix+name,'size':st.st_size})
        elif stat.S_ISDIR(st.st_mode):
            child=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
            try: result+=walk(child,prefix+name+'/',depth+1)
            finally: os.close(child)
        if len(result)>=200: break
    return result[:200]

try:
    req=json.load(sys.stdin)
    if req['op']=='list':
        fd=os.open('/workspace',os.O_RDONLY|os.O_DIRECTORY)
        try: result={'files':walk(fd)}
        finally: os.close(fd)
    else:
        fd,name=open_parent(req['path'])
        try:
            if req['op']=='write':
                data=base64.b64decode(req['content_b64'])
                if len(data)>MAX: raise ValueError('File too large')
                f=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_NOFOLLOW|os.O_NONBLOCK,0o600,dir_fd=fd)
                try:
                    import stat
                    if not stat.S_ISREG(os.fstat(f).st_mode): raise ValueError('Not a regular file')
                    os.ftruncate(f,0)
                    with os.fdopen(f,'wb',closefd=False) as stream: stream.write(data)
                finally: os.close(f)
                result={'size':len(data)}
            else:
                f=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
                try:
                    import stat
                    st=os.fstat(f)
                    if not stat.S_ISREG(st.st_mode) or st.st_size>MAX: raise ValueError('Not a small regular file')
                    with os.fdopen(f,'rb',closefd=False) as stream: data=stream.read(MAX+1)
                    if len(data)>MAX: raise ValueError('File too large')
                finally: os.close(f)
                result={'content_b64':base64.b64encode(data).decode()}
        finally: os.close(fd)
    print(json.dumps(result))
except Exception as e:
    print(json.dumps({'error':str(e)})); sys.exit(1)
