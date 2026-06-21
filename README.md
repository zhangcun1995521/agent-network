# PeerMind — Agent 通信网络协议

> 让任何 Agent（无论属于哪个组织、运行在哪个平台）都能互相发现、建立连接、交换结构化信息、形成信任网络。

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Status](https://img.shields.io/badge/Status-Draft%20v0.1-orange.svg)](SPEC.md)
[![Python](https://img.shields.io/badge/Python-3.9%2B-green.svg)](#)

---

## 这是什么

**PeerMind** 是一套 Agent 之间的**身份、发现、通信、信任基础设施**，目标是成为 Agent 时代的 TCP/IP——开放协议、参考实现、谁都能接。

当下 Agent 领域最大的结构性空白：**Agent 正在从"工具"变成"参与者"，但它们还没有自己的通信网络。**

- Claude 的 Agent 无法给 GPT 的 Agent 发消息
- LangGraph 的 Agent 不能直接调 CrewAI 的 Agent
- 没有全球唯一的 Agent ID
- 没有 Agent 发现机制
- 没有 Agent 之间的信任度网络

PeerMind 试图解决这个问题。

## 核心设计原则

1. **去中心化优先** —— 核心协议不依赖任何中心化组件
2. **跨平台、跨框架** —— 不绑定任何 LLM 厂商或 Agent 框架
3. **身份基于密码学** —— Ed25519 公钥即身份，无需中心化注册

完整设计见 **[SPEC.md](SPEC.md)**（27KB 协议规范，v0.1 草案）。

## 仓库结构

```
agent-network/
├── SPEC.md                  # 协议规范（核心文档）
├── agent_network/           # 协议参考实现
├── adapters/                # 各 Agent 框架的适配器
├── examples/                # 可运行示例
│   ├── demo.py              # 最小示例
│   ├── demo_p2p.py          # P2P 通信
│   ├── demo_ws.py           # WebSocket 网关
│   ├── demo_chat_*.py       # 聊天场景
│   └── demo_codebuddy_*.py  # CodeBuddy 适配器示例
├── tools/                   # 辅助工具（非协议核心）
│   └── openclaw/            # OpenClaw Gateway 集成脚本
├── tests/                   # 测试
└── requirements.txt
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

依赖：FastAPI / uvicorn / pynacl / pydantic / websockets

### 2. 跑最小示例

```bash
python -m examples.demo
```

### 3. 跑双 Agent 真实对话（需要 DeepSeek API Key）

```bash
export DEEPSEEK_API_KEY=sk-xxxxx
python -m examples.demo_chat_real
```

### 4. OpenClaw Gateway 配对（可选，非协议核心）

见 [`tools/openclaw/`](tools/openclaw/) 目录。

## 当前状态

- ✅ 协议规范 v0.1 草案
- ✅ 参考实现（身份、注册、P2P、WebSocket 网关）
- ✅ CodeBuddy 适配器原型
- 🚧 MVP 网络（公开测试网）
- 🚧 信任度网络
- 📋 路线图见 SPEC.md 第十节

## 贡献

协议尚在草案阶段，欢迎在 Issue 中讨论：

- 协议设计问题
- 适配器实现需求
- 安全 / 隐私考量
- 与现有协议（MCP、A2A 等）的关系

## License

[Apache License 2.0](LICENSE) © 2026 张存

## 相关项目

- [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) — Agent 与工具的通信协议（互补关系）
- [Agent2Agent (A2A)](https://github.com/google/A2A) — Google 提出的 Agent 间通信标准（参考与对比）
