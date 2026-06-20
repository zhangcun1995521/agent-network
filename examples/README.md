# Examples / 示例

> 本目录下的脚本依赖项目根目录的 `agent_network/` 和 `adapters/` 模块。
> **必须从仓库根目录运行**，否则会 `ModuleNotFoundError`。

## 运行方式

从仓库根目录（不是 `examples/` 里）执行：

```bash
# ✅ 正确
cd agent-network/
python -m examples.demo

# ❌ 错误 —— 找不到 agent_network 模块
cd agent-network/examples/
python demo.py
```

## 示例索引

| 文件 | 功能 | 需要 API Key |
|---|---|---|
| `demo.py` | 最小示例：身份生成、签名、验签 | ❌ |
| `demo_p2p.py` | 两个 Agent 直连 P2P 通信 | ❌ |
| `demo_ws.py` | WebSocket 网关 + Agent 注册 | ❌ |
| `demo_chat.py` | 双 Agent 聊天（mock 回复） | ❌ |
| `demo_chat_real.py` | 双 Agent 真实对话 | ✅ DEEPSEEK_API_KEY |
| `demo_chat_ui.py` | 终端 UI 版聊天（mock） | ❌ |
| `demo_chat_ui_real.py` | 终端 UI 版聊天（真 LLM） | ✅ DEEPSEEK_API_KEY |
| `demo_codebuddy_adapter.py` | CodeBuddy 适配器最小示例 | ❌ |
| `demo_codebuddy_peer.py` | CodeBuddy Peer 通信 | ❌ |
| `demo_codebuddy_peer_ui.py` | CodeBuddy Peer 带 UI | ❌ |

## 设置环境变量

```bash
# Windows PowerShell
$env:DEEPSEEK_API_KEY = "sk-xxxxx"

# Linux / macOS
export DEEPSEEK_API_KEY=sk-xxxxx
```
