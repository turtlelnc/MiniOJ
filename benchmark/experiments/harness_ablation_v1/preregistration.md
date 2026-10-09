# Harness Transparency and Agent Task Completion — v1

Registered 2026-10-09 before any real ablation execution. This phase authorizes development and offline/Fake validation only. The earlier 15 DeepSeek Runs are exploratory discovery data, never confirmatory controls. Their original score remains **4/15**, and the separate historical post-hoc result remains **11/11 AC**.

## Hypothesis and critical confound

Execution-budget and sandbox-boundary disclosure may increase the probability of completing final_submit even when source code can already solve these frozen tests. The main competing explanation is simply more available model calls. Therefore A–D retain six calls; E changes only D's call budget. No hidden tests or post-hoc feedback reach the Agent. This is a screening experiment, not a decisive test of general coding ability.

## Conditions and frozen shared settings

| Condition | Model calls | Budget visible | Sandbox visible |
|---|---:|---|---|
| A Legacy | 6 | no | no |
| B Budget | 6 | yes | no |
| C Sandbox | 6 | no | yes |
| D Combined | 6 | yes | yes |
| E Extended | 12 | yes | yes |

All groups use the original system prompt and unchanged final_only tool schema, DeepSeek provider/model `deepseek-flash`, temperature 0.2, max_tokens 2048, tool budget 16 and Run wall budget 180 seconds. They share identical frozen problem/test contents, C++17 `g++ -O2 -std=c++17`, Docker image and actual enforcement. No resource limit is relaxed. E−D estimates the effect of additional calls; it is not a transparency effect.

`conditions.json` and `execution_plan.json` are canonical. Plan ID: `43c5fa6bf0d6064c6c16053d0e19d3e6f1e9d7ff6ba88eb478f08a9899679665`. Any substantive change creates a new plan/version before paid execution. The plan hash covers the schedule, problems, shared configuration and caps.

## Frozen problems and provenance

Five historical tasks: range sum, strict LIS, unweighted undirected shortest path, 0/1 knapsack, nonnegative directed shortest paths. The plan records each full snapshot SHA256, hidden-test SHA256 and test count (12,13,12,12,13). Hashes use canonical JSON (sorted keys, UTF-8, compact separators). Original private snapshots remain in `evidence/real-agent-20261008/trajectories.json`, never in the public repository. On a new machine, obtain the original private evidence from its owner; missing evidence fails closed, never substitutes new tests.

Original image: `sha256:7a5d27699ebab1b98fa78730b655619eb78a655d2e73698ed218e45717f7a638` (Linux arm64). An amd64 replacement is a new environment/version, not an identical reproduction. Original whole-server fingerprint: `d11a6f4cbaa05259a6d1cf49a5ce22498992f3e99edc9d4d294853a5fddd5bdc`. New Harness modules necessarily change that whole-server fingerprint. The tool records the current fingerprint and requires byte equality of the Judge/security/config implementation against the baseline Git revision; this is explicit compatibility, not a claim that the old whole-server fingerprint stayed identical. All new conditions share the same current fingerprint. A runtime freeze records policy hashes, image identity and authorization caps before Runs.

The limited synthetic tests do not establish general correctness or difficulty. All groups use the same tests, including oracle validation already performed in the discovery round.

## Interventions and timing

A uses exactly the legacy model message history, with no added budget or environment content. B–E use the same ephemeral system-message mechanism immediately after the initial system message, before the user/assistant/tool history. Injection never separates an assistant tool-call message from its results and never accumulates previous runtime notices.

Before a model request the Runner increments model_calls. The injected `model_used_including_current` includes that request; remaining responses include its response. The last permitted response may still call final_submit. Tools used count actual attempted validated requests and are frozen at 16. The model cannot change server-owned counters. Wall remaining is a monotonic deadline estimate measured at injection (checkpoint/network delay can reduce it).

Sandbox disclosure distinguishes the 256 KiB file API and source caps; dynamic per-file RLIMIT_FSIZE (up to 1 MiB, shrinking with the remaining 4 MiB Run output budget); per-command combined stdout/stderr cap; 64 MiB /workspace and 16 MiB noexec /tmp tmpfs; workspace cgroup and command RSS/address-space limits; compilation and per-test limits; and reset cwd semantics. The RLIMIT_FSIZE also bounds terminal-generated compiler artifacts. It is not a filesystem total quota. Policy is generated from configuration plus explicitly reviewed, source-hashed enforcement constants; changed policy requires refreezing.

Each injection records content, hash, wall-clock timestamp, counters and UTF-8 byte overhead. **Exact injection-only tokens are null**: the adapter has no matched counterfactual tokenizer/accounting API. Total provider prompt/completion usage remains recorded. Bytes are not relabeled as tokens. Thus exact intervention-only token cost remains unmeasured; different prompt lengths are an unavoidable part of this intervention.

## Allocation and sample size

Exploratory configuration: 5 problems × 5 conditions × 1 repeat = **25 independent Runs**. The execution plan uses Python Random with seed 20261009 to shuffle problem blocks and independently shuffle conditions within each block. Every problem appears once in every condition. The committed schedule is authoritative (not regenerated at execution).

Requested provider seed is 1; DeepSeek's adapter does not send a supported deterministic seed and seed_effective remains unknown. Matching requested seeds is not deterministic pairing. Execution scheduling seed controls allocation only. The 75-Run extension (three repetitions) is not authorized, configured or automatically launched here; decide its separate registration after reviewing the 25-Run feasibility results.

## Outcomes and denominators

Primary: E2E AC = explicit in-budget completed final_submit with AC / all terminal independent Runs. Submission completion = explicit completed final_submit, any verdict / all terminal Runs. Model, Agent, Judge and infrastructure failures remain in these denominators. Pending/Running are reported separately, never early failures. The final planned-unit success rate is null until every planned unit is terminal.

Post-hoc code validity is diagnostic only: AC / independently rejudged reliable termination snapshots, with observed and unknown counts out of all terminal Runs. Unrejudged/unrecoverable code is unknown, never false. No post-hoc score overwrites any original unit/submission. A separate ID, UTC timestamp, source hash, test hash, Judge compatibility and pinned image accompany each new rejudge.

Secondary: budget exhaustion / terminal Runs; final-submit attempt / terminal Runs (unknown legacy observation => null); limit-error and repeated-failed-command Runs / tool-observed terminal Runs; mean calls used including the final submission request among observed attempts; total tokens across all terminal Runs / terminal Runs, completed submissions, or successful submissions (null when any terminal usage is missing); mean observed Run wall time; provider/infrastructure failures / terminal Runs. Repetition means an identical raw terminal command failed twice, not semantic similarity. File-error text is a diagnostic tag, not evidence for Judge verdict classification or causal attribution. Legacy JSON/CSV fields and evaluable_solve_rate remain unchanged.

The compatibility pass@1 uses the first configured requested seed per problem/model among evaluable terminal independent Runs; within-Run revisions are not samples. final_only pass@1 is an Agent completion score, not single-shot code generation accuracy. No aggregation pools A–E into a model ranking.

## Analysis and failure handling

Report raw counts, denominators and Wilson 95% intervals for each condition's E2E/submission rate. Transparency contrasts: B−A and D−C (budget); C−A and D−B (sandbox); interaction D−B−C+A. E−D is budget extension. With only five observations per condition, report descriptive effects without claims of statistical significance. Problem blocking does not make nondeterministic model outputs strictly paired. No favorable seed selection, retries, dropping failures, changed tests or changing caps after seeing outcomes. For any larger study, preregister a problem-stratified/randomization analysis and multiplicity handling before collecting it.

Provider failure stops further paid calls and produces model_failure; Judge SE produces judge_failure; transport/startup failures produce infrastructure_failure; model/tool/wall exhaustion remains agent_failure. Global study caps are reported as stop reasons, keep unstarted units Pending, and do not imply an experiment completed. Failed-Run snapshots pause the entire owned local container before copying a size-bounded regular main.cpp and leave it frozen until cleanup. A short-lived trusted reader uses the target PID namespace and /proc/1/root to read tmpfs because Docker archive-copy cannot read these mounts on the tested Engine; it has no network, host mounts/socket or elevated capabilities. Failure-detection and freeze timestamps are distinct: freeze latency is recorded, and post-hoc validity does not prove code was already valid at the precise budget deadline. Missing local DB/runtime, symlink, copy failure or failed submission cleanup yields unknown; an unfrozen current file is never substituted. Post-hoc environment failure is unknown, not contestant failure.

## Stop conditions and cost

No real calls without `--real --authorize-paid --plan-id ...` AND explicit caps: at most 25 Runs, **180 model calls** (5 × (6+6+6+6+12)), 350000 observed total tokens. Credential presence alone is not authorization. No key is read by validate/dry-run/Fake modes. Missing usage or reaching the observed token cap stops before another model call. Observed tokens can exceed the threshold by the final in-flight call; this is an observed-usage stop, not a guaranteed billing cap. No parallel provider calls. An execution started with fewer authorized Runs follows the prefix of the frozen order and reports the remaining Pending units.

Each Run has 180 seconds, each provider request at most 60 seconds and each terminal command at most 30 seconds. A full study has a 25×180+60 second orchestration deadline. Infrastructure failure, inaccessible frozen data, changed Judge/security source, invalid plan hash, unavailable pinned image, or usage unknown stops/fails explicitly. On exit, stop the isolated server and remove only session-labeled test containers; retain private evidence. Never restart with a new directory to silently retry failed units. A partial execution requires a separately authorized continuation protocol, currently unsupported by this CLI.

## Verification boundary

Fake and unit tests validate schema equality, visibility, counters, message pairing, terminal denominators, unknown values, redaction, read-only post-hoc data and safe authorization gates. A true Docker Fake loop validates compiled reference code on the frozen hidden tests and API JSON/CSV consistency. Neither establishes real-model transparency effectiveness. This phase performs no paid ablation and therefore reports no B−A or other real-model effect.
