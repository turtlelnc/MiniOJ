import csv,io,json
from pathlib import Path
from .metrics import token_usage
FIELDS=['unit_id','problem_id','model_index','seed_requested','seed_effective','protocol','run_id','submission_id','verdict','failure_category','error','model_calls','tool_calls','wall_time_seconds','input_tokens','output_tokens','total_tokens','status']
def csv_text(experiment):
 stream=io.StringIO();writer=csv.DictWriter(stream,fieldnames=FIELDS);writer.writeheader()
 for u in experiment['units']:
  r={**u['record'],'run_id':u['run_id'],'unit_id':u['id'],'status':u['status']};usage=token_usage(r);r.update(usage);r['total_tokens']=usage['input_tokens']+usage['output_tokens'] if usage.get('input_tokens') is not None and usage.get('output_tokens') is not None else None;writer.writerow({k:r.get(k) for k in FIELDS})
 return stream.getvalue()
def export(experiment,directory):
 directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
 for name,value in [('results',experiment),('summary',experiment['summary'])]:
  (directory/(name+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2))
 (directory/'results.csv').write_text(csv_text(experiment))
