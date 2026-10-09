"""Completion diagnostics are additive; post-hoc observations never change scores."""
from .metrics import TERMINAL, outcome, mean, token_usage


def diagnostics(units, posthoc=None):
    done = [u for u in units if u['status'] in TERMINAL]
    n = len(done)
    records = [u['record'] for u in done]
    def rate(count): return count/n if n else None
    # Evidence must be explicit. A submitted attempt is not a final submission.
    completed = [u for u in done if u['record'].get('final_submission_completed') is True]
    successful = [u for u in completed if outcome(u)[1]]
    attempted = [r for r in records if r.get('final_submit_attempted') is True]
    observed = []
    for u in done:
        observation = (posthoc or {}).get(u.get('id'))
        if observation and observation.get('status') == 'verified' and observation.get('verdict') is not None:
            observed.append(observation['verdict'] == 'AC')
    limit_runs = repeated_runs = 0
    tool_observed = 0
    for r in records:
        if 'tool_events' not in r: continue
        tool_observed += 1; failed = []; limit = False
        for e in r['tool_events']:
            result = e.get('result') or {}
            reason = result.get('reason')
            # Text is a diagnostic tag only, never Judge classification evidence.
            text = (result.get('stderr') or '') + (result.get('stdout') or '')
            limit |= reason in ('output_limit', 'memory_limit', 'timeout', 'cpu_timeout') or any(
                x in text for x in ('File too large', 'File size limit exceeded')) or e.get('error') == 'tool_request_rejected_413'
            if e.get('name') == 'terminal' and (result.get('returncode') not in (None, 0) or reason):
                failed.append(e['args']['command'])
        limit_runs += bool(limit)
        repeated_runs += len(failed) != len(set(failed))
    usages = [token_usage(r) for r in records]
    total = sum(x['input_tokens']+x['output_tokens'] for x in usages) if n and all(
        x['input_tokens'] is not None and x['output_tokens'] is not None for x in usages) else None
    return {
        'terminal_denominator': n,
        'end_to_end_success_rate': rate(len(successful)) if all('final_submission_completed' in r for r in records) else None,
        'submission_completion_rate': rate(len(completed)) if all('final_submission_completed' in r for r in records) else None,
        'submission_completed_count': len(completed),
        'submission_observation_unknown_count': sum('final_submission_completed' not in r for r in records),
        'valid_code_at_termination_rate': sum(observed)/len(observed) if observed else None,
        'valid_code_observed_count': len(observed), 'valid_code_unknown_count': n-len(observed),
        'valid_code_ac_count': sum(observed),
        'budget_exhaustion_rate': rate(sum(r.get('error') in ('model_call_budget','tool_call_budget','wall_time_budget') for r in records)),
        'final_submit_attempt_rate': rate(len(attempted)) if all('final_submit_attempted' in r for r in records) else None,
        'final_submit_attempt_unknown_count': sum('final_submit_attempted' not in r for r in records),
        'tool_limit_error_rate': limit_runs/tool_observed if tool_observed else None,
        'repeated_failed_command_rate': repeated_runs/tool_observed if tool_observed else None,
        'tool_diagnostic_observed_runs': tool_observed,
        'mean_model_calls_before_final_submit': mean([r['model_calls_before_final_submit'] for r in attempted if r.get('model_calls_before_final_submit') is not None]),
        'mean_tool_calls_before_final_submit': mean([r['tool_calls_before_final_submit'] for r in attempted if r.get('tool_calls_before_final_submit') is not None]),
        'tokens_per_completed_run': total/n if total is not None and n else None,
        'tokens_per_submission_completed_run': total/len(completed) if total is not None and completed else None,
        'tokens_per_successful_run': total/len(successful) if total is not None and successful else None,
        'observed_total_tokens': sum(x['input_tokens']+x['output_tokens'] for x in usages if all(v is not None for v in x.values())),
        'token_usage_unknown_runs': sum(any(v is None for v in x.values()) for x in usages),
        'mean_wall_time_per_run': mean([r['wall_time_seconds'] for r in records if r.get('wall_time_seconds') is not None]),
        'provider_failure_rate': rate(sum(outcome(u)[2]=='model_failure' for u in done)),
        'infrastructure_failure_rate': rate(sum(outcome(u)[2]=='infrastructure_failure' for u in done)),
        'definitions': {
            'rates': 'All terminal independent Runs form denominators unless explicitly marked observed-only. Pending/Running excluded. Missing observations are unknown, never false.',
            'end_to_end_success_rate': 'Explicit completed final submission with AC / terminal Runs; differs from compatibility metrics when legacy final-submit evidence is unavailable.',
            'submission_completion_rate': 'Final submission finished in budget, including non-AC / terminal Runs. An accepted but unfinished submission is not completion.',
            'valid_code_at_termination_rate': 'Post-hoc AC / independently verified termination snapshots (observed-only denominator); unknown count reported against all terminal Runs. Not an E2E score.',
            'tokens_per_completed_run': 'Total tokens across ALL terminal Runs / terminal Runs; null if any terminal usage missing.',
            'tokens_per_submission_completed_run': 'Total tokens across ALL terminal Runs / completed final submissions; null if any terminal usage missing.',
            'tokens_per_successful_run': 'Total tokens across ALL terminal Runs / completed final AC submissions; null if any terminal usage missing.',
            'tool_rates': 'Runs with at least one limit diagnostic / tool-observed terminal Runs; repeated = identical raw command fails more than once (no semantic equivalence claim). Text tags are not causal evidence.',
            'budget_exhaustion_rate': 'Terminal Runs with model/tool/wall budget failure / terminal Runs.',
            'call_means': 'Calls used including final_submit request, averaged among observed final-submit attempts.',
        },
    }
