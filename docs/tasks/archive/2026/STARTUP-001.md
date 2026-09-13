# STARTUP-001 — Live Demo 单终端启动编排

Status: Completed  
Owner: Runtime and demo owners  
Risk: Boundary  
Completed: 2026-09-13

## Goal

提供一条可复现的本地 Live API 启动命令，按依赖就绪顺序启动 llama-server、Presales API 和 Gradio，
打开唯一确定的页面地址，并在 `Ctrl-C` 时清理启动器创建的全部子进程。

## Non-goals

- 不部署生产环境，不替代 Docker Compose、OIDC/JWT、密钥管理或进程管理器。
- 不自动终止启动器之外的旧进程，不使用模糊 `pkill` 或端口抢占。
- 不把 Replay 改成 Live，也不让 UI 绕过 `/readyz`、需求门、幂等键或状态版本。

## 根因证据

1. 原有本地流程要求用户分别启动 llama-server、Presales API 和 Gradio，任一进程启动失败都要人工判断；
   这使模型 alias、API URL、token 和端口容易漂移。
2. 8080、8090 被旧服务占用时，重复启动可能失败；Gradio 还可能自动选择 7861，用户继续打开旧地址后会
   看到旧页面，从而把页面实例混淆误判成 Live API 或控件故障。
3. API 的 `/healthz` 只表示进程存活；真正允许创建 run 的条件是 `/readyz` 返回 200，且数据库、知识库和
   与 llama-server alias 一致的模型均就绪。原流程没有把这些条件组成启动门。

## Scope

- 新增单终端 `scripts/start_local_demo.py`，默认使用本机 Qwen3 1.7B GGUF、alias `qwen3-1.7b-demo`、
  8080/8090/7860 三个固定本地端口和 Live 初始模式。
- 启动 llama-server 后轮询 `/v1/models`，确认 alias 真正暴露；再启动 API 并轮询 `/readyz`；最后启动
  Gradio 并检查页面可达。
- 三个子进程各自使用独立进程组；信号退出时先优雅停止，超时后只强制结束该启动器创建的进程组。
- 端口占用、模型缺失、可执行文件缺失、alias 不一致和 readiness 超时均 fail fast，并输出下一步。
- `Makefile`、README 和演示脚本只把单终端启动器作为 Live API 的主路径；Replay 仍可离线运行。

## Compatibility policy

启动器不新增 HTTP 路径或持久化格式。它把同一个 alias 同时传给 `llama-server --alias` 和
`serve_agent.py --model`，并通过环境变量把同一个本地 token 传给 API 与 Gradio。默认 checkpoint 路径、
OpenAPI `/v2`、`/readyz` 语义和 UI 状态门保持不变。

## Acceptance

- 一条命令可启动三个本地服务，并只打印/使用一个默认 UI 地址 `http://127.0.0.1:7860`。
- llama-server 未暴露目标 alias、API `/readyz` 非 200 或 UI 端口冲突时不会进入“看似可用”的半启动状态。
- `Ctrl-C` 后 8080、8090、7860 不再由本次启动器的子进程监听；启动器不删除旧数据库或模型文件。
- Live 页面首屏进入 Live API，能够输入补充草稿；首次分析进入允许澄清的状态后可提交补充信息。

## Verification

- `tests/test_local_demo_launcher.py` 验证模型 alias、API URL、固定端口和 Live 初始模式一致。
- 使用 18080/18090/17860 隔离端口做真实启动、`/v1/models`、`/readyz`、Gradio 页面可达和 Ctrl-C 清理验收。
- `make test`、`make lint`、`make governance`、`make openapi-check`、`make demo-replay-check`、
  `make security-check`、`make file-length`、`git diff --check`。

## Blockers

无。本地 launcher 仍要求用户已安装 `uv`、`llama-server` 并准备合法的 GGUF 文件；生产环境必须使用
经过授权的编排、身份、密钥、日志和容量方案。
