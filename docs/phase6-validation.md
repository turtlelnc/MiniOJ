# Phase 6 delivery / validation (2026-10-09)

Development and offline validation completed. No API key read/copied/printed; no paid model calls; no GitHub push. Local raw evidence is ignored, historical data is unchanged. Research effects remain untested.

## Changes

- `benchmark/harness.py`: A–E disclosure mechanism, ephemeral notices, true counters/current-response timing, content hashes, bytes and unavailable token-attribution field.
- `benchmark/ablation.py`: immutable plan verification, randomized allocation, explicit global Run/call/observed-token authorization caps.
- `benchmark/runner.py`: intervention integration, selective unit scheduling, private tool trace, final submission diagnostics, guarded paid calls, immutable/frozen source capture and cleanup despite checkpoint failure.
- `benchmark/snapshots.py`: local trusted capture pauses the owned container; a tightly restricted trusted inspector reads tmpfs via /proc/1/root. Target user processes remain paused; no Docker socket or host mount is exposed. Missing ownership/runtime/invalid source is unknown.
- `benchmark/diagnostics.py`, `benchmark/metrics.py`: additive completion, code-validity, budget/tool/error/cost diagnostics. Existing statistics stay intact.
- `benchmark/storage.py`: validated immutable Harness manifest; public exports redact source snapshots and private tool arguments. No DB schema change or migration needed.
- `benchmark/posthoc.py`: reliable source recovery, source/test hashes, pinned image, baseline Judge/security compatibility, distinct ID/UTC time and unavailable reasons. No DB update path.
- `benchmark/experiments/harness_ablation_v1/{conditions.json,execution_plan.json,sandbox_policy.json,legacy_review.json,preregistration.md}`: frozen settings, private-evidence review hashes, policy drift detection and preregistration.
- `scripts/{harness_ablation.py,audit_legacy_runs.py,posthoc_rejudge.py,harness_snapshot_acceptance.py}`: offline validation, real Docker Fake loop, read-only historical audit, isolated rejudge, concurrent writer/symlink acceptance.
- `tests/{test_harness_ablation.py,test_posthoc_rejudge.py}`, `README.md`, this document.

## Historical findings

Original E2E remains **4/15**. The 11 failed Runs retain **agent_failure/model_call_budget**; the old post-hoc AC remains **11/11**. 88 model calls, 94 tools, 173061 total observed tokens. All 15 terminal records were audited; immutable submitted source was recovered read-only for the four original AC cases. Eleven failed sources match reviewed last successful writes and saved candidate artifacts; all later terminal commands were manually checked for main.cpp mutation, and the review seals the complete original trajectory hash.

Eight failed Runs (3,5,6,7,8,12,13,14) show file-limit errors before exhaustion. The exact limit is launcher RLIMIT_FSIZE, set from command output cap (up to 1 MiB and shrinking with the remaining 4 MiB Run output budget). It limits generated regular files and compiler artifacts, distinct from the 256 KiB file API/source cap, 64 MiB workspace tmpfs and 16 MiB noexec /tmp. Run 9 encountered /tmp noexec; Run 10 had relative-path errors and an incorrect auxiliary expected answer; Run 0 fixed a missing include.

Confirmed: terminal category/counters, tool errors, no final submission on the 11 failures. High-confidence inference: gated compilation succeeded, reviewed final code formed before exhaustion, no later main.cpp changes. Unconfirmed: whether disclosure would change behavior, whether any specific error causally blocked submission, or whether additional testing was unnecessary. No hidden reasoning is inferred.

Old rejudge evidence lacked individual diagnostic IDs/timestamps/fingerprints. The new standalone tool independently rejudged all 11 failures with the same reviewed sources, frozen original cases and original image: **11 AC / 137 test points**. Each now has its own ID, UTC time, source/test hashes and unchanged-Judge compatibility record. Four originally successful Runs were not rejudged by this tool (no reviewed legacy failed-source snapshot); their independent-posthoc status remains unknown, not false.

| ordinal | problem | requested seed | original result | model calls | tools | input / output tokens | file-limit observations | legacy posthoc |
|---:|---:|---:|---|---:|---:|---|---:|---|
| 0 | 1 | 1 | model_call_budget | 6 | 6 | 10590 / 858 | 0 | AC |
| 1 | 1 | 2 | AC | 6 | 6 | 11127 / 867 | 0 | not rejudged |
| 2 | 1 | 3 | AC | 6 | 6 | 11067 / 850 | 0 | not rejudged |
| 3 | 2 | 1 | model_call_budget | 6 | 7 | 11142 / 883 | 1 | AC |
| 4 | 2 | 2 | AC | 5 | 5 | 6689 / 529 | 0 | not rejudged |
| 5 | 2 | 3 | model_call_budget | 6 | 7 | 11103 / 956 | 2 | AC |
| 6 | 3 | 1 | model_call_budget | 6 | 6 | 10523 / 1069 | 1 | AC |
| 7 | 3 | 2 | model_call_budget | 6 | 6 | 10445 / 1016 | 1 | AC |
| 8 | 3 | 3 | model_call_budget | 6 | 6 | 10488 / 1020 | 1 | AC |
| 9 | 4 | 1 | model_call_budget | 6 | 7 | 11474 / 877 | 0 | AC |
| 10 | 4 | 2 | model_call_budget | 6 | 7 | 11456 / 877 | 0 | AC |
| 11 | 4 | 3 | AC | 5 | 6 | 8722 / 722 | 0 | not rejudged |
| 12 | 5 | 1 | model_call_budget | 6 | 6 | 9826 / 1005 | 1 | AC |
| 13 | 5 | 2 | model_call_budget | 6 | 6 | 9910 / 1025 | 1 | AC |
| 14 | 5 | 3 | model_call_budget | 6 | 7 | 14127 / 1818 | 1 | AC |

The structured audit also records run_id/unit_id, source SHA256/provenance, compile evidence, final-submit observation and remaining budgets. Private files: `evidence/harness_ablation_v1/{legacy_audit.json,posthoc-independent.json,posthoc-diagnostics.json}`. No hidden tests or message text are published here.

## Conditions / outcomes

A: 6 calls, legacy messages. B: 6 + budget. C: 6 + sandbox. D: 6 + both. E: 12 + both. All groups keep 16 tools, 180 seconds, final_only, temperature 0.2, max_tokens 2048, original tool schema, image, compiler flags and real limits. E−D is an increased-budget contrast. Disclosures never accumulate in persistent model history or break tool result pairing. A receives no new information.

Diagnostic E2E AC and submission-completion rates use all terminal independent Runs; Pending/Running stay separate. Submission completion includes terminal non-AC/SE submissions finished within budget. Legacy missing final-submit observations are unknown (new diagnostic rates null) while old compatible E2E fields remain unchanged. Post-hoc validity uses verified snapshots as its observed denominator and separately reports unknown count against all terminal Runs. It never changes E2E.

Budget exhaustion/final-submit attempt/provider/infrastructure failure rates use terminal Runs. Tool-limit/repeated-command rates use tool-observed terminal Runs (exact raw command repetition). Calls before submission include the submission request. Tokens per completed Run = all terminal usage / terminal Runs; tokens per successful Run = all terminal usage / final AC Runs; tokens per completed submission is a separate field. Missing usage makes these total-cost ratios null. Wall mean uses observed terminal wall times. Compatibility pass@1 stays the first configured seed among evaluable independent Runs, not per-revision code accuracy.

## Actual validation

- `python3 -m compileall -q minioj benchmark scripts`: passed.
- `python3 -m unittest discover -s tests -v`: **118 passed, 0 failed, 0 skipped** (97 existing +21 new).
- Plan/config validation and dry-run: passed, no provider calls; randomized committed 25-unit order and cap 180 calls verified.
- Real Linux Docker inside macOS Colima, original arm64 sandbox image: **25 Fake Runs / 25 AC / 310 Judge test points**. Each condition 5/5 complete; 100 Fake model calls. Fake token usage is synthetic (2000), not paid/provider usage. API/local JSON and CSV match. Current shared fingerprint, image and policy invariants independently checked across all exports. Server stopped, no session containers remain.
- Real Docker snapshot acceptance: concurrent source writer paused, repeated copy hash stable, symlink source rejected, inspector and target containers removed. Docker archive-copy failed to access tmpfs on this Engine; the tested trusted reader path avoids that failure without weakening the target sandbox.
- Independent historical rejudge: 11 verified AC, 4 unknown/not rejudged; original trajectory hash unchanged.
- Existing regression assertions/security limits preserved. New coverage includes visibility matrix, budget monotonicity, last-response submission, tool caps, multiple calls/message pairing, provider failures, SE final completion, unknown snapshots, private export redaction, policy drift, posthoc isolation and unknown metrics.

Intermediate acceptance failures are retained, not relabeled as passes: the first 25-Run Docker attempt completed its units but hit a null assistant-content bug in report validation; that check was repaired. A subsequent attempt lost its 30-second benchmark lease while waiting for submission 17 (AC); 16 units remained Finished and one Running, with the rest Pending. Exact external scheduling/clock cause was not established. The final independent acceptance succeeded. Logs/databases for all attempts remain in separate ignored directories. Global paid execution stops on provider/Judge/infrastructure failure; an interrupted experiment is not declared complete. No failed historical/model Runs are retried or removed.

## Preregistration and future execution

See `benchmark/experiments/harness_ablation_v1/preregistration.md`. Plan ID:
`43c5fa6bf0d6064c6c16053d0e19d3e6f1e9d7ff6ba88eb478f08a9899679665`.

Five problems × five groups × one repeat = 25 exploratory Runs, maximum **180 model calls**. A 75-Run extension is separately preregistered/authorized later. Requested DeepSeek seed is not effective deterministic control. Use the README command after explicit authorization: `--real --authorize-paid --plan-id ... --max-runs 25 --max-model-calls 180 --max-observed-tokens 350000 --output NEW_DIRECTORY`. Offline validate/dry-run/Fake modes never construct the provider adapter. Keys are supplied privately through the environment only in authorized real mode and never propagated to the server/contestant containers.

## Remaining limits

No real A–E model experiment or current-commit GitHub Actions run was performed; no significance/effectiveness claim. Five observations per condition are only screening evidence, with descriptive contrasts and Wilson intervals specified for future analysis. Small synthetic tests are not a general coding benchmark. Exact injection-only token overhead is **null**, with actual bytes/full provider usage recorded; byte counts are not token estimates. Observed-token cap can overshoot by the last response and is not a billing guarantee.

Original whole-server fingerprint necessarily changes with new Harness code; byte equality of baseline Judge/security/config files establishes explicit compatibility, not identical whole-server identity. All new groups share one current fingerprint and original image. On another architecture or missing original image/evidence, execution fails closed. Failed-source snapshots require the owning local DB/runtime; remote/unavailable snapshots are unknown. Failure detection and container-freeze timestamps are separately stored: post-hoc correctness at freeze does not prove code was correct at the exact budget deadline. Unit tests/real Docker controls cannot prove absence of all timing races.

Local commit SHA is delivered in the final reply; no push is performed. Evidence is local/ignored; publish only this sanitized report and source/configuration.
