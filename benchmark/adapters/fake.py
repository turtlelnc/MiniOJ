import json
from . import Reply
class FakeModelAdapter:
 def __init__(self,spec):self.spec=spec
 def complete(self,messages,tools,temperature,seed,max_tokens,timeout,problem):
  stage=sum(m['role']=='assistant' for m in messages)
  sequence=[('read_file',{'path':'problem.json'}),('write_file',{'path':'main.cpp','content':self.spec.get('codes',{}).get(str(problem['id']),'int main(){}')}),('terminal',{'command':'g++ main.cpp -O2 -std=c++17 -o main && ./main < sample.in'}),('final_submit',{})]
  # Exercise hidden feedback only when the experiment protocol exposes it.
  if any(t['function']['name']=='submit_attempt' for t in tools):sequence.insert(3,('submit_attempt',{}))
  name,args=sequence[min(stage,len(sequence)-1)]
  return Reply({'role':'assistant','content':None,'tool_calls':[{'id':f'fake-{stage}','type':'function','function':{'name':name,'arguments':json.dumps(args)}}]},{'input_tokens':10,'output_tokens':10},self.spec['model'],seed)
