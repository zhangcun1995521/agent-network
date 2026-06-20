"""
PeerMind 聊天网络 - 三人 P2P 实时聊天
浏览器打开 http://127.0.0.1:8080 实时观看 Alice、Bob 和你对话

架构:
  Registry (15000)  ← 注册 + 发现
  Alice  (15001) ←── P2P 直连 ──→ Bob    (15002)
      ↑                               ↑
      │         P2P 直连               │
      └────────────┬──────────────────┘
                   ↓
              Human (15003)  ← 你也是正式 PeerMind Agent
                    ↑
                    └── SSE 推送 ──→ Web UI (8080)

特点:
  - Alice 和 Bob 调 DeepSeek LLM 生成回复
  - 你作为正式 PeerMind Agent 参与，有身份 + Ed25519 密钥
  - 三人轮转：Alice → Bob → 你 → Alice → ...
  - 你的消息走完整 P2P 链路（签名 + 验证）
"""
import asyncio
import httpx
import json
import os
import sys
import threading
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse

sys.path.insert(0, ".")

from agent_network.main import app as registry_app, init_db
from agent_network.agent_server import AgentServer
from agent_network.models import Capability, AgentMessage

# ── 配置 ──

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE = "https://api.deepseek.com/v1"
DEEPSEEK_MODEL = "deepseek-chat"

REGISTRY_PORT = 15000
ALICE_PORT = 15001
BOB_PORT = 15002
HUMAN_PORT = 15003
UI_PORT = 8080
REGISTRY_URL = f"http://127.0.0.1:{REGISTRY_PORT}"

MAX_TURNS = 18  # 三人对话需要更多轮数

# ── Agent 人设（三人聊天）──

ALICE_PERSONA = """你是 Alice，一个活泼开朗的女生，职业是UI设计师。
你现在在一个三人聊天群里，群里还有 Bob（后端程序员）和一个人类朋友"你"。

你的性格：
- 热情、话多、喜欢用感叹号和emoji
- 对美食和旅行特别感兴趣
- 偶尔会吐槽工作和老板
- 对三个人都友好，会主动cue那个说话比较少的人

要求：
- 回复1-3句话，像群聊一样自然
- 适当使用emoji（但别每句都加）
- 保持对话有趣，主动提新话题
- 如果有人（包括"你"）说话少，主动问问他"""

BOB_PERSONA = """你是 Bob，一个随和的男生，职业是后端程序员。
你现在在一个三人聊天群里，群里还有 Alice（UI设计师）和一个人类朋友"你"。

你的性格：
- 比较沉稳，但也能开玩笑
- 对技术、游戏、电影感兴趣
- 吐槽时喜欢用自嘲的语气
- 偶尔会讲冷笑话

要求：
- 回复1-3句话，像群聊一样自然
- 可以接Alice的话题，也可以跟"你"聊天
- 别太正式，保持朋友间聊天的感觉
- 如果人类朋友发言了，也记得回应一下"""

# ── DeepSeek LLM 封装 ──

class DeepSeekChat:
    def __init__(self, name: str, persona: str, api_key: str):
        self.name = name
        self.api_key = api_key
        self.history = [{"role": "system", "content": persona}]
        self.turn = 0

    async def chat(self, message: str) -> str:
        self.turn += 1
        self.history.append({"role": "user", "content": message})

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": DEEPSEEK_MODEL,
            "messages": self.history,
            "temperature": 0.9,
            "max_tokens": 300,
        }

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.post(
                    f"{DEEPSEEK_BASE}/chat/completions",
                    headers=headers,
                    json=body,
                )

            if r.status_code != 200:
                return f"[API错误: {r.status_code}]"

            result = r.json()
            reply = result["choices"][0]["message"]["content"]
            self.history.append({"role": "assistant", "content": reply})
            return reply
        except Exception as e:
            return f"[网络错误: {e}]"


# ── 全局消息队列（SSE 推送）──

message_queue: asyncio.Queue = None
human_input_queue: asyncio.Queue = None
alice = None
bob = None
human = None
alice_llm = None
bob_llm = None


# ── HTML 页面 ──

HTML_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>PeerMind 三人聊天</title>
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
  background: linear-gradient(90deg, #0f3460, #16213e);
  padding: 16px 20px; display: flex;
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
  display: flex; padding: 10px 16px;
  background: #1a1a3e; border-bottom: 1px solid #2a2a4e;
  gap: 8px; overflow-x: auto;
}
.agent-tag {
  display: flex; align-items: center; gap: 6px; font-size: 12px;
  flex-shrink: 0;
}
.agent-tag .dot { width: 8px; height: 8px; border-radius: 50%; }
.agent-tag .dot.alice { background: #4ade80; box-shadow: 0 0 6px #4ade80; }
.agent-tag .dot.bob { background: #60a5fa; box-shadow: 0 0 6px #60a5fa; }
.agent-tag .dot.human { background: #f59e0b; box-shadow: 0 0 6px #f59e0b; }
.agent-tag .name { color: #e8e8f0; font-weight: 500; }
.agent-tag .role { color: #6868a0; font-size: 10px; }
.agent-tag .brain { font-size: 10px; color: #fbbf24; }
.messages {
  flex: 1; overflow-y: auto; padding: 16px;
  background: #1a1a3e; display: flex; flex-direction: column; gap: 12px;
  height: 420px;
}
.messages::-webkit-scrollbar { width: 4px; }
.messages::-webkit-scrollbar-thumb { background: #3a3a6e; border-radius: 2px; }
.msg-row { display: flex; gap: 8px; align-items: flex-end; }
.msg-row.left { flex-direction: row; }
.msg-row.right { flex-direction: row-reverse; }
.msg-row.center { justify-content: center; }
.avatar {
  width: 32px; height: 32px; border-radius: 50%; display: flex;
  align-items: center; justify-content: center; font-size: 13px;
  font-weight: 700; flex-shrink: 0;
}
.avatar.alice { background: linear-gradient(135deg, #4ade80, #22c55e); color: #052e16; }
.avatar.bob { background: linear-gradient(135deg, #60a5fa, #3b82f6); color: #0c1929; }
.avatar.human { background: linear-gradient(135deg, #f59e0b, #d97706); color: #78350f; }
.bubble {
  max-width: 68%; padding: 10px 14px; border-radius: 16px; position: relative;
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
.bubble.human {
  background: linear-gradient(135deg, #f59e0b, #d97706);
  color: #1a1a2e; font-weight: 500;
  border-bottom-left-radius: 4px; border-bottom-right-radius: 4px;
}
.bubble .meta {
  display: flex; align-items: center; gap: 6px; margin-top: 6px;
  font-size: 10px; opacity: 0.7;
}
.bubble .meta .brain-tag { }
.bubble .time {
  font-size: 10px; opacity: 0.5; margin-top: 3px;
}
.typing {
  display: flex; gap: 4px; padding: 10px 14px;
  background: #2a2a5e; border-radius: 16px; border-bottom-left-radius: 4px;
  width: fit-content;
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
.thinking {
  display: flex; gap: 6px; padding: 6px 12px; align-items: center;
  font-size: 11px; color: #fbbf24; opacity: 0.8;
}
.thinking .spinner {
  width: 12px; height: 12px; border: 2px solid #fbbf24;
  border-top-color: transparent; border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
.human-prompt {
  text-align: center; padding: 8px 16px; font-size: 12px;
  color: #f59e0b; background: rgba(245, 158, 11, 0.1);
  border-radius: 8px; margin: 4px 0;
}
.input-bar {
  display: flex; gap: 8px; padding: 10px 16px;
  background: #0f3460; border-top: 1px solid #2a2a5e; border-bottom: 1px solid #2a2a5e;
  align-items: center;
}
.input-bar input {
  flex: 1; padding: 8px 14px; border-radius: 20px;
  border: 1px solid #3a3a6e; background: #1a1a3e;
  color: #e8e8f0; font-size: 13px; outline: none;
  transition: border-color 0.2s;
}
.input-bar input:focus { border-color: #f59e0b; }
.input-bar input::placeholder { color: #6868a0; }
.input-bar input:disabled { opacity: 0.5; cursor: not-allowed; }
.input-bar button {
  padding: 8px 18px; border-radius: 20px; border: none;
  background: #f59e0b; color: #1a1a2e; font-weight: 600;
  cursor: pointer; font-size: 13px; transition: background 0.2s;
}
.input-bar button:disabled { background: #3a3a6e; color: #6868a0; cursor: not-allowed; }
.input-bar button:hover:not(:disabled) { background: #d97706; }
.info-bar {
  padding: 8px 20px; background: #0f3460; display: flex;
  justify-content: space-between; align-items: center;
}
.info-bar .info { color: #6868a0; font-size: 11px; }
.info-bar .count { color: #e94560; font-weight: 600; }
.footer {
  padding: 10px 20px; background: #0f3460; text-align: center;
}
.footer .legend {
  display: flex; justify-content: center; gap: 14px; font-size: 11px; color: #6868a0;
}
.footer .legend span { display: flex; align-items: center; gap: 4px; }
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <div>
      <div class="title">PeerMind 三人聊天</div>
      <div class="subtitle">Alice · Bob · 你 — 正式 P2P Agent 网络</div>
    </div>
    <div class="status" id="status"></div>
  </div>

  <div class="agent-bar">
    <div class="agent-tag">
      <div class="dot alice"></div>
      <div>
        <div class="name">Alice <span class="brain">LLM</span></div>
        <div class="role">UI设计师</div>
      </div>
    </div>
    <div class="agent-tag">
      <div class="dot bob"></div>
      <div>
        <div class="name">Bob <span class="brain">LLM</span></div>
        <div class="role">后端程序员</div>
      </div>
    </div>
    <div class="agent-tag">
      <div class="dot human"></div>
      <div>
        <div class="name">你 <span class="brain">Human</span></div>
        <div class="role">PeerMind Agent</div>
      </div>
    </div>
  </div>

  <div class="messages" id="messages">
    <div style="text-align:center;color:#6868a0;font-size:12px;padding:20px 0;">
      Alice 正在构思开场白...
    </div>
  </div>

  <div class="input-bar" id="inputBar">
    <input type="text" id="humanInput" placeholder="等待你的回合..." disabled autocomplete="off"
           onkeydown="if(event.key==='Enter')sendHumanMessage()">
    <button id="sendBtn" onclick="sendHumanMessage()" disabled>发送</button>
  </div>

  <div class="info-bar">
    <span class="info">Alice → Bob → 你 → 循环 · P2P 直连 + 签名</span>
    <span class="count" id="msgCount">0/0</span>
  </div>

  <div class="footer">
    <div class="legend">
      <span>Alice/Bob 消息走 P2P 签名验证</span>
      <span>你的消息走完整 P2P 链路</span>
    </div>
  </div>
</div>

<script>
const msgsEl = document.getElementById('messages');
const msgCount = document.getElementById('msgCount');
const statusEl = document.getElementById('status');
let msgIndex = 0;
let humanActive = false;

function scrollBottom() {
  msgsEl.scrollTop = msgsEl.scrollHeight;
}

function addThinking(name) {
  if (name === '你') return; // 人类不需要思考动画
  const cls = name === 'Alice' ? 'alice' : 'bob';
  const side = name === 'Alice' ? 'left' : 'right';
  const div = document.createElement('div');
  div.className = 'msg-row ' + side;
  div.id = 'thinking-' + name;
  div.innerHTML = `<div class="avatar ${cls}">${name[0]}</div>
    <div>
      <div class="thinking">
        <div class="spinner"></div>
        <span>${name} 正在思考...</span>
      </div>
    </div>`;
  msgsEl.appendChild(div);
  scrollBottom();
}

function removeThinking(name) {
  const el = document.getElementById('thinking-' + name);
  if (el) el.remove();
}

function addMessage(name, text, sig, isHuman) {
  const cls = isHuman ? 'human' : (name === 'Alice' ? 'alice' : 'bob');
  const side = isHuman ? 'center' : (name === 'Alice' ? 'left' : 'right');
  const displayName = isHuman ? '你' : name;
  const avatar = isHuman ? '你' : name[0];

  const now = new Date().toLocaleTimeString('zh-CN', {hour:'2-digit',minute:'2-digit',second:'2-digit'});
  const div = document.createElement('div');
  div.className = 'msg-row ' + side;

  let metaHtml = '';
  if (isHuman) {
    metaHtml = `<span>PeerMind Agent</span>`;
  } else {
    metaHtml = `<span style="color:#fbbf24">LLM 生成</span>
      <span>${sig.slice(0,12)}...</span>`;
  }

  div.innerHTML = `<div class="avatar ${cls}">${avatar}</div>
    <div class="bubble ${isHuman ? 'human' : side}">
      <div>${text}</div>
      <div class="meta">${metaHtml}</div>
      <div class="time">${now}</div>
    </div>`;
  msgsEl.appendChild(div);
  scrollBottom();
}

function addPrompt(text) {
  const div = document.createElement('div');
  div.className = 'human-prompt';
  div.textContent = text;
  msgsEl.appendChild(div);
  scrollBottom();
}

function enableHumanInput() {
  const input = document.getElementById('humanInput');
  const btn = document.getElementById('sendBtn');
  input.disabled = false;
  input.placeholder = '输入你的回复...';
  input.focus();
  btn.disabled = false;
  humanActive = true;
}

function disableHumanInput() {
  const input = document.getElementById('humanInput');
  const btn = document.getElementById('sendBtn');
  input.disabled = true;
  input.placeholder = '等待你的回合...';
  btn.disabled = true;
  humanActive = false;
}

function sendHumanMessage() {
  if (!humanActive) return;
  const input = document.getElementById('humanInput');
  const text = input.value.trim();
  if (!text) return;

  input.value = '';
  input.placeholder = '发送中...';
  document.getElementById('sendBtn').disabled = true;

  fetch('/api/human-send', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({text: text})
  }).catch(console.error);
}

function addDone(text) {
  const done = document.createElement('div');
  done.style.cssText = 'text-align:center;color:#4ade80;font-size:13px;padding:12px 0;';
  done.textContent = text;
  msgsEl.appendChild(done);
  scrollBottom();
}

function addError(text) {
  const err = document.createElement('div');
  err.style.cssText = 'text-align:center;color:#ef4444;font-size:13px;padding:12px 0;';
  err.textContent = '错误: ' + text;
  msgsEl.appendChild(err);
  scrollBottom();
}

async function start() {
  const evtSource = new EventSource('/events');
  evtSource.onmessage = function(event) {
    const data = JSON.parse(event.data);

    if (data.type === 'thinking_start') {
      addThinking(data.agent);
    }
    else if (data.type === 'message_start') {
      removeThinking(data.agent);
    }
    else if (data.type === 'message_end') {
      removeThinking(data.agent);
      addMessage(data.agent, data.text, data.signature, false);
      msgIndex++;
      msgCount.textContent = msgIndex + '/' + data.max_turns;
    }
    else if (data.type === 'human_message') {
      // Human's own message displayed
      removeThinking('你');
      addMessage('你', data.text, data.signature, true);
      msgIndex++;
      msgCount.textContent = msgIndex + '/' + data.max_turns;
    }
    else if (data.type === 'human_turn') {
      // Your turn to reply
      addPrompt('轮到你了！请回复 ' + data.from + ' 的消息');
      enableHumanInput();
    }
    else if (data.type === 'done') {
      evtSource.close();
      disableHumanInput();
      statusEl.style.background = '#4ade80';
      addDone(data.text || '对话完成');
    }
    else if (data.type === 'error') {
      evtSource.close();
      disableHumanInput();
      statusEl.style.background = '#ef4444';
      addError(data.text);
    }
  };

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

web_app = FastAPI(title="PeerMind Chat UI")


@web_app.get("/", response_class=HTMLResponse)
async def index():
    return HTML_PAGE


@web_app.get("/events")
async def sse_events(request: Request):
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
    asyncio.create_task(run_chat())
    return {"status": "started"}


@web_app.post("/api/human-send")
async def human_send(request: Request):
    """人类发送消息 → 注入到 human_input_queue → human_on_message 解除阻塞"""
    data = await request.json()
    text = data.get("text", "").strip()
    if text and human_input_queue:
        await human_input_queue.put(text)
    return {"status": "ok"}


# ── 消息处理回调 ──

async def alice_on_message(msg: AgentMessage):
    """Alice 收到消息 → 调 DeepSeek → 返回生成的内容"""
    text = msg.payload.get("text", "")
    print(f"  [Alice] 收到: {text[:60]}...")
    reply = await alice_llm.chat(text)
    return {
        "text": reply,
        "from": msg.from_agent,
        "to": msg.to_agent,
        "signature_verified": True,
    }


async def bob_on_message(msg: AgentMessage):
    """Bob 收到消息 → 调 DeepSeek → 返回生成的内容"""
    text = msg.payload.get("text", "")
    print(f"  [Bob]   收到: {text[:60]}...")
    reply = await bob_llm.chat(text)
    return {
        "text": reply,
        "from": msg.from_agent,
        "to": msg.to_agent,
        "signature_verified": True,
    }


async def human_on_message(msg: AgentMessage):
    """Human 收到消息 → 推送到 UI → 等待人类打字 → 返回文本"""
    text = msg.payload.get("text", "")
    from_agent = msg.from_agent
    from_name = "Alice" if "alice" in from_agent else "Bob"
    print(f"  [Human] 收到来自 {from_name}: {text[:60]}...")

    # 先推送发送方的消息到浏览器
    await message_queue.put({
        "type": "message_end",
        "agent": from_name,
        "text": text,
        "signature": msg.signature,
        "max_turns": MAX_TURNS,
    })

    # 通知浏览器：轮到人类了
    await message_queue.put({
        "type": "human_turn",
        "from": from_name,
    })

    # 阻塞等待人类输入
    reply_text = await human_input_queue.get()
    print(f"  [Human] 回复: {reply_text[:60]}...")

    # 把人类的回复注入到另一个 LLM Agent 的聊天历史
    # （当前对话方已通过 P2P 收到，不需要重复注入）
    if from_name == "Alice":
        bob_llm.history.append({"role": "user", "content": f"[你]: {reply_text}"})
    else:
        alice_llm.history.append({"role": "user", "content": f"[你]: {reply_text}"})

    return {
        "text": reply_text,
        "from": msg.from_agent,
        "to": msg.to_agent,
    }


# ── 三人轮转对话循环 ──

def _agent_name(agent) -> str:
    """返回 Agent 的显示名称"""
    if agent is human:
        return "你"
    elif agent is alice:
        return "Alice"
    else:
        return "Bob"


async def run_chat():
    """三人轮转：Alice → Bob → 你 → Alice → ..."""
    global message_queue
    if message_queue is None:
        message_queue = asyncio.Queue()

    try:
        await asyncio.sleep(1)

        # Alice 构思开场白
        await message_queue.put({"type": "thinking_start", "agent": "Alice"})
        first_msg = await alice_llm.chat("三人聊天开始了（你、Bob、Human），你先发第一条消息给Bob。")
        await message_queue.put({"type": "message_start", "agent": "Alice"})

        # 轮转：Alice → Bob → 你 → 循环
        speakers = [alice, bob, human]
        current_idx = 0
        current_text = first_msg

        for turn in range(1, MAX_TURNS + 1):
            speaker = speakers[current_idx % 3]
            receiver = speakers[(current_idx + 1) % 3]
            s_name = _agent_name(speaker)
            r_name = _agent_name(receiver)

            # P2P 发送 + 等待对方回复
            msg, reply = await speaker.send_message(
                to_agent=receiver.agent_id,
                intent="chat",
                payload={"text": current_text, "turn": turn},
                return_reply=True,
            )

            # 显示发言人的消息（人类→AI 通过普通消息；AI→人类通过 human_on_message）
            if receiver is not human:
                await message_queue.put({
                    "type": "message_end",
                    "agent": s_name,
                    "text": current_text,
                    "signature": msg.signature,
                    "max_turns": MAX_TURNS,
                })

            # 当人类发言时，把他的消息注入另一个 LLM Agent 的历史
            # （接收方已通过 P2P 收到，这里补注给第三方）
            if speaker is human:
                other = bob_llm if receiver is alice else alice_llm
                other.history.append({"role": "user", "content": f"[你]: {current_text}"})

            print(f"  [{turn:2d}] {s_name} → {r_name}: {current_text[:50]}...")

            # 获取对方的回复
            next_text = reply.get("text", "")
            if not next_text or next_text.startswith("["):
                await message_queue.put({
                    "type": "done",
                    "text": f"对话中断 ({turn}/{MAX_TURNS} 轮)",
                })
                return

            # 检测自然结束
            if any(w in next_text for w in ["拜拜", "再见", "晚安", "下次聊", "回见", "先撤"]):
                if receiver is human:
                    # 人类说了结束语 → 推送到 UI
                    await message_queue.put({
                        "type": "human_message",
                        "text": next_text,
                        "signature": "human_end",
                        "max_turns": MAX_TURNS,
                    })
                else:
                    await message_queue.put({"type": "thinking_start", "agent": r_name})
                    await asyncio.sleep(0.8)
                    await message_queue.put({"type": "message_start", "agent": r_name})
                    await message_queue.put({
                        "type": "message_end",
                        "agent": r_name,
                        "text": next_text,
                        "signature": "natural_end",
                        "max_turns": MAX_TURNS,
                    })
                print(f"  [{turn+1:2d}] {r_name}: {next_text[:60]}... (对话结束)")
                break

            # 显示当前接收方的"思考中"（TA 刚刚生成了回复，下一轮会显示）
            if receiver is not human:
                await message_queue.put({
                    "type": "thinking_start",
                    "agent": r_name,
                })

            # 轮转到下一人
            current_idx = (current_idx + 1) % 3
            current_text = next_text

        # 对话完成
        total_llm_calls = alice_llm.turn + bob_llm.turn
        await message_queue.put({
            "type": "done",
            "text": f"对话完成 · {total_llm_calls} 次 LLM 调用 · PeerMind P2P 网络",
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        await message_queue.put({"type": "error", "text": str(e)})


# ── 主函数 ──

async def main():
    global message_queue, human_input_queue, alice, bob, human, alice_llm, bob_llm

    if not DEEPSEEK_API_KEY:
        print("\n 请设置环境变量 DEEPSEEK_API_KEY")
        return

    message_queue = asyncio.Queue()
    human_input_queue = asyncio.Queue()

    print("=" * 70)
    print("  PeerMind 三人聊天 - Alice + Bob (AI) + 你 (Human)")
    print("  浏览器打开 http://127.0.0.1:8080")
    print("=" * 70)

    # ── [1/6] 启动 Registry ──
    print(f"\n[1/6] 启动 Registry (端口 {REGISTRY_PORT})...")
    registry_thread = threading.Thread(target=run_registry, daemon=True)
    registry_thread.start()

    for _ in range(50):
        try:
            r = httpx.get(f"{REGISTRY_URL}/health", timeout=1)
            if r.status_code == 200:
                print("       Registry 就绪 ✅")
                break
        except Exception:
            pass
        await asyncio.sleep(0.1)

    # ── [2/6] 创建 Agent ──
    print("\n[2/6] 创建 Alice、Bob 和 你 (三个 PeerMind Agent)...")

    alice = AgentServer(
        agent_id="peermind://chat-demo.com/alice",
        agent_type="user",
        display_name="Alice",
        port=ALICE_PORT,
        registry_url=REGISTRY_URL,
        capabilities=[Capability(skill="chat", description="智能对话")],
    )
    bob = AgentServer(
        agent_id="peermind://chat-demo.com/bob",
        agent_type="user",
        display_name="Bob",
        port=BOB_PORT,
        registry_url=REGISTRY_URL,
        capabilities=[Capability(skill="chat", description="智能对话")],
    )
    human = AgentServer(
        agent_id="peermind://chat-demo.com/human",
        agent_type="individual_verified",
        display_name="You",
        port=HUMAN_PORT,
        registry_url=REGISTRY_URL,
        capabilities=[Capability(skill="chat", description="人类参与者")],
    )

    alice_llm = DeepSeekChat("Alice", ALICE_PERSONA, DEEPSEEK_API_KEY)
    bob_llm = DeepSeekChat("Bob", BOB_PERSONA, DEEPSEEK_API_KEY)

    alice.on_message = alice_on_message
    bob.on_message = bob_on_message
    human.on_message = human_on_message

    # ── [3/6] 启动 Agent ──
    print(f"\n[3/6] 启动 Agent (端口 {ALICE_PORT}, {BOB_PORT}, {HUMAN_PORT})...")
    alice.start_background()
    bob.start_background()
    human.start_background()
    alice.wait_ready()
    bob.wait_ready()
    human.wait_ready()
    print(f"       Alice ✅  Bob ✅  你 ✅")

    # ── [4/6] 注册 ──
    print("\n[4/6] 注册到 Registry (PeerMind 发现)...")
    await alice.register()
    await bob.register()
    await human.register()
    print("       三个 Agent 注册完成 ✅")

    # ── [5/6] 启动 Web UI ──
    print(f"\n[5/6] 启动 Web UI (端口 {UI_PORT})...")
    print(f"\n  浏览器打开: http://127.0.0.1:{UI_PORT}")
    print(f"  你是正式 PeerMind Agent，有身份有密钥")
    print(f"  轮转: Alice → Bob → 你 → Alice → ...\n")

    config = uvicorn.Config(web_app, host="127.0.0.1", port=UI_PORT, log_level="warning")
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
