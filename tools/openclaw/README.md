# OpenClaw 集成工具

这个目录里的脚本用于把 PeerMind Agent 跟 [OpenClaw](https://github.com/) Gateway 对接。

> ⚠️ **这些工具不属于 PeerMind 协议核心**，是作者本地用的 OpenClaw 集成脚本。
> 普通用户不需要跑这里的东西，看 `examples/` 下的 demo 即可。

## 文件说明

### `approve_device.py`

连接 OpenClaw Gateway 的设备配对工具，走的是 **OpenClaw 自己的配对协议**（`connect.challenge` / `device.pair.approve`），**不是 PeerMind 协议**。

认证流程：
1. 连接 WebSocket → 收到 `connect.challenge`（含 nonce）
2. 用 Ed25519 私钥签名 nonce → 发回 `connect.response`
3. 发送 `connect` 消息（含 token + device identity）→ 收到 `connect.hello`
4. 发送 `device.pair.approve` → 批准完成

## 运行

### 额外依赖

`approve_device.py` 用 `cryptography` 库（不是 PeerMind 核心的 `pynacl`），需要单独装：

```bash
pip install cryptography
```

### 环境变量

```bash
export AGENT_NETWORK_TOKEN=你的OpenClawToken
python tools/openclaw/approve_device.py
```

### 前置条件

- 本地启动 OpenClaw Gateway（默认 `ws://127.0.0.1:18789`）
- 拥有有效的 `AGENT_NETWORK_TOKEN`

## 为什么放在单独目录

PeerMind 协议本身是跨平台、跨框架的开放协议，**不依赖 OpenClaw**。
这里只是作者把自己的 OpenClaw 集成脚本一并开源，方便有类似需求的人参考。
如果你不需要对接 OpenClaw，**完全可以忽略这个目录**。
