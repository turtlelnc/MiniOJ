# Phase 7 validation — 2026-10-09

Baseline HEAD: `e96d06a8761c46fb616973d209d77fa9d6a899a1`. This delivery implements a frozen 2×2 experiment, not real-model results. No paid provider calls, no model key access and no push were performed.

## Actual prompt differences

All groups share the new minimum system message and exact Common Workspace Contract (relative file paths, C++17, tool purposes, main.cpp, public sample use, no hidden feedback, real file/output/memory restrictions and identical isolation). Existing Phase 6 SYSTEM_PROMPT is unchanged for old experiments.

| Group | Dynamic budget | Extra static submission reminder |
|---|---|---|
| A | no | no |
| B | yes | no |
| C | no | yes |
| D | yes | yes, once |

The budget block contains actual model/tool counters and remaining wall time; it has no final_submit instruction. Reminder: `A solution is not complete until final_submit is called. After local verification, use final_submit to finish the task.` Minimal common protocol merely explains the final_submit tool's purpose. Exact texts, all simulated request rounds and initial full request hashes are in preregistration/execution_plan and compare-prompts evidence. Dynamic messages are ephemeral system messages before unchanged user/history, never persisted budget stacks.

## Frozen configuration and provenance

- 40 units = 5 original problems × A/B/C/D × repetitions 1/2; each group 10. Actual original IDs parsed from history, server IDs mapped separately. Eight pseudorandom temporal blocks (ordering seed 20261010), fixed unit IDs/order, no runtime reshuffle. Same requested seeds are not deterministic pairing.
- DeepSeek model ID `deepseek-flash`, final_only, C++17; every group: model calls 6, tools 50, wall 300 seconds, temperature 0, max_tokens 4096. Phase 6 differed (tools 16, wall 180, temperature 0.2, max_tokens 2048; E allowed 12 calls). No cross-phase pooling.
- Plan ID: `83d4c2b5ab8d2f80d801e7d6e8dd8c4ff92e95b5313cbc5173628b796cfc1bb6`.
- Raw manifest SHA256: `6f26eefa26c3a287c2b8d8c3c734f5c9498dd56cac37519dc4f295b7e20dfc6e`.
- Docker image: `sha256:7a5d27699ebab1b98fa78730b655619eb78a655d2e73698ed218e45717f7a638` (same original image, no rebuild/substitution).
- Original Phase 6 whole Judge/runtime fingerprint: `d11a6f4cbaa05259a6d1cf49a5ce22498992f3e99edc9d4d294853a5fddd5bdc`. Judge/security source bytes are unchanged; individual hashes are embedded in plan.
- New whole runtime fingerprint: `184088cfce567ed0ff3c55a9557d9d0edf06fc0b3ed4036906c2c85b5fa36f16`, equal across all groups. It changes because Harness code changes; this is separately recorded, not claimed byte-identical to the old entire runtime.

| Key | Original ID | Title | Cases | Snapshot SHA256 | Hidden-test SHA256 |
|---|---|---|---|---|---|
| C01 | 1 | 区间和 | 12 | `d0fbdb0438a48c5b4ef4626b904566f171522a78006e5c29ec97e7eaf96ce1d3` | `cd72bce6352956a865d2921b29ffa0a85d49cd86e6065da48dacb573f98700fa` |
| C02 | 2 | 严格最长递增子序列 | 13 | `2692eb7ce420fc1d4c362850d602dd0be46517019e50f6aab70a8041cdeaa5b2` | `639bb96f2028cc081b908bae11deb5a5ba7156067299b4bd0bea8dc111fcb12e` |
| C03 | 3 | 无权图最短路 | 12 | `ba3f064dedea2b2610a48fe94463ce580e4d5c173dd07248e3574f1ae414bb55` | `cf787bb3716a6813f9b276b0005a6721f38263a99af2ef63e94dbd5f60af2f6c` |
| C04 | 4 | 0/1背包 | 12 | `975b8bd45eeb67fb1f45a1bbb71899f3f6ea3676b1c504e2906c1fbc87b5f3fd` | `a0bdb9634c0d4e6bbf9f29246fe88d22c2d0a423c8d5b829312aeaee430f95cb` |
| C05 | 5 | 非负权有向图单源最短路 | 13 | `c07904994fef5d5a7e9ef00697d2a02fa4eba89a24f74040edb0c970cee85217` | `6e4fe8bf09af3fcb253963e31df5581ad4905645b3eee74ca785683b08a929bd` |

Complete problem/test and initial prompt hashes, implementation/adapter hashes and exact public problem text are in [execution_plan.json](../benchmark/experiments/termination_ablation_v1/execution_plan.json). Private historical snapshots remain local; no hidden text is committed.

## Actual verification

- `python3 -m compileall -q minioj benchmark scripts`: passed.
- `python3 -m unittest discover -s tests -v`: 141 passed, 0 failed, 0 skipped.
- `python3 scripts/phase7.py --validate`: 40 units and frozen inputs passed.
- `--compare-prompts`: all six simulated call rounds, actual messages and A-relative diffs passed.
- `--dry-run`: 40 units, four groups × 10, synthetic sequence and JSON/CSV IDs/status/statistics passed; no live source snapshots claimed.
- Final Docker/Fake closure: 40/40 AC, 496 official Judge test points; 160 model and 160 tool calls, 3200 synthetic tokens. Same fixed Docker digest, separate private DB, all four model settings/schema/runtime hashes consistent, API/JSON/CSV equal. All original final submissions preserved. No independent posthoc rejudge was performed on these successful Fake submissions; posthoc remains null/40 unknown, despite immutable sources being available.
- Real Docker concurrent-writer snapshot acceptance: passed; pause precedes copy, repeated hash stable, symlink rejected, owned containers cleaned up. No host socket or privileged container added.
- 176 historical Phase 6/old model artifacts unchanged by SHA256. Existing database/user data untouched.
- First pre-audit Docker/Fake closure also passed 40/40 and is retained at `evidence/termination_ablation_v1/fake-20261009-v1`. Review then fixed offline dependence on historical Git objects for shallow CI clones and hardened posthoc provenance validation; final closure reran with the final plan. Prompt wording and budgets did not change, and no real outcome was used for refreezing.

Evidence: `evidence/termination_ablation_v1/fake-20261009-final/` (raw original public exports, private trajectories/DB, planned/runtime unit mapping, audit and analysis); `validation-20261009/` (unit log/validate/prompt comparisons/dry-run/history hashes); `snapshot-20261009.json` (real Docker race safety). Worktree validation provenance includes source fingerprint and the pre-commit diff; the frozen source files are included in the delivery commit.

## Metrics and conservative diagnostics

E2E AC numerator is explicit completed final-submit AC; denominator is all terminal Runs, including Agent/model/Judge/infrastructure failures. Submission completion includes official non-AC/SE results; attempts include unsuccessful calls. Phase 7 budget exhaustion includes model/tool caps; wall exhaustion is separate. Pending/Running never count as failures; planned final rate/factorial effects remain null until all units terminal.

Posthoc correctness is independent verified snapshot AC / verified snapshots; unknown count is reported against terminal units. Wrong source/test/image provenance is unknown. Original verdicts are never overwritten. Last-code-change and subsequent-call timing are null for any terminal/unconfirmed-write Run because shell/background source versions are unobserved; all 40 Fake timing records correctly remain null. Identical rewrites are not changes. No first-correct-code timestamp inferred.

Token ratios use provider usage across ALL terminal Runs divided by E2E AC/completed submissions; missing terminal usage makes ratios null. Fake usage is synthetic. Budget/common/reminder UTF-8 byte overhead recorded separately; intervention-only provider tokens unobservable/null. No dollar cost was measured or promised.

Budget average = ((B−A)+(D−C))/2; reminder average = ((C−A)+(D−B))/2; interaction = (D−C)−(B−A). All are descriptive rate differences. Show per-problem outcomes and group numerators/denominators. Five problem clusters with two repetitions each do not justify an independent-problem significance claim. Fake's zero contrasts prove pipeline only, not real-model effects. Compatibility pass@1 still uses the first configured seed; intra-Run modifications are not independent samples.

## Future explicitly authorized execution — NOT run this stage

```bash
.venv/bin/python scripts/phase7.py --real --authorize-paid \
  --plan-id 83d4c2b5ab8d2f80d801e7d6e8dd8c4ff92e95b5313cbc5173628b796cfc1bb6 \
  --max-runs 40 --max-model-calls 240 --max-observed-tokens 600000 \
  --output evidence/termination_ablation_v1/NEW-real-output
```

Only run after explicit user authorization and securely supplying the model credential outside tracked files. Missing or changed historical data/pinned image/implementation/Judge fails explicitly. Max 240 is theoretical, not estimated consumption. Observed token cap can overshoot on the final response; no fixed API bill guarantee. Missing usage/provider/Judge/infrastructure failure stops paid calls; remaining units stay Pending. No retries or automatic continuation; each output directory must be new.

Independent posthoc diagnostics, after execution, one command per group:

```bash
.venv/bin/python scripts/posthoc_rejudge.py \
  --experiment evidence/termination_ablation_v1/NEW-real-output/private/A-trajectories.json \
  --output evidence/termination_ablation_v1/NEW-real-output/A-posthoc.json
# Repeat for B/C/D. Then write a NEW analysis file, never original results.
python3 scripts/phase7.py --analyze \
  --evidence evidence/termination_ablation_v1/NEW-real-output \
  --output evidence/termination_ablation_v1/NEW-analysis.json
```

## Modified files and unverified scope

New: benchmark/termination.py, benchmark/termination_metrics.py, scripts/phase7.py, tests/test_phase7.py; four termination_ablation_v1 registration files; this document.
Updated: benchmark/harness.py (study dispatch), runner.py (conservative observations), storage.py (common configuration guard), reports.py (Phase 7-only CSV additions), scripts/harness_ablation.py (shared orchestration generalized, no duplicate Runner), tests/test_harness_ablation.py (shared test helper), README.md.

No GitHub Actions run or hosted x86 Docker validation of this delivery commit was obtained; offline shallow-history behavior is covered by regression tests. Real Docker validation ran in the existing ARM64 Colima Linux VM on macOS. The original ARM image is intentionally not replaced for another platform. Real DeepSeek Phase 7 effects, model-version stability, true intervention-only token cost, precise shell mutation times and billing are unmeasured. All experiment services and Colima are shut down after validation.
