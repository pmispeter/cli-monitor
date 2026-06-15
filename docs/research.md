---
type: reference
created: 2026-06-02
updated: 2026-06-03
area: "[[ClaudeCodex会话监控面板]]"
tags: [research, 技术方案, 工具开发]
status: active
---

# Claude/Codex CLI 会话监控方案

## 目标

构建一个轻量监控器，用来实时查看通过终端或 Obsidian 启动的 Claude/Codex 类 CLI 会话：

- 当前有哪些被监控的 CLI 会话还在运行
- 每个会话最近一次有意义活动是什么时候
- 哪些会话长时间没有活动，应该回去检查

当前版本不试图精确判断“CLI 内部是否正在工作”或“是否正在等待用户输入”。这两个状态在 Claude/Codex 这类 agent CLI 上没有稳定外部信号，直接用 CPU、进程状态或光标状态判断会产生大量误报。

## 当前结论

### 1. 进程扫描适合发现会话，但不适合判断状态

通过 `/proc`、`ps` 或 `psutil` 可以发现 Claude/Codex 进程，并拿到 PID、TTY、cwd、启动时间、命令行等信息。这个方案适合做未包装会话的 fallback。

但进程扫描无法可靠判断“正在工作 / 等待输入”：

- CLI 在模型请求、网络等待、工具调用等待时可能也是 sleep 状态
- CPU 低不代表等待用户输入
- 许多 agent CLI 在工作时也允许用户插入输入，所以 stdin 可写或光标存在没有判别意义
- Codex 常见为父子进程组合，例如 `node ~/.bun/bin/codex` 和 native `codex` binary，需要合并成一个会话
- Obsidian 内嵌终端可能通过 PTY proxy 启动，进程树和普通终端不同

因此当前 MVP 不使用 CPU/进程状态作为主要状态来源。

### 2. Wrapper 是当前更可靠的基础方案

当前实现使用 PTY wrapper 启动 CLI：

```bash
cli-monitor run -- codex
cli-monitor run -- claude --dangerously-skip-permissions
```

wrapper 位于用户终端和真实 CLI 之间：

```text
terminal stdin -> cli-monitor wrapper -> PTY -> claude/codex
claude/codex -> PTY -> cli-monitor wrapper -> terminal stdout
```

这样可以在不改变用户交互体验的前提下记录 session metadata 和活动时间。

当前记录到：

- `id`
- `pid`
- `command`
- `cwd`
- `tty`
- `started_at`
- `updated_at`
- `last_output_at`
- `last_input_at`
- `last_key_at`
- `last_active_at`
- `ended_at`
- `exit_code`

session 文件存放在：

```text
~/.local/state/cli-monitor/sessions/
```

### 3. 状态语义收敛为 LAST_ACTIVE

早期 UI 展示过 `LAST_OUT` 和 `LAST_IN`。实际使用后发现：

- 普通打字会通过 PTY echo 回到屏幕，容易误算成输出
- 窗口切换会产生 terminal focus event
- 窗口切换或 resize 可能触发 CLI 重绘屏幕
- 仅看输出流无法稳定区分“真实新输出”和“重绘”
- 输入和输出时间在日常查看时区别不大，双列增加了扫描成本

因此 UI 把 `LAST_ACTIVE` 作为状态信号展示，同时增加 `LAST_REPLY` 表示最近一次回复估计时间。`LAST_ACTIVE` 由可见屏幕输出驱动，状态在用户首次提交/控制输入后再根据 `LAST_ACTIVE` 判断。

底层仍记录 `last_input_at`，表示最近一次提交/控制输入：

- Enter
- Ctrl-C
- Ctrl-D

`LAST_ACTIVE` 表示最近一次可见屏幕输出，排除纯 echo、ANSI 控制序列、focus event、短时间重绘。

`LAST_REPLY` 和 `LAST_ACTIVE` 使用同一个可见输出信号，但展示不同含义：`LAST_REPLY` 显示最近一次可见输出发生的钟表时间，`LAST_ACTIVE` 显示距那次输出已经过了多久。它用于回答“上一次完整反馈大约是什么时候”，不参与 `busy/wait` 状态计算。

普通打字只记录为 `last_key_at`，暂不作为面板状态依据。

当前状态基于提交/控制输入和 `LAST_ACTIVE`：

| 状态 | 含义 |
| --- | --- |
| `new` | 还没有记录到提交/控制输入 |
| `busy` | 提交/控制输入后，最近 5 秒内有屏幕输出 |
| `wait` | 提交/控制输入后，至少 5 秒没有记录到屏幕输出 |
| `done` | wrapper 子进程已退出 |
| `gone` | session 文件存在，但 PID 已不存在 |

`done` 和 `gone` 默认不在列表中显示，可以通过 `--all` 查看。

### 4. PROJECT 使用 cwd basename

完整 cwd 太长，在终端表格里经常只显示无意义前缀，例如：

```text
/media/peterzheng/disk_large/Codes/cli_m...
```

当前 UI 显示 `PROJECT`，取启动目录 basename，例如：

```text
cli_monitor
qmt_trading
```

wrapper 记录的是启动命令时的当前目录。shell function 不应 `cd` 到固定目录，否则所有 session 都会显示同一个项目。

推荐 shell function：

```bash
codex() {
  cli-monitor run -- /home/peterzheng/.bun/bin/codex "$@"
}

claude() {
  cli-monitor run -- /path/to/claude "$@"
}
```

## 当前已实现

### CLI 命令

```bash
cli-monitor run -- <command> [args...]
cli-monitor list
cli-monitor list --all
cli-monitor watch
cli-monitor watch --all
cli-monitor prune
```

### 当前列表字段

```text
CLI     STATE  PROJECT       LAST_REPLY      PID LAST_ACTIVE     RUNTIME
```

### 已实现行为

- 通过 PTY wrapper 启动命令
- 透明转发 stdin/stdout
- 保留被包装命令的退出码
- 记录 session JSON
- 实时刷新 session 状态
- 默认隐藏 done/gone session
- `prune` 清理 done/gone session
- 排除普通按键、terminal echo、focus event 对 `LAST_ACTIVE` 的干扰
- 展示 `LAST_REPLY` 和 `LAST_ACTIVE`，其中状态计算仍只依赖 `LAST_ACTIVE`
- 将长 cwd 替换为项目 basename
- 使用 curses TUI 原地刷新 `watch` 界面

## 当前限制

### 1. 只准确监控通过 wrapper 启动的会话

已经存在的 Claude/Codex 进程没有 wrapper 层，无法准确获得 `LAST_ACTIVE`。未来可以加入进程扫描 fallback，但需要在 UI 中明确标为低置信信号。

### 2. 无法直接获得 Claude/Codex 对话标题

wrapper 默认只能看到终端输入输出流、cwd、命令、PID。它拿不到 CLI 内部的“对话总结标题”，除非：

- Claude/Codex 暴露稳定 session metadata 或日志
- CLI 把标题明确输出到屏幕，且我们解析它
- 用户启动时手动传 label
- 从窗口标题、Obsidian 上下文或应用 API 获取，但这会变成平台/应用特定逻辑

当前建议优先支持手动 label，而不是自动猜标题。

### 3. 输出重绘无法完全消除

当前实现会过滤 ANSI 控制序列、echo、focus event，并在 focus/resize 后短暂抑制输出刷新。但如果 CLI 在窗口切换后超过抑制窗口主动输出可见文本，wrapper 仍会将其视为活动。这是没有内部状态 API 时的合理边界。

## 后续计划

### 近期

- 支持 `--label`，允许用户给会话手动命名
- 支持显示会话启动时间和运行时长
- 支持只显示指定 project 或 command

### 中期

- 增加进程扫描 fallback，发现未通过 wrapper 启动的 Claude/Codex
- 对 fallback 会话明确显示低置信状态，例如 `unwrapped`
- 为 Obsidian 内嵌终端增加更友好的来源识别
- 增加 TUI 颜色和快捷键提升可用性
- 支持手动结束 session 或打开 session 文件详情

### 长期

- 探索 Claude/Codex 官方日志或 metadata，用于更准确的标题和状态
- 支持平台相关窗口定位，例如普通终端窗口、Obsidian pane、桌面窗口标题
- 支持历史统计和导出，例如每个项目的 agent 使用时长
- 支持跨平台适配，优先 Linux，再评估 macOS

## 设计原则

- 不把低置信推断伪装成准确状态
- 优先展示对工作流有帮助的信号，而不是追求内部状态判断
- wrapper 会话优先，因为它能提供最可靠的活动时间
- fallback 可以存在，但必须明确标注信号来源和置信度
- 默认视图只显示当前需要关注的会话，历史记录通过 `--all` 或 `prune` 管理
