# Phase 7 preregistration: budget awareness vs submission reminder

Baseline repository: e96d06a8761c46fb616973d209d77fa9d6a899a1. Registered before any Phase 7 paid calls; this stage authorizes offline/Fake execution only. No previous experiment is rewritten or pooled into this study.

## Research question and hypotheses

With model, tools, problems, enforcement and actual execution budgets held constant, does dynamic budget disclosure improve in-budget completion, does a static submission reminder improve completion, and do these factors interact? Directional screening hypotheses: each may increase submission completion; their effects may overlap. Prior Phase 6 budget notices contained a submission instruction, so their differences cannot isolate budget awareness. The hypotheses are fixed before Phase 7 real outcomes. No claim that correct code alone completes an Agent task.

## Common protocol and exact interventions

All groups use the same base system message:

```text
Solve the provided algorithm problem in the isolated Linux workspace using only the provided tools. read_file reads a workspace file; write_file writes a workspace file; terminal executes a shell command; final_submit evaluates main.cpp and ends the Run. Hidden results are not returned for further revisions.
```

An ephemeral second system message is inserted after this system message and before the unchanged user/history, on every request. It contains this exact common contract in all groups:

```text
[Common Workspace Contract]
Language: C++17. Source file: main.cpp. read_file/write_file require paths relative to /workspace; absolute paths are rejected by file tools. Use problem.json, main.cpp, sample.in and sample.out. terminal starts in /workspace on every call; absolute paths may be used inside shell commands. Compilation and public sample testing are allowed. Hidden tests are unavailable to the final_only Agent. No network; read-only container root; unprivileged user, dropped capabilities, no-new-privileges and no host Docker socket. Container memory includes resident processes and tmpfs; process RSS is separately sampled. Shell exit(0) can hide previous failures: use && for dependent commands.
{"api_file_read_write_bytes": 262144, "command_cpu_ms": "same as requested command wall ms (min 100 ms)", "command_cwd": "/workspace (reset on every call)", "command_linux_address_space_mb": 800, "command_output_bytes": 1048576, "command_process_tree_rss_mb": 384, "command_wall_max_ms": 30000, "compiler_flags": ["-O2", "-std=c++17"], "generated_file_rule": "RLIMIT_FSIZE per file = min(command_output_bytes, remaining run_output_bytes); applies to compiler artifacts too", "generated_regular_file_bytes": 1048576, "judge_compile_artifact_file_bytes": 1048576, "judge_compile_container_memory_mb": 768, "judge_compile_process_tree_rss_mb": 640, "judge_compile_wall_ms": 30000, "language": "C++17", "network": false, "pids_limit": 64, "root_filesystem": "read-only", "run_output_bytes": 4194304, "submission_source_bytes": 262144, "tmp_execution": false, "tmp_tmpfs_bytes": 16777216, "workspace": "/workspace", "workspace_cgroup_cpu_seconds": 120, "workspace_container_memory_mb": 512, "workspace_tmpfs_bytes": 67108864, "workspace_wall_seconds": 900}
```

The user message is the frozen PUBLIC problem snapshot. Hidden tests and original test contents never appear in messages or the final_only schema. read_file/write_file/terminal/final_submit definitions and their SHA256 are identical in every group. final_submit's existence, source filename, basic evaluation/end-Run semantics belong to the common minimum tool contract; no common instruction orders or prioritizes submission.

A = common only (B0 S0).
B = common + Runtime Budget (B1 S0).
C = common + Task Completion Reminder (B0 S1).
D = common + Runtime Budget + the same reminder ONCE (B1 S1).

Exact static reminder, C/D only:

```text
[Task Completion Reminder]
A solution is not complete until final_submit is called. After local verification, use final_submit to finish the task.
```

Budget block, B/D only, is `[Runtime Budget]` followed by sorted JSON of actual Runner counters: model_total, model_used_including_current, model_responses_remaining_including_current, tool_total, tool_used, tool_remaining, run_wall_total_seconds, run_wall_remaining_seconds; followed by exactly `Remaining model responses INCLUDE this response; its tools may execute.` No submission language appears in this block. A/C see none of these dynamic values. The model counter increments before request generation, so visible responses remaining is 6 on the first response and 1 on the sixth; tools from that final response, including final_submit, are still within budget. Tools increment before dispatch, remaining is clamped at zero. Wall remaining is measured from the Runner deadline, rounded to 3 decimals. Failures never decrement counters. Injections are regenerated, never stacked in persisted history or inserted inside an assistant/tool pair.

`python3 scripts/phase7.py --compare-prompts` produces actual constructed messages and A-relative textual diffs for every simulated model call (1–6). The same request function is called by the production Runner. Every actual injection records content SHA256, complete request SHA256, model-call index, timestamp, common/budget/reminder UTF-8 bytes, and null injection-only tokens (provider does not report them). Bytes never masquerade as billing tokens.

## Frozen study and allocation

5 Phase 6 original problems, keys C01–C05 mapped to original IDs from the trusted historical manifest, not hardcoded IDs. Full snapshot/test hashes, public prompt snapshots, case counts and titles are in execution_plan.json; hidden original content remains private. Original DeepSeek model, pinned Docker digest, unchanged Judge/security source hashes and Phase 6 fingerprint are preserved. The new whole runtime fingerprint is separately frozen because Harness code changes it; Judge byte compatibility is checked against the original commit.

40 independent Agent Runs: four groups × five problems × two repetitions; 10 units per group. All use final_only, C++17, model calls 6, tool calls 50, wall 300 seconds, temperature 0, max_tokens 4096. This deliberately differs from Phase 6 (tools 16, wall 180, temperature 0.2, max_tokens 2048; Phase 6 E allowed 12 model calls). Thus Phase 7 contrasts are within this study, not pooled cross-phase effects.

Ordering seed 20261010 generates eight temporal blocks, each containing every problem once. For each repetition/problem, an independently shuffled four-condition permutation assigns one condition per block. Problems are shuffled within blocks. Each same-problem repetition distributes the four conditions over four blocks instead of executing A/B/C/D contiguously. The committed order, unique planned IDs, ordinal, factors, requested seeds (1/2), limits and full initial prompt hash are authoritative. No reshuffle at runtime. Server-owned unit IDs are separately mapped to planned IDs in unit_mapping.json. Prompt freeze uses original problem ID; runtime allocation IDs are normalized only for comparison, never altered in actual messages. First-request freeze uses call=1/tools=0/wall=300; actual remaining wall differs and every actual request is independently hashed.

Temperature zero and requested seed do not ensure deterministic provider output. seed_effective is null for DeepSeek; repeats are fresh samples, not deterministic paired outputs. No favorable reruns or selection.

## Outcomes, denominators and statistical estimates

Primary: original explicit final-submit AC / all terminal independent Runs (Finished/Failed), including Agent/model/Judge/infrastructure failures. Pending/Running excluded; final planned-unit rate and factorial contrasts are null until all 40 are terminal.

Secondary: submission completion (final_submit finished with official verdict, including SE) / terminal; final-submit attempts / terminal; model/tool budget exhaustion / terminal (wall-clock exhaustion reported separately); and post-hoc AC / independently verified reliable snapshots, with unknown count reported against terminal units. Unknown rejudges remain null, never WA. Post-hoc verdicts never overwrite original records. Legacy metrics remain compatible; Phase 7 call-budget rate explicitly excludes wall-budget failure even though the legacy diagnostic combines them.

Total/input/output usage comes only from provider observations (Fake usage is synthetic). Missing usage remains null; tokens per E2E AC and per completed submission are total tokens across ALL terminal units divided by the corresponding observed count, null if any terminal usage is missing or denominator zero. No provider cost promised: no current price lookup or billing measurement is performed this stage.

Preregistered descriptive rate differences:
- Budget average = ((B−A)+(D−C))/2.
- Reminder average = ((C−A)+(D−B))/2.
- Interaction = (D−C)−(B−A).

Show group numerators/denominators, failure breakdowns, Pending/Running and per-problem results. No significance claim with ten Runs per condition and five problem clusters. Repeated Runs are not independent problems. No post-result changes to analysis, hidden tests, source protocol, reminder, ordering or budgets; no cross-phase pooling.

## Trajectory and snapshot evidence

Record model/tool calls, final_submit attempted/completed and terminal_reason. Exact last-code-change timing and subsequent calls are available only when successful API writes establish a content change from the known empty source and no terminal or unconfirmed write could mutate it. Any terminal command may write source/start a background writer; without source versioning these timing values are null. Rewriting identical content is not a code change. Do not infer when correct code first appeared. Public outputs carry conservative nulls rather than guessed timing.

Successful final sources are immutable submission snapshots. Failed-Run capture reuses the Phase 6 owned-container pause and trusted inspector; freeze precedes read, background writers cannot race capture, symlinks are rejected, and source hashes are verified. Capture failure is unknown. Freeze occurs after failure detection, so validity at freeze does not prove validity at the exact budget deadline. Independent post-hoc results have separate IDs/timestamps/tests/image/hash provenance. Run `scripts/posthoc_rejudge.py` per group's private trajectory, then `scripts/phase7.py --analyze` on separate outputs; no original DB updates.

## Stop conditions, safety and future authorization

This stage performs zero paid calls and never searches/reads model keys. Offline commands work without importing model adapters or production MiniOJ config. Fake mode uses only FakeModelAdapter and the existing real Docker Judge, private new DB, pinned image and session-specific cleanup.

Future real execution requires --real --authorize-paid, exact plan ID and explicit caps no greater than 40 Runs, 240 model calls and 600000 observed total tokens. The token threshold stops before another call; the last in-flight response can exceed it. 240 is a theoretical allowed call maximum, not expected consumption. Billing cost cannot be reliably bounded by an observed-token stop without prices/context accounting. There are no concurrent provider calls or automatic retries.

Provider failure, missing usage, observed token cap, global call cap or Judge/infrastructure failure stops new paid calls; unstarted units remain Pending. Per-Run exhaustion stays an Agent failure. Global orchestration deadline = authorized Runs × 300 + 60 seconds; provider timeout at most 60 seconds, terminal at most 30 seconds. Missing frozen inputs/image, enforcement/Judge/implementation drift fails explicitly; never substitute problems/images. Interruption cleanup retains evidence and terminates the isolated server/session containers. No privileged containers, socket exposure, isolation relaxation, production DB use, deletion of historical evidence or automatic GitHub push. A stopped partial execution cannot be silently restarted in a new directory.

Frozen files: execution_plan.json and its raw SHA256 manifest.sha256, conditions.json, this preregistration; plan embeds exact public prompt, model/settings, budgets, policy/Judge/Runner/adapter hashes and schedule. Any implementation change requires explicit preregistration/version review, never refreezing after observing real outcomes.

## Validation boundary

Compileall, unit tests, validate, compare-prompts, dry-run and Docker/Fake closure verify implementation and isolation. A separate real-Docker concurrent-writer/symlink acceptance verifies safe source capture. Fake AC proves pipeline function only, not either factor's effect on a real model. Real Phase 7 outcomes are unmeasured this stage.

Plan ID: 83d4c2b5ab8d2f80d801e7d6e8dd8c4ff92e95b5313cbc5173628b796cfc1bb6

Offline validation uses the committed Judge file SHA256 map and does not require old Git objects (supports CI shallow clones). Real execution still checks the historical Judge byte compatibility and actual private snapshots before creating Runs. Post-hoc analysis rejects mismatched source/test/image provenance as unknown.
