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

### 第三轮：资源计量与统计语义

Docker 测试点继续使用独立容器、相同硬内存/无 swap/PID/CPU 限制、非 root、只读根目录、禁网、cap-drop ALL 和 no-new-privileges。测试容器的 Python PID 1 改为 Docker `--init` 加 `sleep infinity`，降低常驻内存且继续回收孤儿；编译/工作台容器不变。测试监督器从宿主可信源码通过 `python3 -S -c` 启动，选手输出经有界管道收集。监督器禁止 dump/ptrace，选手无法访问其报告管道；杀死监督器只会产生 SE，不会得到伪造的正常退出。无需重建已有镜像。

结果 JSON 的计量口径：

- `container_peak_memory_kb`：内核 `memory.peak`，覆盖整个测试容器自创建后的生命周期，包括 PID 1、sleep、监督器、所有选手子进程、加载/拷贝二进制和 tmpfs 页，以及计量读取进程。`memory_kb` / `peak_memory_kb` 保留为兼容别名；不能解释为选手 RSS。
- `process_peak_rss_kb`：当前 Docker 方案无法可靠获得整棵选手进程树的精确峰值，返回 null；`process_memory_method=unavailable`。不减去基线推导进程峰值。
- `container_baseline_memory_kb`：执行前 `memory.current` 快照，包含读取器自身与初始化/二进制 tmpfs 开销，是观察到的基线，不是固定常数。监督器执行期内存不包含在该基线中。相应 `*_method` 字段记录实际方法。
- `cpu_time_ms`：`cpu.stat:usage_usec` 增量，包含容器内监督与观测开销；不宣称是纯选手 CPU 时间。不能仅因该数值大于题目限额而判 TLE。
- `cgroup.before` / `cgroup.after` 保存原始快照；memory、cpu、pids 分别命名。对应增量仅在前后均可读且计数未回退时计算，否则为 null。计量读取器使用容器内 UID 0（不增加任何 capability），防止选手通过同 UID 的 /proc 文件篡改计量输出；选手仍始终是 UID 1000。读取器自身可能影响 PID 事件，因此 PID 增量仅作诊断，不能证明选手因 PID 限制退出。
- OOM 导致整个容器停止时，cgroup 文件可能不可读：峰值和增量为 null，以保留的 `container_state.OOMKilled` 为 MLE 证据；不伪造进程信号。正常退出、监督器主动超时/输出限制终止而容器仍存活时仍能读取内核峰值。它包含初始化期峰值，未重置为仅选手执行区间。

退出分类：独立记录选手 `exit_code` / `termination_signal` 和 `transport_exit_code`。正常非零退出或实际异常信号为 RE；输出超限为 RE/output_limit；监督器实际观察的 wall 超时为 TLE/timeout；监督器观察选手进程 CPU 时钟或实际 CPU 用量达到预算为 TLE/cpu_timeout（主动发送 SIGXCPU 不足以确认 CPU 超时）。内存 OOM kill 增量或 Docker OOMKilled 为 MLE；单独 memory.max、pids.max、stderr 中的 bad_alloc 或 Docker CLI 137 均不足以推断资源终止。监督器缺失/损坏、Docker 传输错误、无 OOM 证据的意外容器退出为 SE。OOM 可能杀死监督器或 PID 1，因此没有直接的选手 wait 状态时信号和退出码均为 null。

Benchmark 新字段兼容旧的 solve_rate、pass@1 和 token 均值：

| 字段 | 分子 / 分母 |
|---|---|
| `evaluable_solve_rate`（旧 `solve_rate` 别名） | AC / 可评估终态独立 Run；Agent failure 计未解出，Model/Judge/Infrastructure failure 排除 |
| `end_to_end_success_rate` | AC / 全部终态 Finished 或 Failed 独立 Run，包含上述所有失败 |
| `final_end_to_end_success_rate` | 所有计划单元均终态才返回 AC / 全部计划单元，否则 null |
| `failure_breakdown.*.rate` | 对应失败类别数量 / 全部终态 Run |
| `failure_breakdown.*.share_of_failures` | 对应失败类别数量 / 全部失败终态 Run |
| `pending_units` / `running_units` | 未执行 / 执行中的单元数量，不进入上述成功率分母 |
| `pass@1` | 每个题目/模型的首个配置 seed 中，AC / 可评估终态独立 Run；首 seed 被排除时不以其他 seed 替补 |

`solution_failure` 包含 WA/RE/TLE/MLE/CE，其余类别分别为 agent_failure、model_failure、judge_failure、infrastructure_failure；各 verdict 数量另见 `verdict_counts`。没有有效终态分类的记录保守计基础设施失败，SE 计 Judge failure。Failed 记录中的旧 AC 不计成功。成功率可能随实验进展变化，不能把部分完成结果称为全计划最终结果；即使某个模型组先完成，final 字段也等待整个实验完成。overall 汇总全部模型，groups 按模型分别汇总；protocol 保留在实验和 CSV 记录中。iterative 的 pass@1 是允许反馈/修改的首个独立 Agent Run 成功率，不是一次代码生成成功率。一个 Run 内的多次修改永远不是独立样本。

Token 均值沿用可评估终态 Run 的实际观测；只接受非负整数计数，空对象、负数或错误类型视为缺失；缺失为 null，零为零，部分 usage 分别影响对应均值。`tokens_per_solved_problem` 只有全部可评估 Run 的输入/输出 usage 都存在时才计算；不包含被排除的 Model/Judge/Infrastructure failure 的成本，因此不是系统总成本指标。模型解题结果、Agent 失败分布和端到端成功率应一起阅读，不能用 solve_rate 隐藏系统失败。

本轮验收可写入独立证据目录与独立数据库，不覆盖用户数据或既有报告：

```sh
export MINIOJ_EVIDENCE_DIR="$PWD/evidence/round3"
export MINIOJ_DATA="$MINIOJ_EVIDENCE_DIR/data"
mkdir -p "$MINIOJ_EVIDENCE_DIR"
.venv/bin/python -m compileall -q minioj benchmark scripts
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/stage2_resources.py
.venv/bin/python scripts/round3_resources.py
.venv/bin/python scripts/queue_crash_acceptance.py
# 同样环境变量启动 scripts/run.sh 后，顺序运行：
.venv/bin/python scripts/acceptance.py
.venv/bin/python scripts/resource_acceptance.py
.venv/bin/python scripts/benchmark_acceptance.py
MINIOJ_BENCHMARK_PROTOCOL=iterative .venv/bin/python scripts/benchmark_acceptance.py
```

本轮只使用 Fake Adapter，未调用付费模型 API。实际测试数量、结果、实验 ID 和限制见本轮交付记录；这里的命令不是对未执行测试的通过声明。

### 第四轮：独立 CI 与真实 Docker 边界验证

`.github/workflows/tests.yml` 有两个独立 Job，均使用 Ubuntu 24.04 / Python 3.14。`unit` 运行 compileall、完整 unittest 和 20 次同步 SIGXCPU 回归（10 分钟上限）；`docker-integration` 复用 runner 的 Docker Engine，构建一次 Alpine 沙箱镜像，再运行真实资源、安全、判题、队列崩溃恢复，以及 final_only / iterative 各 18 个 Fake Adapter Run（20 分钟上限）。没有 Colima 启动步骤或付费模型调用。

本地复用 CI 入口：

```sh
python3 -m compileall -q minioj benchmark scripts
python3 -m unittest discover -s tests -v
python3 scripts/ci_unit.py --output evidence/round4/unit
# 在已有 Docker Engine 的 Linux 环境，先安装 requirements.lock：
docker build -t minioj-sandbox:ci .
MINIOJ_IMAGE=minioj-sandbox:ci MINIOJ_DOCKER_CONTEXT=default \
  python3 scripts/ci_docker.py --output evidence/round4/docker
```

本轮应重建沙箱镜像，使工作台命令也使用更新后的 LocalRunner。Docker 入口拒绝占用中的 8000/8001 端口；数据库、随机认证令牌、原始日志和导出位于独立临时目录。入口检测实际 cgroup v2、内存峰值/OOM/PID/CPU 指标及 OOM score 调整能力，缺少必需能力会明确失败。脚本有分阶段超时和 15 分钟内部预算，清理只匹配本次随机 session 标签的容器，并检查服务端口释放。生产/开发数据库不参与测试。

Job Summary 显示单元测试 passed/failed/skipped、Docker 各验收阶段（失败时带源码位置和异常类型），以及 Benchmark 的 planned/completed、AC/WA/其他失败和指标校验结果。artifacts 只上传白名单 JSON：测试 ID、计数、资源数值、已知原因、指标汇总和清理结果；不上传原始 stderr/stdout、数据库、manifest、模型消息、隐藏测试或认证信息。失败时同样保存已观测到的脱敏结果，不能用无条件 skip 变绿。

原失败的 300 ms 用例同时覆盖 Python launcher、解释器和调度开销；尚未 exec 到测试程序时，触发墙钟限制本身是正确行为，不能据此要求 RE。现在用原生程序写 ready、控制线程回 ack 后主动发信号，并断言实际用时/CPU 均未达到宽裕的 10 秒测试预算；独立用例仍验证 50/100 ms 的真实墙钟限制和 1 秒 CPU 限制。20 次重复是回归证据，不是无竞态的证明。

LocalRunner 不再把调用方共享 cgroup 的 CPU/OOM/内存归给选手；使用 wait4 保存实际退出状态及 CPU 用量，避免 poll 提前回收丢失证据。墙钟起点仍在 launcher 之前，未人为扣除启动时间。Python launcher 在 exec 前恢复 SIGPIPE/SIGXFSZ 默认处理；等于输出上限的正常输出不会误报超限。

真实 Docker 测试还发现 RLIMIT_CPU 的内核 tick 计量可在 wait4 用量略低于整数秒时发送 SIGXCPU。监督器改为从选手自己的 Linux process CPU clock 明确观察 CPU 预算后终止（实际信号为 SIGKILL），RLIMIT_CPU 保留为晚一秒的内核后备；CPU clock 不可用导致 SE，不用容器总 CPU 或容差猜测。该时钟接口见 [Linux clock_getcpuclockid 文档](https://man7.org/linux/man-pages/man3/clock_getcpuclockid.3.html)。LocalRunner 使用进程树采样预算和 wait4，内核 guard 同样后移一秒；采样仍有时间/峰值盲区。Docker 公开 CPU 指标仍是容器增量，进程 RSS 仍不可用，内存口径不变。主动 SIGXCPU、SIGKILL、SIGXFSZ、exit(137)、真实超时、输出边界、OOM、真实 Docker exec 错误和监督器故障分别验证，不从退出码或错误文本伪造信号。

推送被授权后，可用 `gh run list --workflow tests.yml --commit <SHA>` 查对应提交，再用 `gh run watch <run-id> --exit-status` 和 Job Summary 验证两个 Job。没有对应提交的远端成功结果，不能声称 GitHub Actions 已通过。

额外的确定性竞态测试在选手退出后故意延迟 LocalRunner 的观测；Docker 则由程序 SIGSTOP 监督器、主动 SIGXCPU 退出，再由测试助手延迟恢复监督器。两者均检查实际退出信号不会被监督侧的墙钟延迟覆盖。PID 压力夹具用管道门闩保留子进程，避免 sleep 到期与 fork 竞争导致 PID 事件偶发消失。

### Harness transparency ablation (Phase 6)

This offline research harness independently controls budget disclosure, sandbox disclosure and model-call budget. A/B/C/D allow 6 model calls; E allows 12. Every condition keeps final_only, 16 tools, 180 seconds and the same Docker/Judge limits. The [preregistration](benchmark/experiments/harness_ablation_v1/preregistration.md) and [frozen execution plan](benchmark/experiments/harness_ablation_v1/execution_plan.json) define a randomized 25-Run exploratory study. The earlier 4/15 original score and 11/11 separate post-hoc AC are never rewritten.

```bash
python scripts/harness_ablation.py --validate
python scripts/harness_ablation.py --dry-run
python scripts/audit_legacy_runs.py --output evidence/harness_ablation_v1/legacy_audit.json
python scripts/harness_ablation.py --fake-smoke --output evidence/harness_ablation_v1/new-docker-smoke
# Set MINIOJ_IMAGE to the same pinned image before this Docker boundary check.
python scripts/harness_snapshot_acceptance.py --output evidence/harness_ablation_v1/new-snapshot-check.json
```

These commands make no paid provider calls and do not read API keys. Fake smoke requires the original private evidence and pinned Docker image; it starts its own loopback server and separate database, runs 25 independent reference-code Agents against real Docker Judge, validates JSON/CSV exports, and cleans up its services/containers. Missing Docker or snapshots is an explicit failure, not a silent success. Output directories must be new. Private trajectories, source snapshots and databases stay in ignored `evidence/`; do not publish them. On another machine, historical evidence can be unavailable; the audit reports that state rather than inventing data.

Budget notices are temporary system messages, never accumulated history. The remaining model-response count includes the current response, so its final_submit is allowed. Sandbox disclosures distinguish API/source/file/output/tmpfs limits. Exact injection-only token usage is unavailable (`null`); byte overhead and full provider usage are recorded separately. Diagnostics are additive to existing summary/CSV interfaces. Code-validity rates require independent rejudging, and unknown observations remain unknown.

Read-only post-hoc diagnosis (new output file, never changes original scores):

```bash
python scripts/posthoc_rejudge.py \
  --experiment evidence/real-agent-20261008/trajectories.json \
  --review benchmark/experiments/harness_ablation_v1/legacy_review.json \
  --output evidence/harness_ablation_v1/new-posthoc.json
```

Historical recovery requires matching reviewed trajectory/source hashes, not the present workspace. New experiments capture source privately from a paused owned container before cleanup, or from immutable final submissions. Remote capture without the owning DB/runtime remains unknown. Rejudging pins the original image and verifies baseline-compatible Judge/security source, recording a new diagnostic ID and timestamp.

**Future paid execution is disabled by default and was not run in Phase 6.** After explicit authorization, supply the credential privately through the environment and run:

```bash
python scripts/harness_ablation.py --real --authorize-paid \
  --plan-id 43c5fa6bf0d6064c6c16053d0e19d3e6f1e9d7ff6ba88eb478f08a9899679665 \
  --max-runs 25 --max-model-calls 180 --max-observed-tokens 350000 \
  --output evidence/harness_ablation_v1/authorized-real-unique
```

The observed-token cap stops additional calls; the last response can overshoot it. Missing usage also stops further calls. DeepSeek seed effectiveness is unknown, so repeats are not deterministic pairs. A 75-Run extension requires a new preregistration and authorization. The Fake loop proves implementation behavior, not that transparency improves the real model.

Phase 6 路径说明复测：冻结计划见 `benchmark/experiments/harness_ablation_v2/preregistration.md`。显式传入 `--plan benchmark/experiments/harness_ablation_v2/execution_plan.json`；默认仍为 v1。v2 仅修正 C/D/E 的相对文件路径说明，A/B 与隔离限制保持不变，历史结果不合并。

## Phase 7：终止策略 2×2 实验

预算可见性与提交提醒独立开关，四组共享最小工具协议、相对路径约定和真实沙盒限制。预注册 5 道 Phase 6 冻结题 × 4 组 × 2 次 = 40 独立 Run；各 Run 固定 6 次模型调用、50 次工具调用、300 秒，temperature=0、max_tokens=4096。工具定义和 Judge 不变。计划不会运行时洗牌，也不将事后 AC 改写为原始成功。

无需模型密钥的离线验证：

```bash
python3 scripts/phase7.py --validate
python3 scripts/phase7.py --compare-prompts
python3 scripts/phase7.py --dry-run
# Docker 与原始固定镜像可用时；使用全新独立证据目录
.venv/bin/python scripts/phase7.py --fake-smoke --output evidence/termination_ablation_v1/my-fake-check
```

离线命令不加载生产配置或模型认证信息；Fake 模式不构造真实模型适配器。已有结果目录会被拒绝覆盖。当前阶段不执行付费实验；未来需用户另行明确授权，并显式指定 `--real --authorize-paid --plan-id` 与三个总量上限。理论最大 240 次模型调用，已观察 token 停止阈值 600000，非固定账单保证。

[预注册](benchmark/experiments/termination_ablation_v1/preregistration.md) · [验证报告与未来执行命令](docs/phase7-validation.md)。源码修改时点缺少终端版本证据时为 null；独立复判的来源校验失败亦为未知。
