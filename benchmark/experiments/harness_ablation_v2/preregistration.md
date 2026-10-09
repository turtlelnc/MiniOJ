# Harness ablation v2: file-path contract correction

Registered before new model calls. v1 remains unchanged: 14 sandbox-visible Runs rejected absolute file-tool paths. This follow-up tests an incomplete harness disclosure, not a claim that sandbox transparency inherently harms reasoning.

Only C/D/E receive a File Tool Paths notice: read_file/write_file require paths relative to /workspace; absolute paths may occur inside terminal commands. A/B messages, all tool schemas, fail-fast error handling, enforcement, frozen five problems and hidden cases, image, model settings and per-Run limits remain unchanged. Enforcement policy is the v1 sandbox_policy.json. Version 1 manifests retain their original prompts. v2 is selected explicitly by its frozen plan and manifest disclosure_version=2.

25 fresh independent Runs (five problems times A–E), same preregistered order, no retries or pooling with v1. Requested seed is not effective deterministic pairing. Same exploratory outcomes, denominators, Wilson intervals, post-hoc provenance and stop/cleanup rules as v1 preregistration apply. First-tool absolute-path rejection counts are additionally inspected. A/B are contemporary controls; changes across dates can reflect stochastic sampling or provider drift. With five units per group, improved completion cannot establish a statistically significant transparency benefit.

Authorized maximum: 25 Runs, 180 model calls, 350000 observed tokens. Missing usage, provider/Judge/infrastructure failure stops paid execution. The observed-token threshold may be exceeded by the last response. Fake validation is not real-model evidence. Preserve all historical data; no automatic push.

Plan ID: cdc1de86f60db68298aef2ab0447453a6384041294431ace2887efb94133c147
