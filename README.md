# MiniOJ

可运行的本地 C++17 Online Judge，以及人和 AI Agent 共用的 Linux 解题工作台。

- 题目 CRUD、公开样例、隐藏测试、SQLite 提交历史。
- 异步队列 → 编译 → 测试点执行 → 资源限制 → exact/trimmed checker → verdict。
- AC / WA / TLE / MLE / RE / CE / SE，独立过程状态 Pending / Compiling / Running / Finished。
- 原生 HTML/JS WebUI、文件编辑器、xterm.js 交互终端、命令结果及 Run 操作记录。
- Agent Run 与代码尝试分离，支持外部模型元数据及多轮提交。模型调用由外部客户端完成。

## 快速运行

依赖 Python 3.11+，Docker Engine；macOS 可使用 Colima。WebUI 的 xterm 资源已随项目提供，不依赖 CDN 或 Node 构建。

```sh
git clone https://github.com/turtlelnc/MiniOJ.git
cd MiniOJ
python3 -m venv .venv
.venv/bin/pip install -r requirements.lock
# macOS，若尚未安装容器运行时：
brew install colima docker
./scripts/setup_sandbox.sh
./scripts/run.sh
```

浏览器打开 http://127.0.0.1:8000 。首次启动的题库为空，请在“题目管理”中添加题目、样例及隐藏测试。

如果只需用 macOS 本地编译器测试可信代码，可设置 `MINIOJ_JUDGE_BACKEND=local`；这不启用工作台，不是安全沙箱。默认使用 Docker 判题，不会悄悄退回本地执行。

Colima 使用专用 profile `minioj`，2 CPU / 2 GiB 内存 / 8 GiB 数据盘；Lima 另有基础系统盘。首次启动会下载 VM 镜像、初始化系统包，需预留约 5 GiB 实际磁盘空间。停止 VM：`colima stop minioj`。不会安装自动开机服务。

环境变量：`MINIOJ_PORT`（8000）、`MINIOJ_DATA`（项目 data）、`MINIOJ_JUDGE_BACKEND`（docker/local）、`MINIOJ_COMPILER`（本地 g++ 路径）、`MINIOJ_IMAGE`（minioj-sandbox:1）、`MINIOJ_DOCKER_CONTEXT`、`MINIOJ_TOKEN`。若检测到专用 Colima socket，默认使用 `colima-minioj` context。

## 页面

| 路径 | 用途 |
|---|---|
| `/` | 题目列表 |
| `/problems/:id`、`/problems/:id/submit` | 题目说明和直接提交 |
| `/submissions`、`/submissions/:id` | 提交记录、进度、结果、编译诊断和源码 |
| `/runs`、`/runs/:id` | 人/Agent Run 列表和工作台 |
| `/admin` | 本机题目管理，包括隐藏测试编辑 |
| `/benchmarks`、`/benchmarks/:id` | 实验状态、配置、每单元结果、汇总和 JSON/CSV 下载 |

题目管理中的“允许启用工作台”默认关闭（已有题目也默认关闭）。勾选并保存后，该题才显示工作台入口，创建隔离环境的 API 也会检查此设置。提交编辑器和工作台的 `main.cpp` 均为空白，不预填解答。

工作台使用方式：从题目页面点击“打开 Linux 工作台”，编辑并保存 `main.cpp`，点击“编译并运行样例”，或连接交互终端。终端是真实 PTY，支持 Ctrl-C、标准输入和 shell。连接终端时仍可点击文件查看内容和切换编辑草稿；文件列表显示用途及字节大小。保存、命令 API、最终提交前请断开终端，避免并发修改。切换文件会保留当前页面中的未保存草稿，刷新页面前应先保存。命令行 API 与终端共享同一个 `/workspace`。

终端断开时清理终端中残留的进程，保留文件。最终提交捕获源码后销毁工作环境，由另一个 Judge 容器执行隐藏测试。已结束 Run 可查看操作记录和最终源码，但不能重开原环境。

## 文件与模块

```text
MiniOJ/
  minioj/
    app.py                 HTTP/API、校验、WebSocket PTY
    config.py              路径、运行配置和本机 API token
    db.py                  SQLite 数据访问
    judge.py               Judge Core、JudgeQueue、后端会话
    runner.py              资源监测与进程组清理
    launcher.py            子进程 exec 前的 setrlimit
    checker.py             输出比较接口
    docker_backend.py      Docker 生命周期、文件操作、受限传输
    workspace.py           Run 环境、命令队列、预算和清理
  scripts/
    container_*.py         镜像内可信执行、文件、PID 1 回收工具
    setup_sandbox.sh        启动 Colima / 构建镜像
    run.sh                 启动服务
    agent_example.py       不依赖模型供应商的完整 Agent API 客户端
    acceptance.py          HTTP + 容器 + WebSocket 验收
  static/                  原生 WebUI、MIT 授权 xterm.js
  tests/                   Judge / Checker 单元和实际程序测试
  evidence/                本地验证输出（不加入版本控制）
  data/                    本机运行数据（不应加入版本控制）
```

数据库：`data/minioj.sqlite3`（WAL 模式）；题目说明、样例、隐藏测试都保存在 SQLite。每次提交及 Run 保存题目/限制/测试点快照，编辑和软删除题目不改变历史判题。

API token：`data/api-token`，首次生成，权限 0600。浏览器访问本机页面时建立 HttpOnly、SameSite=Strict cookie。外部 Agent 使用 `X-MiniOJ-Token` 请求头；勿把 token 写进日志或 URL。

Docker Judge 在编译容器中生成源码和产物，再把可执行文件通过有界内存传输复制到每个测试点独立的新容器；不挂载宿主目录。测试容器内存硬上限等于题目内存限制、禁用 swap，输出通过宿主有界管道收集。Agent 同样使用独立 tmpfs 工作目录。容器删除后全部清理。本地可信 Runner 使用 `/tmp/minioj/submission-随机值` 独立目录，结束后删除。

## REST API

所有 `/api/*` 都需要本机 cookie 或 token，包括 `/api/openapi.json`。错误：404 对象缺失、409 环境状态/操作冲突、413 请求过大、422 参数校验、429 队列/环境容量满、503 Docker 未就绪。

| 方法与路径 | 行为 |
|---|---|
| `GET /api/health` | 当前后端、沙箱可用性、工作台预算 |
| `GET /api/problems`、`GET /api/problems/:id` | 普通题目读取，不含隐藏测试 |
| `POST /api/problems`、`PUT /api/problems/:id`、`DELETE /api/problems/:id` | 本机管理 CRUD；删除为软删除 |
| `GET /api/admin/problems/:id` | 管理端完整题目，含隐藏测试 |
| `POST /api/submissions` | `{problem_id, language:"cpp17", source_code}`，202 返回 `{submission_id}` |
| `GET /api/submissions`、`GET /api/submissions/:id` | 列表和轮询进度/结果 |
| `POST /api/agent-runs` | 创建 Run 和可选 Linux 环境 |
| `GET /api/agent-runs`、`GET /api/agent-runs/:id` | 列表/详情；支持 problem_id/model_name/provider 筛选 |
| `PATCH /api/agent-runs/:id` | 合并模型及统计元数据；反馈策略不可修改 |
| `GET /api/agent-runs/:id/files` | 工作区文件列表 |
| `GET /api/agent-runs/:id/file?path=main.cpp` | 读 UTF-8 文件 |
| `PUT /api/agent-runs/:id/file` | `{path,content}` 写文件；不跟随符号链接 |
| `POST /api/agent-runs/:id/commands` | `{command,timeout_ms,stdin}`，202 返回 `{command_id}` |
| `GET /api/commands/:id` | 轮询命令状态及 stdout/stderr/退出码/资源信息 |
| `WS /api/agent-runs/:id/terminal` | 交互式 bash PTY，cookie 或 token 握手认证 |
| `POST /api/agent-runs/:id/submissions` | `{path}` 或 `{source_code}`，提交尝试 |
| `POST /api/agent-runs/:id/final-submit` | `{path}` 或 `{source_code}`，最终提交并销毁环境 |
| `POST /api/agent-runs/:id/finish` | `{final_submission_id}`，选定已完成的本 Run 提交并结束 |
| `DELETE /api/agent-runs/:id/environment` | 销毁环境，保留 Run 和历史 |

创建题目字段：`title`、`description`、`input_description`、`output_description`、`time_limit_ms`、`memory_limit_mb`、`checker`、`samples`、`testcases`。样例/测试点为 `{input,expected_output,weight}`，weight 默认 1，当前整体通过判定不做部分分数汇总。

创建 Run 示例：

```json
{
  "problem_id": 1,
  "source": "agent",
  "environment": true,
  "feedback_policy": "final_only",
  "metadata": {
    "model_name": "your-model",
    "provider": "your-provider",
    "prompt": "Solve the problem using the terminal"
  }
}
```

题目字段 `allow_workspace` 为布尔值，默认 `false`；`environment:true` 需要该题已启用，否则返回 403。

`source` 支持 human/agent。`environment:false` 允许外部 Agent 不使用工作台而直接提交源码。

`final_only` 默认仅一次隐藏判题：公开样例可以自由编译/运行，首次 `/submissions` 等同最终提交。`iterative` 显式允许多次隐藏判题反馈，用于另一类实验；结束时调用 `/finish` 指定最终尝试，或 `/final-submit` 创建最终尝试。这两种策略应分开统计。单用户可以直接调用普通提交 API；这是评测协议约束，不是抗作弊竞赛权限系统。

元数据可存 `model_name/provider/prompt/token_input/token_output/tool_calls/compile_attempts/patch_count/wall_time/cost`。这些由 Agent 报告，不能当成服务端独立核验的消耗。服务端另外记录创建/结束时间、文件写入内容、命令请求及结果、终端输入/输出和每次判题。原始记录支持后续计算 pass@1/pass@n、time-to-AC、tokens/cost per solved problem；本版不提供统计仪表盘。

WebSocket 输入为 JSON：`{"type":"input","data":"ls\r"}` 或 `{"type":"resize","rows":24,"cols":100}`；服务器输出 UTF-8 文本终端片段。命令 API 的 shell 解释只发生在隔离容器内，不拼接宿主 shell 命令。最大单次输入 8 KiB、单次会话输入合计 256 KiB、输出 1 MiB、会话最长 5 分钟。

运行示例 Agent 客户端：

```sh
.venv/bin/python scripts/agent_example.py --problem 1
# 或提供模型生成的源码：
.venv/bin/python scripts/agent_example.py --problem 1 --source solution.cpp
```

## 判题行为和限制

- 编译：`g++ main.cpp -O2 -std=c++17 -o main`，argv 启动，编译最多 30 秒，输出合计 1 MiB；失败或编译资源超限为 CE。
- 测试点：父进程 wall-clock 计时，CPU rlimit，RSS/cgroup 内存采样，文件输出大小限制；超限主动 kill 进程组。Docker Judge 每测试点后清理其他残留进程，包括脱离进程组的后台进程；容器 PID 1 回收孤儿和僵尸。
- TLE：wall-clock 或 CPU 超限。MLE：采样观察到内存超限，或运行时报告分配失败；RE：崩溃、非零退出、输出超限。输出超限附 `reason=output_limit`。基础设施失败为 SE。
- Docker Judge 测试点由独立容器的 cgroup 硬限制，读取 `memory.peak` / `memory.events` / `cpu.stat`。本地后端、工作台命令、编译阶段仍使用采样监测，不能视为逐测试点硬限制。无法读取峰值或 CPU 时返回 null。
- 时间包含 launcher/监测开销，快速程序不适合用这些结果做微秒级性能比较。判题耗时/峰值取已执行测试点最大值，首个失败后停止，不等于全部测试耗时。
- exact 逐字节比较；trimmed 移除每行末尾空格/tab 和文件末尾 LF，保留内部空白、内部空行和 CRLF 差异。
- 工作环境：非 root UID 1000、无网络、无 host bind mount/无 Docker socket、只读根文件系统、移除全部 capabilities、no-new-privileges、Docker 默认 seccomp；`/workspace` 为可执行 tmpfs，`/tmp` 不可执行。
- 每 Run：512 MiB 内存且禁用容器 swap、1 CPU 配额、64 PID、工作区 64 MiB、tmp 16 MiB、15 分钟 wall-clock、累计 CPU 120 秒（监测间隔 3 秒）、最多 100 次执行/终端会话、输出累计 4 MiB；最多 2 个活动工作台。后台命令也受整个容器预算限制。
- Judge：默认单 worker，SQLite 中最多 100 个 Pending；独立 768 MiB 编译容器、编译监测预算 640 MiB。每测试点新容器硬内存限制为题目指定的 32–256 MiB，包含容器内 idle 进程和可执行文件 tmpfs 的内存开销。受限命令的 RLIMIT_FSIZE 也限制其创建的单个文件为 1 MiB；交互终端直接受工作区总量限制。源码/单文件最大 256 KiB；请求体最大 2 MiB；题目全部测试数据合计 1 MiB。
- 服务重启：Pending 从 SQLite 原子领取；旧版无租约的编译/运行任务立即标 SE，新任务等待租约过期后标 `SE / worker_lease_expired`，不自动重跑。活动 Run 标 Interrupted 并删除属于该数据库实例的容器。关闭服务同样销毁工作环境。维护中若服务器异常退出，可使用 `MINIOJ_RECOVER_WORKSPACES=1 ./scripts/run.sh` 接管仍运行且未过期的原容器，保留文件并清理旧命令进程；资源预算和到期时间不重置。

## 安全边界

这是本机单用户工具，不应直接公开监听或暴露到互联网。所有本机 UI/API 使用同一身份，管理接口可读取隐藏测试；不提供人/Agent 多租户权限隔离。默认拒绝外部 Host/Origin，避免浏览器跨站调用和 DNS rebinding；本机同一用户的其他程序仍能访问。

Docker 使用 Linux 隔离和 cgroup，比 macOS 本地资源限制更合适，但仍共享 VM 内核。默认 seccomp 不是面向公开恶意代码完成审计的 OJ 策略；容器逃逸、针对执行器的攻击和精确峰值计量仍需要进一步加固。正式公开服务应另行实现专用身份/权限、网络访问控制、强化 seccomp/独立 VM 或 microVM、日志保留/配额和运维监控。

`LocalRunner` 无文件系统/网络隔离。macOS 不把 RLIMIT_AS 当可靠 RSS 限制，也不设置会影响宿主用户其他进程的 RLIMIT_NPROC；只能用于可信代码开发和测试。

## 验证

```sh
.venv/bin/python -m compileall -q minioj benchmark scripts
.venv/bin/python -m unittest discover -s tests -v
# 启动服务器和 Docker 镜像后：
.venv/bin/python scripts/acceptance.py
```

实测证据保存于 `evidence/unit-tests.log`、`docker-build-final.log`、`acceptance.log`、`acceptance.json`、`resource-acceptance.log`、`resource-acceptance.json`。验收会创建测试题目和提交，结束后软删除测试题目，保留提交历史。浏览器验收覆盖提交 AC、工作区文件编辑、样例运行、交互终端和最终判题。

尚未实现：仓库修 bug/功能任务、模型供应商调用、评分指标聚合、special checker、用户/竞赛体系、Redis/多 worker/远程节点、严格公开 OJ 沙箱、精确峰值内存计量。当前保留 Runner/Checker/队列和 Run 边界，后续仓库任务可以复用工作环境生命周期。

第三方前端依赖 xterm.js 与 fit addon 为 MIT，许可及版本位于 `static/vendor`。

### 测试数据配置与 ZIP 导入

题目管理页面使用可增删的“输入 / 期望输出”表单，不要求用户编写 JSON。新建题目的字段和测试点集合保持空白。公开样例与隐藏测试分别配置，也分别支持上传 ZIP；导入的数据先在表单中预览和编辑，点击保存题目后才写入数据库。上传默认追加，已有同名测试点会提示冲突。

ZIP 内支持 `1.in / 1.out`、`apple.in / apple.out` 等任意同名配对，以及子目录中的同名配对；输入和输出需位于同一目录，文件名区分大小写，扩展名大小写均可。测试点名称会保留在题目数据中。文件内容须为 UTF-8 文本，空输入或空输出可以使用空文件。

导入接口：`POST /api/admin/testcases/import-zip`，请求体直接为 ZIP 二进制（Content-Type: application/zip），返回 `{testcases:[{name,input,expected_output,weight}]}`。此接口只解析预览，不直接修改题目。JSON REST API 仍供程序使用。

限制：ZIP 最大 2 MiB，解压后的测试文件总量 1 MiB，每个文件 128 KiB，最多 100 对；公开样例最多 10 对。拒绝未配对、重复条目、路径穿越、符号链接、加密包、非 UTF-8 文本和损坏 ZIP。文件直接在内存中有界读取，不解压到磁盘；忽略 README、macOS 元数据等非测试文件。

对应验证：`evidence/zip-import-unit-tests.log`（25 项测试通过）、`evidence/zip-import-api.json`（具名 ZIP 导入、保存名称、实际判题 AC）。

真实 DeepSeek Agent 验证：设置 `DEEPSEEK_API_KEY` 后运行 `.venv/bin/python scripts/deepseek_agent.py`。客户端建立临时区间求和题，最多 16 轮模型调用，只提供文件读写、隔离终端与最终提交工具；结果保存在 `evidence/deepseek-agent-api.json`，测试题随后软删除、Run 和提交历史保留。密钥不保存到证据。


## 第二阶段：可靠 Judge 与 Benchmark

### Judge 计量和硬限制

实测 Colima 的 `/sys/fs/cgroup` 为 cgroup v2，但只读，创建子组返回 Read-only file system。实现选择每个测试点新建受限 Docker 容器，由宿主 Python 监督器执行与收集输出；不使用 privileged，不挂载 Docker socket，不增加 capabilities。编译容器与每个测试容器分离，因此测试 OOM 和 fork 压力不会杀死宿主监督器或编译器。容器删除会清理所有后台进程，包括 setsid 子进程。

测试容器使用 `memory.max=题目内存`、swap 禁用、1 CPU 配额、64 PID，以及原有只读根目录、无网络、非 root、no-new-privileges 和 Docker 默认 seccomp。宿主 wall-clock 终止和有界输出管道另行限制执行；CPU rlimit 作为补充。CPU 配额是速率限制，并非精确累计 CPU 时间阈值；wall-clock 包含 Docker exec 启动/传输与终止请求开销，不适合微秒级性能比较。

每个测试结果保留旧的 `runtime_ms` / `memory_kb`，并增加 `wall_time_ms`、`cpu_time_ms`、`peak_memory_kb`、`termination_signal`、`termination_reason`、`transport_exit_code`。`memory_method=cgroup_v2_memory_peak_container` 表示内核记录的整个测试容器峰值（含运行时和 tmpfs），不是仅 contestant RSS；CPU 为整个测试容器的 usage 差值，包含计量辅助命令开销。超时/输出超限时先终止再读取计量，无法获取的峰值/CPU 返回 null。

Docker exec 只提供传输退出状态，不能可靠区分 `exit(134)` 与 SIGABRT。因此大于等于 128 的状态保存在 `transport_exit_code`，`exit_code` / `termination_signal` 不做猜测；已观察到内核 OOM kill 时可以确认 signal 9。已观察到 OOM 的退出优先判 MLE，否则宿主观察到的超时为 TLE；极近边界事件不能宣称有精确先后顺序。可执行文件最大 1 MiB。

参考：[Linux cgroup v2](https://www.kernel.org/doc/html/latest/admin-guide/cgroup-v2.html)、[Docker 资源限制](https://docs.docker.com/engine/containers/resource_constraints/)。

### SQLite 调度与恢复

数据库通过幂等列/表迁移升级（`PRAGMA user_version=2`），保留原题目、Run、提交和命令历史。SQLite 是唯一任务权威；Python 队列仅兼容旧唤醒调用，满了不会隐藏已持久化任务。

`BEGIN IMMEDIATE` 同时完成容量检查和提交插入；worker 原子领取 Pending 并写入 `lease_owner`、`lease_expires_at`、`attempt_count`。默认 60 秒租约、5 秒续租。状态和结果写入带 owner 条件，过期 worker 的迟到结果无法覆盖终态。进程崩溃后执行结果未知，所以保守记为 Judge SE，不偷偷重试；需要重新评测时创建新提交。`MINIOJ_SUBMISSION_LEASE_SECONDS` 可配置，最低 10 秒。

最终提交的插入和 Run→Judging 在一个事务中完成；提交完成时同事务把对应 Run→Finished。每个数据库只运行一个应用服务进程（不要开启多个 Uvicorn worker）；数据库任务领取支持竞争，但工作台生命周期仍是单进程管理。

### Benchmark 配置与启动

先在管理页为待评测题目启用工作台。复制 `benchmark/examples/deepseek.json`，把 `problems` 改成实际数据库 ID（不是首页列表序号），按需添加模型和 seeds。配置采用 JSON，不引入额外框架。

```json
{
  "name": "coding-basic-v1",
  "problems": [1, 2, 3],
  "models": [{"provider": "deepseek", "model": "deepseek-flash", "api_key_env": "DEEPSEEK_API_KEY"}],
  "seeds": [1, 2, 3],
  "protocol": "final_only",
  "temperature": 0,
  "max_tokens": 4096,
  "limits": {"max_model_calls": 16, "max_tool_calls": 50, "max_wall_time_seconds": 300}
}
```

```sh
# 先运行 scripts/run.sh；在另一个终端安全设置 DEEPSEEK_API_KEY。
.venv/bin/python -m benchmark.runner --config benchmark/examples/deepseek.json
# 在单元边界暂停；控制本次成本：
.venv/bin/python -m benchmark.runner --config my-benchmark.json --max-units 3
# 使用输出中的 experiment ID 恢复；终态单元不会重新执行：
.venv/bin/python -m benchmark.runner --resume EXPERIMENT_ID
```

启动时冻结完整题面、样例、隐藏测试、模型配置、seed 请求、temperature、max_tokens、system prompt、tool schema、预算、协议、Git commit/dirty diff hash、Runner 版本、代码指纹、Docker 镜像 ID/架构。Run 与 Judge 使用被冻结的测试和镜像 ID；Judge 代码指纹变化会明确报 SE，不会静默换版。导出和 WebUI 隐去隐藏测试内容，保留其 SHA256；完整快照在本机 SQLite 中保存。要复现实验需保留数据库及对应源码提交/镜像；仅公开 JSON 不能还原隐藏测试。

DeepSeek Adapter 接收 messages/tools/temperature/max_tokens，密钥仅从指定环境变量读取，错误记录不包含响应体或请求头。当前不向 DeepSeek 发送不受保证的 seed，记录 `seed_requested`、`seed_effective:null`、`deterministic:false`；响应模型名另存 `model_returned`，实际后端版本标 unknown。FakeModelAdapter 只用于协议验收，可以记录生效 seed。适配器接口独立，尚未实现 OpenAI/Anthropic/本地兼容 API。

### 协议、失败与恢复

`final_only` 工具为 read_file/write_file/terminal/final_submit。最终提交后直接保存结果并结束单元，不把隐藏结果反馈给仍可调用工具的模型。`iterative` 额外提供 submit_attempt，可以接收多次隐藏反馈，最后必须 final_submit；统计单独保留协议标签。

每个 `(model_index, problem, seed)` 预建唯一单元、关联唯一 Agent Run。实验有租约，禁止两个 Runner 同时推进；每个模型/工具调用前后存检查点。正常暂停发生在单元边界，恢复跳过终态。意外中断时：已有最终提交可以仅查询并收敛结果；其他正在执行的单元保守记录 `infrastructure_failure / interrupted_execution_not_replayed`，清理环境、继续剩余单元，不重复执行可能有副作用的终端命令。恢复时无法可靠还原的 wall_time 为 null。JSON 中 Interrupted 表示 Runner 租约已失效，可以用 --resume 接管。

错误分为 model_failure（供应商请求/超时/缺失密钥）、agent_failure（非法工具、协议结束或预算耗尽）、judge_failure（SE）、infrastructure_failure（MiniOJ/运行器故障、未知中断）。前三类之外的有效 WA/CE/TLE/MLE/RE 是正常可评估判题结果。供应商、Judge、基础设施错误不计作模型未解出；Agent 协议/预算失败计为未解出。

### 指标与报告

每个模型/协议分别报告 attempted、evaluable、excluded、solved、solve_rate、pass@1 及其分母、mean input/output/total tokens、mean tool calls、mean wall time、tokens per solved problem。solve_rate 以可评估的独立 Run 为分母；pass@1 仅选每题**第一个预设 seed** 的独立 Run，缺失/排除时不拿其他 seed 代替。iterative 的 pass@1 指第一独立 Run（含反馈），不能解读为单次代码提交的通过率。未实现 pass@k，不把同一 Run 中的修复当独立样本。

缺失 token usage 保持 null；均值只使用实际观察值，同时报告 usage_observed_units / usage_complete。如果任何可评估 Run 缺少 usage，tokens_per_solved_problem 为 null；该指标分母是解出的独立单元数，不是去重后的题目数。

默认导出到 `evidence/benchmark/EXPERIMENT_ID/` 的 results.json、results.csv、summary.json。结果包含 unit_id / run_id / submission_id，可追溯源码和所有工具操作。WebUI `/benchmarks` → 选择实验 → 配置/每题结果/汇总 → 下载 JSON/CSV。

新增 API（沿用本机 token 认证）：

| 方法与路径 | 用途 |
|---|---|
| POST /api/benchmarks | 校验配置、冻结快照、预建实验单元 |
| GET /api/benchmarks | 实验列表及状态 |
| GET /api/benchmarks/:id | 配置、单元与汇总；隐藏测试不返回 |
| GET /api/benchmarks/:id/export/json 或 csv | 下载报告 |
| POST /api/benchmarks/:id/acquire、heartbeat、release | Runner 租约与暂停/完成 |
| PUT /api/benchmarks/:id/units/:uid | Runner 检查点与终态（需 owner） |
| POST /api/benchmarks/:id/units/:uid/run | 从服务端冻结快照创建/返回唯一 Run（需 owner） |

### 第二阶段验收

```sh
mkdir -p evidence
.venv/bin/python -m compileall -q minioj benchmark scripts
.venv/bin/python -m unittest discover -s tests -v
# 下列测试顺序执行，避免资源压力测试与实验互相争用：
.venv/bin/python scripts/stage2_resources.py
.venv/bin/python scripts/queue_crash_acceptance.py
# 主服务开启后：
.venv/bin/python scripts/acceptance.py
.venv/bin/python scripts/benchmark_acceptance.py
# 仅一个单元；未设置密钥时明确跳过：
.venv/bin/python scripts/benchmark_real_smoke.py
```

实测：32 MiB 测试容器能捕获 96 MiB 短时触页分配并 MLE，memory.peak 为 32768 KiB；16 MiB 短时峰值程序正常退出，内核记录约 20 MiB 的容器峰值。无限循环、fork 压力、脱离会话的残留子进程、无限输出、abort，以及内存/超时竞争均实际测试，编译容器持续存活。资源脚本记录每次结果；不能把容器峰值当纯程序 RSS。

真实服务 SIGKILL 验收分别在 Compiling 与 Running 杀死服务，用临时独立数据库和短租约重启：两次均以 SE/worker_lease_expired 结束，attempt_count=1、Run Finished，后续新提交 AC。

FakeAdapter 验收为 3 题 × 2 模型 × 3 seeds = 18 个实际 Agent Run；正确模型 9 AC，错误模型 9 WA，各模型 pass@1 分母为 3；暂停恢复、冻结快照、导出和重复启动去重均检查。真实 DeepSeek 单元已 AC/3 个测试点，seed_effective=null，约 7.6 秒（单次链路验证，不代表模型综合能力）。证据保存在本机 evidence，不包含密钥、不进入 Git。
