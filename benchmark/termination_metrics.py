"""Conservative trajectory observations and preregistered factorial estimates."""
from pathlib import PurePosixPath
from .diagnostics import diagnostics
from .metrics import TERMINAL, group

TRAJECTORY_FIELDS = ['last_code_change_model_call', 'model_calls_after_last_code_change',
                     'tool_calls_after_last_code_change', 'remaining_calls_at_last_code_change',
                     'final_submit_attempted', 'final_submit_completed', 'terminal_reason',
                     'posthoc_rejudge_verdict']


def trajectory(record, limits):
    result = {k: None for k in TRAJECTORY_FIELDS}
    result.update(final_submit_attempted=record.get('final_submit_attempted'),
                  final_submit_completed=record.get('final_submission_completed'),
                  terminal_reason=record.get('error') or record.get('verdict'))
    events = record.get('tool_events')
    if events is None:
        result['code_change_observation'] = 'unavailable trajectory'
        return result
    # A shell can edit main.cpp or start a background writer. Do not infer exact
    # source-change timing from a write event or final snapshot in such a Run.
    if any(e['name'] == 'terminal' or (e['name']=='write_file' and 'size' not in (e.get('result') or {})) for e in events):
        result['code_change_observation'] = 'unknown: terminal/background mutations are not versioned'
        return result
    previous = ''; last = None
    for event in events:
        if event['name']=='write_file' and PurePosixPath(event.get('args',{}).get('path',''))==PurePosixPath('main.cpp') and 'size' in (event.get('result') or {}):
            content=event['args']['content']
            if content!=previous:last=event
            previous=content
    result['code_change_observation'] = 'successful API writes only; initial source empty; no terminal commands'
    if last:
        result.update(last_code_change_model_call=last['model_call'],
                      model_calls_after_last_code_change=record['model_calls']-last['model_call'],
                      tool_calls_after_last_code_change=record['tool_calls']-last['tool_call'],
                      remaining_calls_at_last_code_change=max(0,limits['max_model_calls']-last['model_call']))
    return result


def condition_metrics(units, posthoc=None):
    d=diagnostics(units,posthoc);done=[u for u in units if u['status'] in TERMINAL];n=len(done)
    d['call_budget_exhaustion_count']=sum(u['record'].get('error') in ('model_call_budget','tool_call_budget') for u in done)
    d['call_budget_exhaustion_rate']=d['call_budget_exhaustion_count']/n if n else None
    d['wall_budget_exhaustion_count']=sum(u['record'].get('error')=='wall_time_budget' for u in done)
    d['posthoc_code_correctness']=d['valid_code_at_termination_rate']
    d['definitions']['phase7_budget_exhaustion']='Model/tool budget failures / terminal Runs; wall-clock failures reported separately.'
    return d


def factorial(experiments, posthoc=None):
    groups={};per_problem={}
    for c in 'ABCD':
        e=experiments[c];units=e['units']
        groups[c]={'counts':group(units,e['manifest']['seeds']), 'diagnostics':condition_metrics(units,posthoc)}
        per_problem[c]={str(pid):condition_metrics([u for u in units if u['problem_id']==pid],posthoc)
                        for pid in sorted({u['problem_id'] for u in units})}
    rates={c:g['diagnostics']['end_to_end_success_rate'] for c,g in groups.items()}
    # No early factorial contrasts from incomplete/unbalanced conditions.
    complete=all(g['counts']['experiment_complete'] for g in groups.values())
    contrasts={'budget_average_effect':None,'reminder_average_effect':None,'interaction':None}
    if complete and all(v is not None for v in rates.values()):
        a,b,c,d=(rates[x] for x in 'ABCD')
        contrasts.update(budget_average_effect=((b-a)+(d-c))/2,
                         reminder_average_effect=((c-a)+(d-b))/2,
                         interaction=(d-c)-(b-a))
    return {'groups':groups,'per_problem':per_problem,'complete':complete,'descriptive_rate_differences':contrasts,
            'interpretation':'Descriptive differences only. Ten Runs per condition, five problem clusters; repetitions are not independent problems. No significance claim or pooling with Phase 6.'}
