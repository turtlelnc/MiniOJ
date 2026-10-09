"""Auditable prompt interventions; no resource enforcement or tool-schema changes."""
import copy
import hashlib
import json
import time

CONDITIONS = {
    'A': {'budget_visible': False, 'sandbox_visible': False, 'max_model_calls': 6},
    'B': {'budget_visible': True, 'sandbox_visible': False, 'max_model_calls': 6},
    'C': {'budget_visible': False, 'sandbox_visible': True, 'max_model_calls': 6},
    'D': {'budget_visible': True, 'sandbox_visible': True, 'max_model_calls': 6},
    'E': {'budget_visible': True, 'sandbox_visible': True, 'max_model_calls': 12},
}


def sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':')).encode()).hexdigest()


def sandbox_policy():
    # Reviewed frozen enforcement values, with hashes detecting policy drift.
    # CPU/wall budgets are different from contestant per-test limits.
    from minioj import config
    from minioj.workspace import WorkspaceManager
    paths = ['minioj/config.py', 'minioj/docker_backend.py', 'minioj/runner.py', 'minioj/launcher.py',
             'minioj/workspace.py', 'scripts/container_files.py', 'scripts/container_exec.py']
    result = {
        'language': 'C++17', 'compiler_flags': ['-O2', '-std=c++17'],
        'network': False, 'root_filesystem': 'read-only',
        'workspace': '/workspace', 'command_cwd': '/workspace (reset on every call)',
        'workspace_tmpfs_bytes': 64*1024*1024, 'tmp_tmpfs_bytes': 16*1024*1024,
        'tmp_execution': False, 'api_file_read_write_bytes': 262144,
        'submission_source_bytes': config.SOURCE_LIMIT,
        'command_output_bytes': config.OUTPUT_LIMIT,
        'run_output_bytes': WorkspaceManager.OUTPUT_BUDGET,
        'generated_regular_file_bytes': config.OUTPUT_LIMIT,
        'generated_file_rule': 'RLIMIT_FSIZE per file = min(command_output_bytes, remaining run_output_bytes); applies to compiler artifacts too',
        'command_wall_max_ms': 30000,
        'command_cpu_ms': 'same as requested command wall ms (min 100 ms)',
        'command_process_tree_rss_mb': 384,
        'command_linux_address_space_mb': 384*2+32,
        'workspace_container_memory_mb': 512,
        'workspace_wall_seconds': WorkspaceManager.WALL_SECONDS,
        'workspace_cgroup_cpu_seconds': WorkspaceManager.CPU_SECONDS,
        'pids_limit': 64,
        'judge_compile_wall_ms': 30000, 'judge_compile_process_tree_rss_mb': 640,
        'judge_compile_container_memory_mb': 768,
        'judge_compile_artifact_file_bytes': 1048576,
        'enforcement_sha256': {p: hashlib.sha256((config.ROOT/p).read_bytes()).hexdigest() for p in paths},
    }

    frozen = json.loads((config.ROOT/'benchmark/experiments/harness_ablation_v1/sandbox_policy.json').read_text())
    if result != frozen:
        raise ValueError('Sandbox enforcement/config drift; inspect actual limits and preregister a new policy')
    return result


def validate_harness(value, limits):
    if not isinstance(value, dict) or not {'condition', 'sandbox_policy'} <= set(value) or set(value) - {'condition', 'sandbox_policy', 'disclosure_version'}:
        raise ValueError('harness requires condition and frozen sandbox_policy')
    version = value.get('disclosure_version', 1)
    if type(version) is not int or version not in (1, 2):
        raise ValueError('Unsupported disclosure version')
    condition = value['condition']
    if condition not in CONDITIONS or limits['max_model_calls'] != CONDITIONS[condition]['max_model_calls']:
        raise ValueError('Condition/model budget mismatch')
    if limits['max_tool_calls'] != 16 or limits['max_wall_time_seconds'] != 180:
        raise ValueError('Ablation requires frozen tool/wall budgets')
    if value['sandbox_policy'] != sandbox_policy():
        raise ValueError('Sandbox policy drift; refreeze before execution')
    return copy.deepcopy(value)


def request_messages(messages, manifest, record, problem, remaining_wall):
    """One ephemeral system message before user/tool history, never between pairs.

    Called AFTER incrementing model_calls. Remaining model calls include the
    current response; its tools, including final_submit, may still execute.
    No old runtime messages are appended to the persistent model history.
    """
    harness = manifest.get('harness')
    if not harness:
        return messages
    condition = CONDITIONS[harness['condition']]
    limits = manifest['limits']; parts = []; budget = None
    if condition['budget_visible']:
        budget = {'model_total': limits['max_model_calls'],
                  'model_used_including_current': record['model_calls'],
                  'model_responses_remaining_including_current': max(0, limits['max_model_calls']-record['model_calls']+1),
                  'tool_total': limits['max_tool_calls'], 'tool_used': record['tool_calls'],
                  'tool_remaining': max(0, limits['max_tool_calls']-record['tool_calls']),
                  'run_wall_total_seconds': limits['max_wall_time_seconds'],
                  'run_wall_remaining_seconds': round(max(0, remaining_wall), 3)}
        parts.append('[Agent Runtime Budget]\n'+json.dumps(budget, sort_keys=True)+
                     '\nThe remaining model responses INCLUDE this response. Tools from this response can still run. '
                     'final_submit(main.cpp) is required to complete the task and ends this Run; no later model call follows it.')
    if condition['sandbox_visible']:
        public = {k: v for k, v in harness['sandbox_policy'].items() if k != 'enforcement_sha256'}
        public.update(judge_test_cpu_ms=problem['time_limit_ms'], judge_test_wall_ms=problem['time_limit_ms'],
                      judge_test_container_memory_mb=problem['memory_limit_mb'])
        parts.append('[Sandbox Boundaries]\n'+json.dumps(public, sort_keys=True)+
                     '\nIsolated Linux container; restricted filesystem; no network. Final submission source: main.cpp. '
                     'Container memory includes resident processes and tmpfs; process RSS is a separate sampled limit. '
                     'Shell exit(0) can hide an earlier command failure: use && to gate dependent commands.')
        if harness.get('disclosure_version', 1) == 2:
            parts.append('[File Tool Paths]\nread_file and write_file paths MUST be relative to /workspace. '
                         'Use problem.json or main.cpp, never /workspace/problem.json or /workspace/main.cpp. '
                         'Absolute paths may be used inside terminal shell commands.')
    content = '\n\n'.join(parts)
    event = {'model_call': record['model_calls'], 'at_unix': time.time(),
             'condition': harness['condition'], 'budget': budget,
             'content': content, 'content_sha256': hashlib.sha256(content.encode()).hexdigest(),
             'extra_utf8_bytes': len(content.encode()),
             'extra_tokens': None, 'token_method': 'unavailable: provider does not report injection-only token usage'}
    record.setdefault('harness_injections', []).append(event)
    if not content:
        return messages  # A: byte-for-byte legacy messages, no budget disclosure.
    return [messages[0], {'role': 'system', 'content': content}, *messages[1:]]
