"""Frozen plan validation and hard opt-in guards; importing never reads keys."""
import json
import random
from pathlib import Path
from .harness import CONDITIONS, sha
from .protocol import SYSTEM_PROMPT, tools


def build_plan(experiment, order_seed=20261009):
    m=experiment['manifest']; problems=[]
    for p in m['problem_snapshots']:
        # No hidden text in the public preregistration/plan.
        problems.append({'original_problem_id':p['id'],'title':p['title'],
                         'snapshot_sha256':sha(p),'hidden_tests_sha256':sha(p['testcases']),
                         'test_count':len(p['testcases'])})
    schedule=[]; rng=random.Random(order_seed)
    # Independently randomized problem order and condition order in each block.
    order=list(range(len(problems)));rng.shuffle(order)
    for pi in order:
        cs=list(CONDITIONS);rng.shuffle(cs)
        schedule.extend({'problem_index':pi,'condition':c,'repetition':1,'requested_seed':1} for c in cs)
    plan={'version':1,'study':'harness_ablation_v1','classification':'exploratory screening, not a significance claim',
          'legacy_experiment_id':experiment['id'],'original_commit':m['git_commit'],
          'problems':problems,'conditions':CONDITIONS,
          'shared':{'provider':m['models'][0]['provider'],'model':m['models'][0]['model'],
                    'protocol':'final_only','temperature':m['temperature'],'max_tokens':m['max_tokens'],
                    'max_tool_calls':16,'max_wall_time_seconds':180,'tool_schema_sha256':sha(tools('final_only')),
                    'system_prompt_sha256':sha(SYSTEM_PROMPT),'image_id':m['environment_information']['image_id'],
                    'original_judge_fingerprint':m['environment_information']['source_fingerprint']},
          'random_order_seed':order_seed,'schedule':schedule,'planned_units':len(schedule),
          'maximum_model_calls':sum(CONDITIONS[x['condition']]['max_model_calls'] for x in schedule),
          'observed_token_stop_cap':350000,'missing_usage_policy':'stop before next model call',
          'paid_execution_default':False,'seed_effective':'unknown; provider does not promise seeded sampling'}
    plan['plan_id']=sha(plan)
    return plan


def validate_plan(plan, experiment=None):
    original={k:v for k,v in plan.items() if k!='plan_id'}
    if sha(original)!=plan.get('plan_id'):raise ValueError('Plan hash mismatch')
    if plan['conditions']!=CONDITIONS:raise ValueError('Condition drift')
    if plan['shared']['protocol']!='final_only' or plan['shared']['max_tool_calls']!=16 or plan['shared']['max_wall_time_seconds']!=180:
        raise ValueError('Shared protocol drift')
    if plan['shared']['system_prompt_sha256']!=sha(SYSTEM_PROMPT) or plan['shared']['tool_schema_sha256']!=sha(tools('final_only')):
        raise ValueError('Legacy prompt/schema drift')
    expected={(i,c,1) for i in range(len(plan['problems'])) for c in CONDITIONS}
    actual=[(x['problem_index'],x['condition'],x['repetition']) for x in plan['schedule']]
    if len(plan['problems'])!=5 or len(actual)!=25 or set(actual)!=expected or any(x['requested_seed']!=1 for x in plan['schedule']):
        raise ValueError('Invalid 25-Run allocation')
    count=sum(CONDITIONS[x['condition']]['max_model_calls'] for x in plan['schedule'])
    if plan['planned_units']!=25 or plan['maximum_model_calls']!=count:raise ValueError('Scale mismatch')
    if experiment and build_plan(experiment,plan['random_order_seed'])!=plan:raise ValueError('Historical frozen inputs differ')
    return {'status':'passed','plan_id':plan['plan_id'],'planned_units':25,'maximum_model_calls':count}


class ExecutionGuard:
    def __init__(self, max_calls, max_tokens):
        self.max_calls=max_calls;self.max_tokens=max_tokens;self.calls=0;self.tokens=0;self.stop_reason=None
    def before_model(self):
        from .runner import AgentFailure
        if self.stop_reason or self.calls>=self.max_calls or self.tokens>=self.max_tokens:
            self.stop_reason=self.stop_reason or 'global_execution_cap';raise AgentFailure(self.stop_reason)
        self.calls+=1
    def after_model(self, usage):
        if not isinstance(usage,dict) or any(type(usage.get(k)) is not int or usage[k]<0 for k in ('input_tokens','output_tokens')):
            self.stop_reason='usage_unavailable';return
        self.tokens+=usage['input_tokens']+usage['output_tokens']
        if self.tokens>=self.max_tokens:self.stop_reason='observed_token_cap'
        elif self.calls>=self.max_calls:self.stop_reason='global_model_call_cap'


def authorize(args, plan):
    """Explicit limits are mandatory even when a credential happens to exist."""
    if not args.authorize_paid or args.plan_id!=plan['plan_id']:
        raise ValueError('Paid execution needs explicit --authorize-paid and frozen --plan-id')
    if not 1<=args.max_runs<=plan['planned_units'] or not 1<=args.max_model_calls<=plan['maximum_model_calls'] or not 1<=args.max_observed_tokens<=plan['observed_token_stop_cap']:
        raise ValueError('Explicit execution caps must not exceed preregistered caps')
    return ExecutionGuard(args.max_model_calls,args.max_observed_tokens)
