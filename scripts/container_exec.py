"""Trusted container entrypoint for bounded commands and judge executions."""
import base64, dataclasses, json, os, sys
sys.path.insert(0,'/opt')
from minioj.runner import LocalRunner

request=json.load(sys.stdin)
if request.get('kind')=='compile':
    argv=['/usr/bin/g++','/workspace/main.cpp','-O2','-std=c++17','-o','/workspace/main']
elif request.get('kind')=='judge':
    argv=['/workspace/main']
else:
    argv=['/bin/bash','-c',request['command']]
result=LocalRunner().run(argv,'/workspace',base64.b64decode(request.get('input_b64','')),request['time_limit_ms'],request['memory_limit_mb'],request.get('output_limit',1048576))
d=dataclasses.asdict(result)
d['stdout_b64']=base64.b64encode(d.pop('stdout')).decode()
d['stderr_b64']=base64.b64encode(d.pop('stderr')).decode()
print(json.dumps(d))
