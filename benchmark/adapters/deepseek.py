import os
import httpx
from . import Reply,ModelFailure
class DeepSeekAdapter:
 def __init__(self,spec):
  key=os.environ.get(spec.get('api_key_env','DEEPSEEK_API_KEY'))
  if not key:raise ModelFailure('API key environment variable is absent')
  self.model=spec['model'];self.client=httpx.Client(base_url='https://api.deepseek.com',headers={'Authorization':'Bearer '+key})
 def complete(self,messages,tools,temperature,seed,max_tokens,timeout,problem):
  # DeepSeek seed control is not promised; never claim reproducibility.
  try:
   r=self.client.post('/chat/completions',json={'model':self.model,'messages':messages,'tools':tools,'temperature':temperature,'max_tokens':max_tokens,'thinking':{'type':'disabled'}},timeout=timeout)
   r.raise_for_status();data=r.json();usage=data.get('usage')
   return Reply(data['choices'][0]['message'],{'input_tokens':usage.get('prompt_tokens'),'output_tokens':usage.get('completion_tokens')} if usage else None,data.get('model'))
  except (httpx.HTTPError,ValueError,KeyError,IndexError) as exc:
   # No response bodies or headers: they may contain credentials.
   raise ModelFailure('Provider request failed: '+type(exc).__name__) from None
