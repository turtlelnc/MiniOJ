from dataclasses import dataclass
@dataclass
class Reply:
 message:dict
 usage:dict|None
 model:str|None=None
 effective_seed:int|None=None
class ModelFailure(RuntimeError):pass
def adapter(spec):
 if spec['provider']=='deepseek':
  from .deepseek import DeepSeekAdapter
  return DeepSeekAdapter(spec)
 if spec['provider']=='fake':
  from .fake import FakeModelAdapter
  return FakeModelAdapter(spec)
 raise ValueError('Unsupported provider')
