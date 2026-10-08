# Round 4 validation

Base: `6dedf4713563b243e5e6bc698757c076b7f131ca`. Local validation: 2026-10-08. No push or paid model API call.

## Diagnosis and changes

The failed [Actions run](https://github.com/turtlelnc/MiniOJ/actions/runs/37812922643) recorded a roughly 311 ms timeout in a 300 ms Python self-SIGXCPU test. That log alone cannot establish whether startup/scheduling or resource attribution caused the timeout. Controlled reproductions of the old runner established two distinct paths: delaying launcher startup by 350 ms caused a real wall timeout before the target signaled; injecting unrelated caller-cgroup CPU usage caused a false timeout after about 5 ms. The original test conflated startup with signal classification.

LocalRunner now reads only child/process-tree evidence, uses wait4 instead of poll to retain exit and CPU evidence, rechecks completion before declaring wall timeout, and starts the launcher with `-S`. Wall time still includes launcher startup. The native signal fixture uses ready/ack synchronization, with a 10-second test budget and explicit assertions that wall/CPU limits were not reached. Separate short wall and actual CPU deadline tests preserve limit enforcement. Python's ignored SIGPIPE/SIGXFSZ dispositions are reset before exec; exactly-at-limit output is accepted.

Real Linux container tests uncovered another issue: RLIMIT_CPU SIGXCPU arrived with wait4 CPU measurements around 995–996 ms for a nominal one-second limit, so the strict old threshold produced RE. Docker supervision now explicitly observes the contestant's process CPU clock and enforces the requested budget; a later RLIMIT_CPU guard remains. Actual supervisor kills record SIGKILL. Clock-read failure becomes SE. The public cgroup CPU metric remains container-wide; it is not used as contestant CPU proof. LocalRunner uses its sampled process-tree budget, with wait4 evidence and a later kernel guard. No threshold tolerance or weakened assertions were introduced.

Both runners preserve completed exits when their observation is delayed. Deterministic tests delay LocalRunner observation and actually SIGSTOP/SIGCONT the Docker supervisor across its deadline after the target has self-signaled. Docker no longer infers output_limit from a self-sent SIGXFSZ without output evidence.

PID pressure fixtures hold children behind a pipe gate instead of racing short sleeps against fork. Queue recovery uses its own token instead of an inherited outer token, tracks the server during startup failure, and cleans up on termination. CI preflight permits TIME_WAIT reuse but rejects active listeners. Container cleanup uses a random per-test-session label; existing user containers/databases are outside its scope.

## Modified files

- `.github/workflows/tests.yml`: independent bounded unit/Docker jobs, Linux Engine, summaries and sanitized artifacts.
- `minioj/runner.py`, `minioj/launcher.py`: child evidence, reaping, CPU guard, startup and signal dispositions.
- `minioj/docker_backend.py`, `scripts/container_judge.py`: independent internal wall budget for boundary tests, precise process CPU enforcement, reaping order and cleanup label.
- `minioj/config.py`: Colima auto-detection only on macOS.
- `scripts/ci_unit.py`, `scripts/ci_docker.py`: isolated CI orchestration, counts, capability checks, timeouts, cleanup and allowlisted diagnostics.
- `scripts/round4_boundaries.py`: real Docker exit/signal/CPU/wall/output/transport/supervisor regressions.
- `scripts/acceptance.py`: real HTTP SE regression alongside AC/WA/TLE/MLE/RE/CE.
- `scripts/round3_resources.py`: deterministic PID event fixtures.
- `scripts/queue_crash_acceptance.py`: isolated authentication and bounded server lifecycle.
- `tests/runner_support.py`, `tests/test_runner_boundaries.py`, `tests/test_resource_metrics.py`: synchronized native fixtures, actual limits and observation-race regressions.
- `tests/test_ci_reports.py`: counts, null metrics, artifact allowlists and failure diagnostics.
- `README.md`, `docs/round4-validation.md`: CI usage, definitions, evidence and limits.

## Actual results

| Environment/check | Result |
|---|---|
| macOS arm64, Python 3.14: compileall and unittest | 97 passed, 0 failed, 0 skipped |
| Linux Ubuntu 24.04 arm64 VM, Python 3.12: compileall and unittest | 97 passed, 0 failed, 0 skipped |
| Synchronized SIGXCPU repetitions | 20/20 on each environment |
| YAML parse and job-independence check | Passed |
| Real Linux Docker integration, full final run | Passed, 148.051 seconds |
| Resource/cgroup/runner observations | 37 passed cases across three scripts |
| HTTP Judge/workspace acceptance | 18 checks, including AC/WA/TLE/MLE/RE/CE/SE and output_limit |
| Sandbox security acceptance | 5 checks |
| Queue crash/recovery | Killed during Compiling and Running; SE/worker_lease_expired, attempt_count=1; subsequent AC |
| Fake final_only | 18/18 finished, 9 AC, 9 WA, no other failures |
| Fake iterative | 18/18 finished, 9 AC, 9 WA, no other failures |
| Raw Run/metrics/JSON/CSV consistency, pause/resume, frozen snapshot, idempotency | Passed for both protocols |
| Cleanup | No session containers remain; servers stopped; ports released; private directory removed |

The resource cases include hard container memory and OOM, sustained/transient/child memory, tmpfs/base overhead, historical/new PID events, missing post-OOM metrics, detached children, authentic exit(0/1/137), self SIGXCPU/SIGKILL/SIGXFSZ, CPU/wall deadlines, exact/overflow output, crash, stderr without resource evidence, report-pipe protection, paused-container Docker CLI error, supervisor death and delayed observation.

Local sanitized evidence is under `evidence/round4/{mac-unit,linux-unit,linux-docker}` and is intentionally ignored by Git. CI uploads only allowlisted JSON counts, source locations, known reasons and numeric observations. Raw logs, tokens, databases, hidden tests and Benchmark manifests/messages are private temporary files. Artifact allowlists are tested with injected private strings.

## Boundaries and remote verification

The actual Docker environment was Linux arm64 in the existing Colima VM; CI uses the native Engine on GitHub-hosted Ubuntu x86_64 / Python 3.14. That exact hosted combination and Actions orchestration have not been executed for this commit. No remote success is claimed. Missing mandatory cgroup capabilities cause a visible failed preflight, not a successful skip.

Container memory.peak still covers the entire container, including init, supervisor, children, tmpfs and observers. Exact contestant process RSS is unavailable/null. Missing post-OOM measurements remain null. LocalRunner's RSS/CPU tree sampling remains approximate and is not a security sandbox. CPU-clock supervision measures the primary contestant process (including its threads), not a precise sum of all descendant CPU clocks; default wall and container CPU/PID/memory limits remain in force. Polling cannot make wall deadlines exact under arbitrary host scheduling delays. Repeated tests do not prove absence of every race.

This round's VM and test services were stopped after verification. Only round-specific bootstrap files were removed; no user database was deleted.

After explicit push authorization, use:

```sh
gh run list --workflow tests.yml --commit <local-commit-SHA>
gh run watch <run-id> --exit-status
gh run view <run-id> --json headSha,conclusion,jobs
```

Confirm the head SHA, both successful jobs, counts in Job Summary and sanitized artifacts. The workflow also supports manual dispatch. Neither job depends on the other. Docker's overall job timeout is 20 minutes; the harness has a 15-minute budget and bounded per-stage waits. Only Fake Adapter is used.
