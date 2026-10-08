SYSTEM_PROMPT='Solve the given algorithm problem in C++17 using the isolated Linux workspace. Read problem.json, write main.cpp, compile and test with sample.in, then final_submit. Hidden tests are unavailable until submission. Use only provided tools. Do not merely return source code.'
def tool(name,properties,required):
 return {'type':'function','function':{'name':name,'description':name,'parameters':{'type':'object','properties':properties,'required':required,'additionalProperties':False}}}
def tools(protocol):
 result=[tool('read_file',{'path':{'type':'string'}},['path']),tool('write_file',{'path':{'type':'string'},'content':{'type':'string'}},['path','content']),tool('terminal',{'command':{'type':'string'}},['command']),tool('final_submit',{},[])]
 if protocol=='iterative':result.append(tool('submit_attempt',{},[]))
 return result
