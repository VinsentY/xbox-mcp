# xbox-mcp

[English](README.md) | [简体中文](README.zh-CN.md)

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![MCP](https://img.shields.io/badge/MCP-Model%20Context%20Protocol-green.svg)](https://modelcontextprotocol.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

一个轻量、纯本地运行的 **Model Context Protocol (MCP)** 服务，**直连微软官方 Xbox Live API**——无需任何第三方聚合 API Key（如 OpenXBL），无免费额度/付费限制，所有 OAuth 令牌仅保存在你自己的电脑上。

让你可以在 AI 助手中直接查询 **Xbox 主机与 PC Game Pass** 游戏库、精确游玩时长（`MinutesPlayed`）、成就进度与全球稀有度、实时在线状态、好友列表以及全库时长汇总。

---

## 核心特性

- **直连微软官方接口**：基于 [`xbox-webapi`](https://github.com/OpenXbox/xbox-webapi-python) 直接调用官方 `TitleHub`、`UserStats`、`Achievements`、`Profile`、`Presence`、`PeopleHub` 接口，不经过任何第三方中转。
- **高速批量拉取游玩时长**：通过 `userstats/batch` 以 **50 款一批** 并发拉取 `MinutesPlayed`，上百款游戏也能在 1–2 秒内拿到精确分钟数。
- **自动区分 Xbox 游戏与 Win32 足迹**：清晰分离 Xbox / PC Game Pass 原生记录与 Windows Xbox Game Bar 自动记录的第三方 PC 游戏（Steam / Riot / 战网等），统计口径更干净。
- **极简本地登录授权**：支持命令行一键浏览器回调（`uv run xbox-auth`）和对话内粘贴回调链接（`get_auth_status` + `complete_auth`）两种方式；令牌以 `0600` 权限落盘并自动无感续期。
- **跨世代成就支持**：支持 Xbox One / Series X|S / PC 成就与全球解锁稀有度百分比，并自动兼容回退至 Xbox 360 游戏成就。

---

## 环境要求

- **Python 3.12+**
- **[uv](https://docs.astral.sh/uv/)**（推荐）
- 微软 / Xbox 账号

---

## 快速开始

### 1. 通过 `uvx` 一行运行（推荐，无需克隆仓库）

```bash
# 首次登录微软 / Xbox 账号授权
uvx --from xbox-mcp xbox-auth

# 运行 MCP 服务
uvx xbox-mcp
```

或本地克隆开发运行：

```bash
git clone https://github.com/VinsentY/xbox-mcp.git
cd xbox-mcp
uv sync
uv run xbox-auth
```

### 2. 完成一次微软 / Xbox 账号登录授权

以下两种方式任选其一：

#### 方式 A：命令行一键自动回调（推荐）

```bash
uv run xbox-auth
```

命令会在本机临时监听 `http://localhost:8080/auth/callback` 并自动打开微软官方登录页。登录同意授权后，会自动换取 OAuth2 + XBL + XSTS 令牌并以 `0600` 权限保存到本机。

#### 方式 B：在对话内手动完成授权

如果不方便在终端启动监听（或 8080 端口被占用）：

1. 让 AI 调用 `get_auth_status`，获取微软官方登录链接 `login_url`。
2. 在浏览器登录微软账号并确认授权，浏览器会跳转到 `http://localhost:8080/auth/callback?code=...`（页面提示无法访问属正常现象）。
3. 复制浏览器地址栏中的完整链接，传给 `complete_auth` 工具（或在终端运行 `uv run xbox-auth --code "<回调链接>"`）。

> **令牌保存与自动续期说明**
> 令牌默认保存在本机 `~/Library/Application Support/xbox/tokens.json`（macOS）或 `~/.local/share/xbox/tokens.json`（Linux），可通过环境变量 `XBOX_TOKENS_FILE` 自定义。每次调用接口时会自动检查并刷新过期的 Access / XSTS 令牌，同时写回更新后的 Refresh Token。

---

## MCP 客户端配置

### Antigravity（`~/.gemini/config/mcp_config.json`）/ Claude Desktop / Cursor

通过 `uvx` 启动（推荐，免克隆、自动拉取 PyPI 包）：

```json
{
  "mcpServers": {
    "xbox": {
      "command": "uvx",
      "args": ["xbox-mcp"],
      "env": {
        "XBOX_LANGUAGE": "zh-CN"
      }
    }
  }
}
```

或使用本地克隆后的虚拟环境可执行文件：

```json
{
  "mcpServers": {
    "xbox": {
      "command": "/absolute/path/to/xbox-mcp/.venv/bin/xbox-mcp",
      "args": [],
      "env": {
        "XBOX_LANGUAGE": "zh-CN"
      }
    }
  }
}
```

### 可选环境变量

| 变量名 | 默认值 | 说明 |
|---|---|---|
| `XBOX_TOKENS_FILE` | 系统应用数据目录 `xbox/tokens.json` | 自定义本地 OAuth 令牌保存路径 |
| `XBOX_LANGUAGE` | `en-US` | Xbox API 返回的语言区域（如 `zh-CN`、`en-US`、`ja-JP`） |
| `XBOX_CLIENT_ID` | OpenXbox 公开 Client ID | 如需使用自建 Azure 应用可覆盖 |
| `XBOX_CLIENT_SECRET` | *(空)* | 自建机密应用时选填 |
| `XBOX_REDIRECT_URI` | `http://localhost:8080/auth/callback` | 与自定义应用匹配的 OAuth 回调地址 |

---

## 提供的工具（10 个）

| 工具名 | 功能说明 |
|---|---|
| `get_auth_status` | 检查本机 Xbox OAuth 令牌是否有效；未登录时返回微软登录 URL |
| `complete_auth` | 传入回调 URL（`http://localhost:8080/auth/callback?code=...`）或授权码换取并保存令牌 |
| `get_profile` | 获取 Gamertag、成就点数（Gamerscore）、账号等级、年限、简介与头像 |
| `get_presence` | 查询在线状态以及当前正在游玩的设备与游戏（Xbox 主机 / PC / 云游戏） |
| `get_game_library` | 拉取 Xbox / PC Game Pass 全量游戏记录并补全 `MinutesPlayed` 时长；支持按时长/近期/成就/名称排序，以及 `platform`、`game_pass_only`、`tracked_only`、`exclude_win32_footprints` 过滤 |
| `get_recently_played` | 快速查看近期游玩的游戏、时长与成就进度 |
| `get_playtime_summary` | 生成全库汇总报告：总时长、Xbox 主机 vs PC 分布、Game Pass 占比、时长分段、100% 全成就名单、Win32 足迹数与 Top 20 榜单 |
| `get_game_achievements` | 查询单款游戏的完整成就列表、解锁时间、Gamerscore 与全球稀有度百分比（支持按 `rarity` / `gamerscore` / `unlock_time` 排序） |
| `get_game_stats` | 通过 `title_id` 或 `scid` 查询单款游戏的 `MinutesPlayed` 与 Hero 统计项 |
| `get_friends_list` | 获取 Xbox Live 好友列表、在线状态、成就点数与当前正在玩的游戏 |

---

## 使用示例

- 「帮我汇总一下我的 Xbox 和 PC Game Pass 游玩时长，生成一份游戏画像」
- 「列出我游玩时间最长的 20 款 Xbox / Game Pass 游戏，过滤掉 Win32 Game Bar 足迹」
- 「查一下我在《光与影：33号远征队》里解锁的最稀有的成就」
- 「把我的 Steam 和 Xbox 游戏库合并分析一下」
- 「看看我现在有哪些 Xbox 好友在线，都在玩什么」

---

## 常见问题排查

- **登录时弹出 Passkey 引导页（`account.live.com/interrupt/passkey`）**：点击页面上的「暂时跳过 / 取消」，随后在权限确认页点「接受 / 是」，直到地址栏跳转到 `http://localhost:8080/auth/callback?code=...`。
- **`account.live.com` 提示连接关闭（`ERR_CONNECTION_CLOSED`）**：国内直连或部分分流规则可能导致 `login.live.com` 与 `account.live.com` 线路不一致，请确保 `login.live.com`、`account.live.com` 和 `*.xboxlive.com` 统一走稳定代理节点后刷新即可。
- **为什么部分 PC 游戏没有时长（显示 `0m` / `null`）**：Windows Xbox Game Bar 会自动将你运行过的非 Xbox 平台游戏（如 Steam、LOL、战网等）以 `Win32` 设备记录到 TitleHub，这类记录不包含 Xbox 官方 `MinutesPlayed` 统计。调用 `get_game_library` 时传入 `exclude_win32_footprints=true` 或 `tracked_only=true` 即可只看真正的 Xbox / Game Pass 游戏。

---

## 本地开发与测试

```bash
uv sync
uv run python -m unittest discover -s tests -v
```

---

## 安全与隐私说明

- 所有微软 OAuth2 令牌均**仅保存在你本地磁盘**（文件权限 `0600`），不会上传到任何第三方服务器。
- `.gitignore` 已默认屏蔽 `tokens.json`、`*tokens*.json` 与 `.env*`，请勿将本地令牌文件提交到公开仓库。

## 开源协议

[MIT](LICENSE)
