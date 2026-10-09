"""Independent Agent Runs; terminal outcomes and missing observations are explicit."""
TERMINAL = {'Finished', 'Failed'}
VERDICTS = {'AC', 'WA', 'RE', 'TLE', 'MLE', 'CE'}
FAILURES = ('solution_failure', 'agent_failure', 'model_failure',
            'judge_failure', 'infrastructure_failure')


def mean(values):
    return sum(values)/len(values) if values else None


def token_usage(record):
    raw=record.get('usage')
    raw=raw if isinstance(raw,dict) else {}
    return {key:raw[key] if type(raw.get(key)) is int and raw[key]>=0 else None
            for key in ('input_tokens','output_tokens')}


def outcome(unit):
    """Return (evaluable, solved, failure). Ignore stale verdicts on failed Runs."""
    record = unit['record']
    category = record.get('failure_category')
    if unit['status'] == 'Finished' and not category and record.get('verdict') in VERDICTS:
        solved = record['verdict'] == 'AC'
        return True, solved, None if solved else 'solution_failure'
    if category == 'agent_failure':
        return True, False, category
    if category in FAILURES:
        return False, False, category
    return False, False, 'judge_failure' if record.get('verdict') == 'SE' else 'infrastructure_failure'


def group(units, seeds):
    completed = [u for u in units if u['status'] in TERMINAL]
    valid = [u for u in completed if outcome(u)[0]]
    solved = [u for u in completed if outcome(u)[1]]
    first = [u for u in valid if seeds and u['seed'] == seeds[0]]
    usage = [token_usage(u['record']) for u in valid]
    complete_usage = bool(valid) and all(x is not None and x.get('input_tokens') is not None and x.get('output_tokens') is not None for x in usage)
    total = sum(x['input_tokens']+x['output_tokens'] for x in usage) if complete_usage else None
    evaluable_rate = len(solved)/len(valid) if valid else None
    e2e_rate = len(solved)/len(completed) if completed else None
    finished_all = bool(units) and len(completed) == len(units)
    failures = len(completed)-len(solved)
    breakdown = {}
    for category in FAILURES:
        count = sum(outcome(u)[2] == category for u in completed)
        breakdown[category] = {'count': count,
                              'rate': count/len(completed) if completed else None,
                              'share_of_failures': count/failures if failures else None}
    return {
        'planned_units': len(units), 'completed_units': len(completed),
        'pending_units': sum(u['status']=='Pending' for u in units),
        'running_units': sum(u['status']=='Running' for u in units),
        'attempted': sum(u['status']!='Pending' for u in units),
        'evaluable': len(valid), 'excluded': len(completed)-len(valid), 'solved': len(solved),
        'solve_rate': evaluable_rate, 'evaluable_solve_rate': evaluable_rate,
        'evaluable_solve_rate_denominator': len(valid),
        'end_to_end_success_rate': e2e_rate,
        'end_to_end_success_rate_denominator': len(completed),
        'experiment_complete': finished_all,
        'final_end_to_end_success_rate': e2e_rate if finished_all else None,
        'failure_breakdown': breakdown,
        'verdict_counts': {v: sum(u['status']=='Finished' and not u['record'].get('failure_category') and u['record'].get('verdict')==v for u in completed) for v in sorted(VERDICTS | {'SE'})},
        'pass@1': sum(outcome(u)[1] for u in first)/len(first) if first else None,
        'pass@1_denominator': len(first),
        'mean_input_tokens': mean([x['input_tokens'] for x in usage if x and x.get('input_tokens') is not None]),
        'mean_output_tokens': mean([x['output_tokens'] for x in usage if x and x.get('output_tokens') is not None]),
        'mean_total_tokens': mean([x['input_tokens']+x['output_tokens'] for x in usage if x and x.get('input_tokens') is not None and x.get('output_tokens') is not None]),
        'usage_complete': complete_usage, 'usage_observed_units': sum(any(v is not None for v in x.values()) for x in usage),
        'mean_tool_calls': mean([u['record']['tool_calls'] for u in valid if u['record'].get('tool_calls') is not None]),
        'mean_wall_time': mean([u['record']['wall_time_seconds'] for u in valid if u['record'].get('wall_time_seconds') is not None]),
        'tokens_per_solved_problem': total/len(solved) if total is not None and solved else None,
    }


def summary(experiment):
    manifest, units = experiment['manifest'], experiment['units']
    overall=group(units,manifest['seeds'])
    groups=[{'model_index':i,'provider':model['provider'],'model':model['model'],
             **group([u for u in units if u['model_index']==i],manifest['seeds'])}
            for i,model in enumerate(manifest['models'])]
    for g in groups:
        g['group_complete']=g['experiment_complete']
        g['experiment_complete']=overall['experiment_complete']
        if not overall['experiment_complete']:g['final_end_to_end_success_rate']=None
    from .diagnostics import diagnostics
    return {
        'diagnostics': diagnostics(units),
        'protocol': manifest['protocol'],
        'overall': overall,
        'groups': groups,
        'definitions': {
            'pass@1': 'First configured seed per problem/model among evaluable terminal independent Agent Runs. Excluded first units are not replaced; pending/running first units are not evaluated. Within-Run revisions are not samples.',
            'solve_rate': 'Compatibility alias of evaluable_solve_rate.',
            'evaluable_solve_rate': 'AC / evaluable terminal independent Runs. Agent failures are unsolved; model, Judge and infrastructure failures excluded.',
            'end_to_end_success_rate': 'AC / all terminal (Finished or Failed) independent Runs, including all failure categories. Pending and Running excluded.',
            'final_end_to_end_success_rate': 'Null until all planned units are terminal; then AC / planned units.',
            'failure_breakdown': 'rate = category count / all terminal units; share_of_failures = category count / unsuccessful terminal units. solution_failure includes WA/RE/TLE/MLE/CE; unclassified terminal failures are infrastructure_failure.',
            'excluded': 'Terminal units excluded from evaluable_solve_rate; excludes neither Pending nor Running because neither is terminal.',
            'usage': 'Compatibility means use evaluable terminal observations; tokens_per_solved_problem is null if any evaluable usage is missing. Only nonnegative integer token counts are observations. Zero observed tokens is distinct from unavailable.',
            'iterative': 'Reported per experiment protocol; pass@1 is first independent Agent Run with iterative hidden feedback, not single-code-generation success rate.',
        },
    }
