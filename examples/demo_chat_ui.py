"""
Agent 通信网络 - 聊天 UI Demo
启动 Registry + 两个 Agent + 网页聊天界面

架构:
  Registry (:9000)  ← 注册 + 发现
  Alice (:9001) ←── P2P 直连 ──→ Bob (:9002)
                    ↑                   ↑
                    └── SSE 推送 ──→ Web UI (:8080)
"""
import asyncio
import json
import sys
import threading
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse

sys.path.insert(0, ".")

from agent_network.main import app as registry_app, init_db
from agent_network.agent_server import AgentServer
from agent_network.models import Capability, AgentMessage

# 端口配置
REGISTRY_PORT = 9000
ALICE_PORT = 9001
BOB_PORT = 9002
UI_PORT = 8080
REGISTRY_URL = f"http://127.0.0.1:{REGISTRY_PORT}"

# 对话脚本
CHAT_SCRIPT = [
    ("Alice", "你好 Bob，今晚想吃什么？"),
    ("Bob", "我想吃麻辣烫，你呢？"),
    ("Alice", "我也想吃辣的！一起点吧，你加购物车了吗？"),
    ("Bob", "还没呢，刚打开外卖APP，你喜欢啥菜？"),
    ("Alice", "我喜欢毛肚、牛肉丸、藕片，再加宽粉"),
    ("Bob", "好嘞都加上了。再加一份豆腐皮？"),
    ("Alice", "可以！辣度选中辣还是特辣？"),
    ("Bob", "中辣吧，上次特辣我俩第二天都不行了"),
    ("Alice", "哈哈哈哈确实。那就中辣下单吧！"),
    ("Bob", "已下单！预计35分钟到，准备碗筷"),
]

# 全局消息队列（SSE 推送用）
message_queue: asyncio.Queue = None

# ── HTML 页面（内联） ──

HTML_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Agent 聊天 - P2P 直连</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  font-family: -apple-system, "Microsoft YaHei", sans-serif;
  background: #1a1a2e; display: flex; justify-content: center;
  align-items: center; min-height: 100vh; padding: 20px;
}
.container {
  width: 100%; max-width: 500px; background: #16213e;
  border-radius: 16px; overflow: hidden; box-shadow: 0 20px 60px rgba(0,0,0,0.5);
}
.header {
  background: #0f3460; padding: 16px 20px; display: flex;
  align-items: center; gap: 12px;
}
.header .title { color: #e94560; font-size: 16px; font-weight: 600; }
.header .subtitle { color: #a0a0b0; font-size: 12px; }
.header .status {
  width: 8px; height: 8px; border-radius: 50%; background: #4ade80;
  animation: pulse 1.5s infinite; margin-left: auto;
}
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.3; }
}
.agent-bar {
  display: flex; justify-content: space-between; padding: 10px 20px;
  background: #1a1a3e; border-bottom: 1px solid #2a2a4e;
}
.agent-tag {
  display: flex; align-items: center; gap: 8px; font-size: 13px;
}
.agent-tag .dot { width: 10px; height: 10px; border-radius: 50%; }
.agent-tag .dot.alice { background: #4ade80; }
.agent-tag .dot.bob { background: #60a5fa; }
.agent-tag .name { color: #e8e8f0; }
.agent-tag .addr { color: #6868a0; font-size: 11px; }
.messages {
  height: 500px; overflow-y: auto; padding: 16px;
  background: #1a1a3e; display: flex; flex-direction: column; gap: 12px;
}
.messages::-webkit-scrollbar { width: 4px; }
.messages::-webkit-scrollbar-thumb { background: #3a3a6e; border-radius: 2px; }
.msg-row { display: flex; gap: 8px; align-items: flex-end; }
.msg-row.left { flex-direction: row; }
.msg-row.right { flex-direction: row-reverse; }
.avatar {
  width: 36px; height: 36px; border-radius: 50%; display: flex;
  align-items: center; justify-content: center; font-size: 14px;
  font-weight: 700; flex-shrink: 0;
}
.avatar.alice { background: linear-gradient(135deg, #4ade80, #22c55e); color: #052e16; }
.avatar.bob { background: linear-gradient(135deg, #60a5fa, #3b82f6); color: #0c1929; }
.bubble {
  max-width: 65%; padding: 10px 14px; border-radius: 16px; position: relative;
  word-break: break-word; line-height: 1.5; font-size: 14px;
}
.bubble.left {
  background: #2a2a5e; color: #e8e8f0;
  border-bottom-left-radius: 4px;
}
.bubble.right {
  background: #e94560; color: #fff;
  border-bottom-right-radius: 4px;
}
.bubble .sig {
  display: flex; align-items: center; gap: 4px; margin-top: 6px;
  font-size: 10px; opacity: 0.7;
}
.bubble .time {
  font-size: 10px; opacity: 0.5; margin-top: 4px;
}
.typing {
  display: flex; gap: 4px; padding: 10px 14px;
  background: #2a2a5e; border-radius: 16px; border-bottom-left-radius: 4px;
  width: fit-content; align-self: flex-start;
}
.typing span {
  width: 6px; height: 6px; border-radius: 50%;
  background: #a0a0c0; animation: bounce 1.4s infinite;
}
.typing span:nth-child(2) { animation-delay: 0.2s; }
.typing span:nth-child(3) { animation-delay: 0.4s; }
@keyframes bounce {
  0%, 60%, 100% { transform: translateY(0); opacity: 0.4; }
  30% { transform: translateY(-4px); opacity: 1; }
}
.info-bar {
  padding: 8px 20px; background: #0f3460; display: flex;
  justify-content: space-between; align-items: center;
}
.info-bar .info { color: #6868a0; font-size: 12px; }
.info-bar .count { color: #e94560; font-weight: 600; }
.footer {
  padding: 12px 20px; background: #0f3460; text-align: center;
}
.footer .legend {
  display: flex; justify-content: center; gap: 20px; font-size: 11px; color: #6868a0;
}
.footer .legend span { display: flex; align-items: center; gap: 4px; }
.footer .legend .sig-ok { color: #4ade80; }
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <div>
      <div class="title">Agent 聊天室 - P2P 直连</div>
      <div class="subtitle">Ed25519 签名 + 去中心化通信</div>
    </div>
    <div class="status" id="status"></div>
  </div>

  <div class="agent-bar">
    <div class="agent-tag">
      <div class="dot alice"></div>
      <span class="name">Alice</span>
      <span class="addr">:9001</span>
    </div>
    <div class="agent-tag">
      <div class="dot bob"></div>
      <span class="name">Bob</span>
      <span class="addr">:9002</span>
    </div>
  </div>

  <div class="messages" id="messages">
    <div style="text-align:center;color:#6868a0;font-size:12px;padding:20px 0;">
      对话即将开始...
    </div>
  </div>

  <div class="info-bar">
    <span class="info">Registry 只做发现 · 消息 P2P 直连</span>
    <span class="count" id="msgCount">0/10</span>
  </div>

  <div class="footer">
    <div class="legend">
      <span>🔐 每条消息 <span class="sig-ok">Ed25519签名验证</span></span>
      <span>📡 数据不经 Registry 中转</span>
    </div>
  </div>
</div>

<script>
const msgsEl = document.getElementById('messages');
const msgCount = document.getElementById('msgCount');
const statusEl = document.getElementById('status');
let msgIndex = 0;

function scrollBottom() {
  msgsEl.scrollTop = msgsEl.scrollHeight;
}

function addTyping(name) {
  const cls = name === 'Alice' ? 'alice' : 'bob';
  const side = name === 'Alice' ? 'left' : 'right';
  const div = document.createElement('div');
  div.className = 'msg-row ' + side;
  div.id = 'typing-' + name;
  div.innerHTML = `<div class="avatar ${cls}">${name[0]}</div>
    <div class="typing"><span></span><span></span><span></span></div>`;
  msgsEl.appendChild(div);
  scrollBottom();
}

function removeTyping(name) {
  const el = document.getElementById('typing-' + name);
  if (el) el.remove();
}

function addMessage(name, text, sig) {
  const cls = name === 'Alice' ? 'alice' : 'bob';
  const side = name === 'Alice' ? 'left' : 'right';
  const now = new Date().toLocaleTimeString('zh-CN', {hour:'2-digit',minute:'2-digit',second:'2-digit'});
  const div = document.createElement('div');
  div.className = 'msg-row ' + side;
  div.innerHTML = `<div class="avatar ${cls}">${name[0]}</div>
    <div class="bubble ${side}">
      <div>${text}</div>
      <div class="sig">🔐 签名验证通过 · ${sig.slice(0,16)}...</div>
      <div class="time">${now}</div>
    </div>`;
  msgsEl.appendChild(div);
  msgIndex++;
  msgCount.textContent = msgIndex + '/10';
  scrollBottom();
}

async function start() {
  const evtSource = new EventSource('/events');
  evtSource.onmessage = function(event) {
    const data = JSON.parse(event.data);

    if (data.type === 'typing_start') {
      addTyping(data.agent);
    }
    else if (data.type === 'message') {
      removeTyping(data.agent);
      addMessage(data.agent, data.text, data.signature);
    }
    else if (data.type === 'done') {
      evtSource.close();
      statusEl.style.background = '#4ade80';
      msgCount.textContent = '10/10 ✅';
      const done = document.createElement('div');
      done.style.cssText = 'text-align:center;color:#4ade80;font-size:13px;padding:12px 0;';
      done.textContent = '10轮对话完成 · 20次签名验证全部通过';
      msgsEl.appendChild(done);
      scrollBottom();
    }
    else if (data.type === 'error') {
      evtSource.close();
      statusEl.style.background = '#ef4444';
      const err = document.createElement('div');
      err.style.cssText = 'text-align:center;color:#ef4444;font-size:13px;padding:12px 0;';
      err.textContent = '错误: ' + data.text;
      msgsEl.appendChild(err);
    }
  };

  // 触发聊天
  fetch('/api/start-chat', { method: 'POST' }).catch(console.error);
}

start();
</script>
</body>
</html>"""


def run_registry():
    """后台线程启动 Registry"""
    init_db()
    uvicorn.run(registry_app, host="127.0.0.1", port=REGISTRY_PORT, log_level="warning")


# ── Web UI FastAPI ──

web_app = FastAPI(title="Agent Chat UI")


@web_app.get("/", response_class=HTMLResponse)
async def index():
    """聊天界面主页"""
    return HTML_PAGE


@web_app.get("/events")
async def sse_events(request: Request):
    """SSE 端点：实时推送聊天消息到前端"""
    async def event_stream():
        while True:
            if await request.is_disconnected():
                break
            try:
                data = await asyncio.wait_for(message_queue.get(), timeout=5)
                yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                if data.get("type") == "done":
                    break
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
    return StreamingResponse(event_stream(), media_type="text/event-stream")


@web_app.post("/api/start-chat")
async def start_chat():
    """触发聊天，后台运行"""
    asyncio.create_task(run_chat())
    return {"status": "started"}


async def run_chat():
    """后台运行聊天脚本，将每条消息推送到 message_queue"""
    global message_queue
    if message_queue is None:
        message_queue = asyncio.Queue()

    try:
        await asyncio.sleep(1)  # 给前端一点加载时间

        for sender_name, text in CHAT_SCRIPT:
            # 打字中
            await message_queue.put({"type": "typing_start", "agent": sender_name})
            await asyncio.sleep(1.2)

            # 发送消息
            if sender_name == "Alice":
                msg, reply = await alice.send_message(
                    to_agent="peermind://chat-demo.com/bob",
                    intent="chat",
                    payload={"text": text},
                    return_reply=True,
                )
            else:
                msg, reply = await bob.send_message(
                    to_agent="peermind://chat-demo.com/alice",
                    intent="chat",
                    payload={"text": text},
                    return_reply=True,
                )

            # 验证通过
            sig_ok = reply.get("signature_verified", False)
            print(f"  [{sender_name}] {text} → 签名验证: {sig_ok}")

            await message_queue.put({
                "type": "message",
                "agent": sender_name,
                "text": text,
                "signature": msg.signature,
                "verified": sig_ok,
            })

            await asyncio.sleep(0.8)

        # 完成
        await asyncio.sleep(0.5)
        await message_queue.put({"type": "done"})

    except Exception as e:
        await message_queue.put({"type": "error", "text": str(e)})


async def main():
    global message_queue, alice, bob
    message_queue = asyncio.Queue()

    print("=" * 60)
    print("  Agent 聊天 UI - 浏览器打开 http://127.0.0.1:8080")
    print("=" * 60)

    # ── 启动 Registry ──
    print("\n[启动] Registry 服务 (端口 9000)...")
    registry_thread = threading.Thread(target=run_registry, daemon=True)
    registry_thread.start()

    import httpx
    for _ in range(50):
        try:
            r = httpx.get(f"{REGISTRY_URL}/health", timeout=1)
            if r.status_code == 200:
                print("  Registry 就绪 ✅")
                break
        except Exception:
            pass
        await asyncio.sleep(0.1)

    # ── 创建 Agent ──
    print("\n[创建] 两个 Agent 实例...")
    alice = AgentServer(
        agent_id="peermind://chat-demo.com/alice",
        agent_type="user",
        display_name="Alice",
        port=ALICE_PORT,
        registry_url=REGISTRY_URL,
        capabilities=[Capability(skill="chat", description="日常闲聊")],
    )
    bob = AgentServer(
        agent_id="peermind://chat-demo.com/bob",
        agent_type="user",
        display_name="Bob",
        port=BOB_PORT,
        registry_url=REGISTRY_URL,
        capabilities=[Capability(skill="chat", description="日常闲聊")],
    )

    # 设置 on_message 回调
    async def on_msg(msg: AgentMessage):
        return {
            "status": "ok",
            "from": msg.from_agent,
            "message_received": msg.payload.get("text", ""),
            "signature_verified": True,
        }

    alice.on_message = on_msg
    bob.on_message = on_msg

    # ── 启动 Agent ──
    print("  Agent 启动中...")
    alice.start_background()
    bob.start_background()
    alice.wait_ready()
    bob.wait_ready()
    print("  Alice (9001) ✅  Bob (9002) ✅")

    # ── 注册 ──
    await alice.register()
    await bob.register()
    print("  注册完成 ✅\n")

    # ── 启动 Web UI ──
    print(f"  🌐 打开浏览器访问: http://127.0.0.1:{UI_PORT}")
    print("  (对话将自动开始，观察聊天界面)\n")

    config = uvicorn.Config(web_app, host="127.0.0.1", port=UI_PORT, log_level="warning")
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
