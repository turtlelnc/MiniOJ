"""Phase 7 factorial intervention; shares the existing Runner and sandbox."""
import copy
import hashlib
import json
import random
import time
from pathlib import Path
from .harness import sha
from .protocol import tools

STUDY = 'termination_ablation_v1'
CONDITIONS = {
    'A': {'budget_visible': False, 'submit_reminder': False},
    'B': {'budget_visible': True, 'submit_reminder': False},
    'C': {'budget_visible': False, 'submit_reminder': True},
    'D': {'budget_visible': True, 'submit_reminder': True},
}
LIMITS = {'max_model_calls': 6, 'max_tool_calls': 50, 'max_wall_time_seconds': 300}
SYSTEM = ('Solve the provided algorithm problem in the isolated Linux workspace using only the provided tools. '
          'read_file reads a workspace file; write_file writes a workspace file; terminal executes a shell command; '
          'final_submit evaluates main.cpp and ends the Run. Hidden results are not returned for further revisions.')
REMINDER = ('[Task Completion Reminder]\nA solution is not complete until final_submit is called. '
            'After local verification, use final_submit to finish the task.')
ROOT = Path(__file__).resolve().parent.parent
IMPLEMENTATION_FILES = ('benchmark/runner.py', 'benchmark/termination.py', 'benchmark/harness.py',
                        'benchmark/protocol.py', 'benchmark/adapters/__init__.py',
                        'benchmark/adapters/deepseek.py', 'benchmark/adapters/fake.py',
                        'benchmark/termination_metrics.py', 'benchmark/snapshots.py',
                        'scripts/harness_ablation.py', 'scripts/phase7.py', 'benchmark/storage.py',
                        'benchmark/reports.py', 'benchmark/diagnostics.py', 'benchmark/metrics.py',
                        'benchmark/ablation.py', 'benchmark/posthoc.py')


def implementation_hashes():
    return {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in IMPLEMENTATION_FILES}


def frozen_policy():
    # Offline validation never imports minioj.config or reads credentials/DB.
    policy=json.loads((ROOT/'benchmark/experiments/harness_ablation_v1/sandbox_policy.json').read_text())
    for path,digest in policy['enforcement_sha256'].items():
        if hashlib.sha256((ROOT/path).read_bytes()).hexdigest()!=digest:
            raise ValueError('Frozen enforcement source drift')
    return policy


def runtime_fingerprint():
    digest=hashlib.sha256()
    for path in sorted([*(ROOT/'minioj').glob('*.py'),*(ROOT/'benchmark').rglob('*.py'),
                        *(ROOT/'scripts').glob('container_*.py'),ROOT/'Dockerfile']):
        digest.update(str(path.relative_to(ROOT)).encode());digest.update(path.read_bytes())
    return digest.hexdigest()


def common_contract(policy):
    public = {k: v for k, v in policy.items() if k != 'enforcement_sha256'}
    return ('[Common Workspace Contract]\nLanguage: C++17. Source file: main.cpp. '
            'read_file/write_file require paths relative to /workspace; absolute paths are rejected by file tools. '
            'Use problem.json, main.cpp, sample.in and sample.out. terminal starts in /workspace on every call; '
            'absolute paths may be used inside shell commands. Compilation and public sample testing are allowed. '
            'Hidden tests are unavailable to the final_only Agent. No network; read-only container root; '
            'unprivileged user, dropped capabilities, no-new-privileges and no host Docker socket. '
            'Container memory includes resident processes and tmpfs; process RSS is separately sampled. '
            'Shell exit(0) can hide previous failures: use && for dependent commands.\n'
            + json.dumps(public, sort_keys=True))


def validate_harness(value, limits):
    if set(value) != {'study', 'condition', 'sandbox_policy', 'implementation_sha256'}:
        raise ValueError('Invalid termination harness fields')
    if value['study'] != STUDY or value['condition'] not in CONDITIONS or limits != LIMITS:
        raise ValueError('Termination condition or budget drift')
    if value['sandbox_policy'] != frozen_policy() or value['implementation_sha256'] != implementation_hashes():
        raise ValueError('Termination enforcement/implementation drift')
    return copy.deepcopy(value)


def request_messages(messages, manifest, record, problem, remaining_wall):
    harness = manifest['harness']; condition = CONDITIONS[harness['condition']]
    parts = [common_contract(harness['sandbox_policy'])]
    budget = None
    if condition['budget_visible']:
        budget = {'model_total': LIMITS['max_model_calls'],
                  'model_used_including_current': record['model_calls'],
                  'model_responses_remaining_including_current': max(0, LIMITS['max_model_calls']-record['model_calls']+1),
                  'tool_total': LIMITS['max_tool_calls'], 'tool_used': record['tool_calls'],
                  'tool_remaining': max(0, LIMITS['max_tool_calls']-record['tool_calls']),
                  'run_wall_total_seconds': LIMITS['max_wall_time_seconds'],
                  'run_wall_remaining_seconds': round(max(0, remaining_wall), 3)}
        parts.append('[Runtime Budget]\n'+json.dumps(budget, sort_keys=True)+
                     '\nRemaining model responses INCLUDE this response; its tools may execute.')
    if condition['submit_reminder']:
        parts.append(REMINDER)
    content = '\n\n'.join(parts)
    record.setdefault('harness_injections', []).append({
        'model_call': record['model_calls'], 'at_unix': time.time(), 'condition': harness['condition'],
        'budget': budget, 'content': content, 'content_sha256': hashlib.sha256(content.encode()).hexdigest(),
        'extra_utf8_bytes': len(content.encode()), 'common_utf8_bytes':len(parts[0].encode()),
        'budget_utf8_bytes':len(parts[1].encode()) if condition['budget_visible'] else 0,
        'reminder_utf8_bytes':len(REMINDER.encode()) if condition['submit_reminder'] else 0,
        'extra_tokens': None,
        'token_method': 'unavailable: provider does not report injection-only usage'})
    request=[messages[0], {'role': 'system', 'content': content}, *messages[1:]]
    record['harness_injections'][-1]['request_sha256']=sha(request)
    return request


def prompt_preview(condition, policy, model_call=1, tool_calls=0, remaining_wall=300, problem=None):
    manifest = {'harness': {'condition': condition, 'sandbox_policy': policy}, 'limits': LIMITS}
    record = {'model_calls': model_call, 'tool_calls': tool_calls}
    messages=[{'role':'system','content':SYSTEM}]
    if problem is not None:messages.append({'role':'user','content':json.dumps(problem,ensure_ascii=False)})
    return request_messages(messages, manifest, record, problem or {}, remaining_wall)


def build_plan(experiment, order_seed=20261010, _offline_judge=None):
    m = experiment['manifest']; policy = frozen_policy(); problems = []
    for i, p in enumerate(m['problem_snapshots']):
        problems.append({'problem_key': f'C{i+1:02}', 'original_problem_id': p['id'], 'title': p['title'],
                         'snapshot_sha256': sha(p), 'hidden_tests_sha256': sha(p['testcases']),
                         'test_count': len(p['testcases']),
                         'public_snapshot':{**{k:v for k,v in p.items() if k not in ('testcases','deleted')},
                                            '_judge_image':m['environment_information']['image_id'],
                                            '_judge_fingerprint':runtime_fingerprint()}})
    implementation = implementation_hashes()
    from .posthoc import judge_compatibility,JUDGE_FILES
    if _offline_judge is None:
        judge = judge_compatibility(ROOT,m['git_commit'])
    else:
        current={path:hashlib.sha256((ROOT/path).read_bytes()).hexdigest() for path in JUDGE_FILES}
        if current!=_offline_judge:raise ValueError('Frozen Judge file hash drift')
        judge={'compatible':True,'files_sha256':current}
    if not judge['compatible']:raise ValueError('Frozen Judge unavailable: '+judge['reason'])
    plan = {'version': 1, 'study': STUDY, 'baseline_commit': 'e96d06a8761c46fb616973d209d77fa9d6a899a1',
            'original_commit': m['git_commit'], 'legacy_experiment_id': experiment['id'],
            'problems': problems, 'conditions': CONDITIONS, 'sandbox_policy': policy,
            'runtime_fingerprint':runtime_fingerprint(), 'implementation_sha256': implementation, 'judge_files_sha256': judge['files_sha256'],
            'shared': {'provider': m['models'][0]['provider'], 'model': m['models'][0]['model'],
                       'protocol': 'final_only', 'temperature': 0, 'max_tokens': 4096, **LIMITS,
                       'tool_schema_sha256': sha(tools('final_only')), 'system_prompt_sha256': sha(SYSTEM),
                       'common_contract_sha256': sha(common_contract(policy)), 'reminder_sha256': sha(REMINDER),
                       'image_id': m['environment_information']['image_id'],
                       'original_judge_fingerprint': m['environment_information']['source_fingerprint']},
            'random_order_seed': order_seed, 'planned_units': 40, 'maximum_model_calls': 240,
            'observed_token_stop_cap': 600000, 'missing_usage_policy': 'stop before next model call',
            'paid_execution_default': False, 'seed_effective': None,
            'prompt_hash_method': 'canonical JSON SHA256 of full initial system+user request at call=1/tools=0/wall=300, original problem ID; runtime allocated ID mapped separately. All actual requests also hashed; dynamic counter values change later request hashes',
            'schedule': []}
    plan['schedule'] = _schedule_from_public(plan)
    plan['plan_id'] = sha(plan)
    return plan


def validate_plan(plan, experiment=None):
    if sha({k: v for k, v in plan.items() if k != 'plan_id'}) != plan.get('plan_id'):
        raise ValueError('Plan hash mismatch')
    if plan.get('study') != STUDY or plan['conditions'] != CONDITIONS or plan['implementation_sha256'] != implementation_hashes():
        raise ValueError('Frozen implementation/conditions drift')
    if plan['sandbox_policy'] != frozen_policy() or plan['runtime_fingerprint']!=runtime_fingerprint():raise ValueError('Sandbox/runtime drift')
    # Reconstruct using ONLY public frozen inputs when private history unavailable.
    if experiment is None:
        original = json.loads((ROOT/'benchmark/experiments/harness_ablation_v1/execution_plan.json').read_text())
        for key in ('provider','model','image_id','original_judge_fingerprint'):
            if plan['shared'][key]!=original['shared'][key]:raise ValueError('Historical model/Judge/image drift')
        if plan['original_commit']!=original['original_commit'] or plan['legacy_experiment_id']!=original['legacy_experiment_id']:
            raise ValueError('Historical experiment drift')
        metadata=[{k:v for k,v in p.items() if k!='public_snapshot'} for p in plan['problems']]
        if metadata != [{**p, 'problem_key': f'C{i+1:02}'} for i,p in enumerate(original['problems'])]:
            raise ValueError('Phase 6 problem identities differ')
        mock = {'id': plan['legacy_experiment_id'], 'manifest': {
            'git_commit': plan['original_commit'], 'models': [{'provider': plan['shared']['provider'], 'model': plan['shared']['model']}],
            'environment_information': {'image_id': plan['shared']['image_id'], 'source_fingerprint': plan['shared']['original_judge_fingerprint']},
            'problem_snapshots': []}}
        # Validate all scalar fields and schedule using a reconstructed plan with trusted problem metadata.
        expected = build_plan(mock, plan['random_order_seed'],_offline_judge=plan['judge_files_sha256'])
        expected['problems'] = plan['problems']
        expected['schedule'] = _schedule_from_public(plan)
        expected['plan_id'] = sha({k:v for k,v in expected.items() if k!='plan_id'})
    else:
        expected = build_plan(experiment, plan['random_order_seed'])
    if expected != plan:raise ValueError('Frozen study inputs/schedule differ')
    return {'status': 'passed', 'plan_id': plan['plan_id'], 'planned_units': 40, 'maximum_model_calls': 240,
            'paid_calls': 0, 'image_validation': 'identity frozen; runtime availability checked before execution'}


def _schedule_from_public(plan):
    # Same allocation generator, using hashes instead of hidden texts.
    rng=random.Random(plan['random_order_seed']); schedule=[]
    for repetition in (1,2):
        orders=[rng.sample(list(CONDITIONS),4) for _ in plan['problems']]
        for block in range(4):
            pis=list(range(len(plan['problems'])));rng.shuffle(pis)
            for pi in pis:
                c=orders[pi][block];p=plan['problems'][pi]
                unit={'problem_index':pi,'problem_key':p['problem_key'],'original_problem_id':p['original_problem_id'],
                      'snapshot_sha256':p['snapshot_sha256'],'hidden_tests_sha256':p['hidden_tests_sha256'],
                      'condition':c,'repetition':repetition,'requested_seed':repetition,'seed_effective':None,
                      'model':plan['shared']['model'],'protocol':'final_only',**LIMITS,**CONDITIONS[c],
                      'execution_ordinal':len(schedule),'temporal_block':(repetition-1)*4+block,
                      'prompt_sha256':sha(prompt_preview(c,plan['sandbox_policy'],problem=p['public_snapshot'])),
                      'runner_adapter_sha256':implementation_hashes()}
                unit['unit_id']=sha(unit);schedule.append(unit)
    return schedule
