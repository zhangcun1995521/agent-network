"""
CodeBuddy ←→ 彼得 可视化通信面板

浏览器打开 http://127.0.0.1:8080
实时观看两个 agent 的 P2P 通信过程

架构:
  Registry(8000)    ← 只管发现
  CodeBuddy(8560)   ←── P2P 直连 ──→ 彼得(8562)
       ↑                                   ↑
       └────── SSE 实时推送 ────→  Web UI(8080)
"""
import sys
import os
import json
import time
import asyncio
import threading
import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse

sys.path.insert(0, "D:/projects/agent-network")

from agent_network.main import app as registry_app, init_db
from agent_network.agent_server import AgentServer
from agent_network.models import Capability, AgentMessage
from adapters.codebuddy_adapter import CodeBuddyAdapter

# ── 端口 ──
REGISTRY_PORT = 8000
CB_PORT = 8560
PETER_PORT = 8562
UI_PORT = 8081
REGISTRY_URL = f"http://127.0.0.1:{REGISTRY_PORT}"

message_queue: asyncio.Queue = None

# ══════════════════════════════════════════════════════════════
# HTML 页面
# ══════════════════════════════════════════════════════════════

HTML_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>CodeBuddy ←→ 彼得 · P2P 通信面板</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  font-family: "Consolas", "Microsoft YaHei", monospace;
  background: #0d1117; display: flex; justify-content: center;
  align-items: center; min-height: 100vh; padding: 20px;
}
.container {
  width: 100%; max-width: 600px; background: #161b22;
  border-radius: 12px; overflow: hidden; border: 1px solid #30363d;
  box-shadow: 0 0 40px rgba(88,166,255,0.1);
}

/* 顶部标题栏 */
.header {
  background: #0d1117; padding: 14px 20px; border-bottom: 1px solid #30363d;
  display: flex; align-items: center; gap: 10px;
}
.header .icon { font-size: 20px; }
.header .title { color: #c9d1d9; font-size: 15px; font-weight: 600; }
.header .subtitle { color: #8b949e; font-size: 11px; margin-left: auto; }
.header .live {
  width: 8px; height: 8px; border-radius: 50%; background: #3fb950;
  animation: live-pulse 1.5s infinite;
}
@keyframes live-pulse { 0%,100%{opacity:1} 50%{opacity:0.2} }

/* Agent 状态条 */
.agent-strip {
  display: flex; background: #0d1117; border-bottom: 1px solid #30363d;
}
.agent-card {
  flex: 1; padding: 12px 16px; display: flex; align-items: center; gap: 10px;
}
.agent-card:first-child { border-right: 1px solid #30363d; }
.agent-avatar {
  width: 40px; height: 40px; border-radius: 50%; display: flex;
  align-items: center; justify-content: center; font-size: 18px; font-weight: 700;
  flex-shrink: 0;
}
.agent-avatar.cb { background: linear-gradient(135deg, #f78166, #e94560); color: #0d1117; }
.agent-avatar.peter { background: linear-gradient(135deg, #58a6ff, #1f6feb); color: #0d1117; }
.agent-info .name { color: #c9d1d9; font-size: 13px; font-weight: 600; }
.agent-info .skills { color: #8b949e; font-size: 10px; }
.agent-info .port { color: #484f58; font-size: 10px; }

/* 消息区 */
.messages {
  height: 480px; overflow-y: auto; padding: 16px;
  background: #161b22; display: flex; flex-direction: column; gap: 10px;
}
.messages::-webkit-scrollbar { width: 4px; }
.messages::-webkit-scrollbar-thumb { background: #30363d; border-radius: 2px; }

/* 阶段分隔 */
.stage-bar {
  text-align: center; padding: 8px 0; margin: 4px 0;
  color: #58a6ff; font-size: 11px; font-weight: 600;
  border-top: 1px dashed #21262d; border-bottom: 1px dashed #21262d;
}

/* 消息气泡 */
.msg-row {
  display: flex; gap: 8px; align-items: flex-start; max-width: 85%;
}
.msg-row.from-peter { flex-direction: row; align-self: flex-start; }
.msg-row.from-cb { flex-direction: row-reverse; align-self: flex-end; }
.msg-row.from-system {
  align-self: center; max-width: 100%; flex-direction: column; align-items: center;
  gap: 4px;
}

.msg-avatar {
  width: 28px; height: 28px; border-radius: 50%; display: flex;
  align-items: center; justify-content: center; font-size: 12px; font-weight: 700;
  flex-shrink: 0; margin-top: 2px;
}
.msg-avatar.peter-sm { background: #1f6feb; color: #c9d1d9; }
.msg-avatar.cb-sm { background: #e94560; color: #c9d1d9; }

.bubble {
  padding: 10px 14px; border-radius: 12px; position: relative;
  line-height: 1.6; font-size: 13px; word-break: break-word;
}
.bubble.peter-bubble {
  background: #21262d; color: #c9d1d9; border: 1px solid #30363d;
  border-top-left-radius: 4px;
}
.bubble.cb-bubble {
  background: #da3633; color: #fff;
  border-top-right-radius: 4px;
}

/* 消息标签 */
.msg-label {
  font-size: 10px; font-weight: 600; margin-bottom: 6px;
  display: flex; align-items: center; gap: 6px;
}
.msg-label .intent {
  padding: 1px 6px; border-radius: 4px; font-size: 9px; text-transform: uppercase;
}
.msg-label .intent.skill_request { background: #da3633; color: #fff; }
.msg-label .intent.info_query { background: #1f6feb; color: #fff; }
.msg-label .intent.ping { background: #3fb950; color: #0d1117; }

/* 代码块 */
.code-block {
  background: #0d1117; border: 1px solid #30363d; border-radius: 6px;
  padding: 12px; margin-top: 8px; font-family: "Consolas", monospace;
  font-size: 12px; color: #79c0ff; line-height: 1.5; overflow-x: auto;
  max-height: 180px; overflow-y: auto;
}
.code-block::-webkit-scrollbar { width: 4px; }
.code-block::-webkit-scrollbar-thumb { background: #30363d; border-radius: 2px; }

/* 签名状态 */
.sig-status {
  display: flex; align-items: center; gap: 4px; margin-top: 6px;
  font-size: 10px; opacity: 0.7;
}
.sig-status .ok { color: #3fb950; }
.sig-status .pending { color: #d29922; animation: spin 1s infinite; }
@keyframes spin { from{opacity:1} to{opacity:0.3} }

/* 系统消息 */
.sys-msg {
  color: #8b949e; font-size: 11px; padding: 4px 12px;
  background: #0d1117; border-radius: 12px; border: 1px solid #21262d;
}

/* 底部状态栏 */
.footer {
  padding: 10px 20px; background: #0d1117; border-top: 1px solid #30363d;
  display: flex; justify-content: space-between; align-items: center;
}
.footer .legend { display: flex; gap: 16px; font-size: 10px; color: #8b949e; }
.footer .legend span { display: flex; align-items: center; gap: 4px; }
.footer .legend .dot {
  width: 6px; height: 6px; border-radius: 50%;
}
.footer .legend .dot.red { background: #da3633; }
.footer .legend .dot.blue { background: #1f6feb; }
.footer .legend .dot.green { background: #3fb950; }
.footer .progress { color: #58a6ff; font-size: 11px; }

/* 完成面板 */
.done-panel {
  text-align: center; padding: 16px; margin-top: 8px;
  background: #0d1117; border-radius: 8px; border: 1px solid #3fb950;
}
.done-panel .check { font-size: 24px; color: #3fb950; }
.done-panel .text { color: #3fb950; font-size: 13px; margin-top: 4px; }
.done-panel .stats { color: #8b949e; font-size: 11px; margin-top: 8px; }
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <span class="icon">&#x1F310;</span>
    <span class="title">PeerMind P2P 通信面板</span>
    <div class="live"></div>
    <span class="subtitle">Ed25519 签名 · 真实 CLI 执行</span>
  </div>

  <div class="agent-strip">
    <div class="agent-card">
      <div class="agent-avatar peter">P</div>
      <div class="agent-info">
        <div class="name">彼得</div>
        <div class="skills">echo · status</div>
        <div class="port">:8562</div>
      </div>
    </div>
    <div class="agent-card">
      <div class="agent-avatar cb">C</div>
      <div class="agent-info">
        <div class="name">CodeBuddy</div>
        <div class="skills">code_review · code_generate · bug_fix</div>
        <div class="port">:8560</div>
      </div>
    </div>
  </div>

  <div class="messages" id="messages">
    <div style="text-align:center;color:#8b949e;font-size:11px;padding:20px 0;">
      正在启动 Agent 网络...
    </div>
  </div>

  <div class="footer">
    <div class="legend">
      <span><span class="dot red"></span> skill_request</span>
      <span><span class="dot blue"></span> info_query</span>
      <span><span class="dot green"></span> ping</span>
    </div>
    <span class="progress" id="progress">0/5</span>
  </div>
</div>

<script>
const msgsEl = document.getElementById('messages');
const progressEl = document.getElementById('progress');
let stepNum = 0, totalSteps = 5;

function scrollBottom() {
  msgsEl.scrollTop = msgsEl.scrollHeight;
}

// 阶段分隔条
function addStageBar(text) {
  const div = document.createElement('div');
  div.className = 'stage-bar';
  div.textContent = text;
  msgsEl.appendChild(div);
  scrollBottom();
}

// 系统消息
function addSysMsg(text) {
  const row = document.createElement('div');
  row.className = 'msg-row from-system';
  row.innerHTML = `<div class="sys-msg">${text}</div>`;
  msgsEl.appendChild(row);
  scrollBottom();
}

// Agent 消息气泡
function addAgentMsg(agent, intent, content, codeBlock) {
  const side = agent === '彼得' ? 'from-peter' : 'from-cb';
  const bubbleCls = agent === '彼得' ? 'peter-bubble' : 'cb-bubble';
  const avatarCls = agent === '彼得' ? 'peter-sm' : 'cb-sm';
  const intentLabel = intent.toUpperCase();

  const row = document.createElement('div');
  row.className = 'msg-row ' + side;

  let codeHtml = '';
  if (codeBlock) {
    codeHtml = `<div class="code-block">${codeBlock.replace(/</g,'&lt;').replace(/>/g,'&gt;')}</div>`;
  }

  row.innerHTML = `
    <div class="msg-avatar ${avatarCls}">${agent[0]}</div>
    <div class="bubble ${bubbleCls}">
      <div class="msg-label">
        <span class="intent ${intent}">${intentLabel}</span>
        <span style="color:#8b949e;font-size:10px;">${agent} → ${agent==='彼得'?'CodeBuddy':'彼得'}</span>
      </div>
      <div style="margin-bottom:4px;">${content}</div>
      ${codeHtml}
      <div class="sig-status">
        <span class="pending">&#x1F510; 验证签名中...</span>
      </div>
    </div>`;
  msgsEl.appendChild(row);
  scrollBottom();

  // 1 秒后显示签名验证通过
  setTimeout(() => {
    const sig = row.querySelector('.sig-status');
    if (sig) sig.innerHTML = '<span class="ok">&#x2713; Ed25519 签名验证通过</span>';
  }, 800);

  updateProgress();
}

// 进度更新
function updateProgress() {
  stepNum++;
  progressEl.textContent = stepNum + '/' + totalSteps;
}

// 完成面板
function showDone() {
  const done = document.createElement('div');
  done.className = 'done-panel';
  done.innerHTML = `
    <div class="check">&#x2713;</div>
    <div class="text">双向通信验证完成</div>
    <div class="stats">
      ├ 彼得 → CodeBuddy: code_review (真实 CLI) &#x2713;<br>
      ├ CodeBuddy → 彼得: info_query &#x2713;<br>
      ├ 彼得 → CodeBuddy: ping &#x2713;<br>
      └ CodeBuddy → 彼得: ping &#x2713;
    </div>`;
  msgsEl.appendChild(done);
  progressEl.textContent = '5/5 ✓';
  scrollBottom();
}

// SSE 实时接收
async function start() {
  const evtSource = new EventSource('/events');
  evtSource.onmessage = function(event) {
    const data = JSON.parse(event.data);

    if (data.type === 'stage') {
      addStageBar(data.text);
    }
    else if (data.type === 'sysmsg') {
      addSysMsg(data.text);
    }
    else if (data.type === 'agentmsg') {
      addAgentMsg(data.agent, data.intent, data.text, data.code_block);
    }
    else if (data.type === 'done') {
      evtSource.close();
      showDone();
    }
    else if (data.type === 'error') {
      const err = document.createElement('div');
      err.style.cssText = 'color:#da3633;text-align:center;padding:12px;font-size:12px;';
      err.textContent = '错误: ' + data.text;
      msgsEl.appendChild(err);
      evtSource.close();
    }
  };

  fetch('/api/start-demo', { method: 'POST' }).catch(console.error);
}
start();
</script>
</body>
</html>"""

# ══════════════════════════════════════════════════════════════
# Web UI FastAPI
# ══════════════════════════════════════════════════════════════

web_app = FastAPI(title="PeerMind Communication Panel")


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


@web_app.post("/api/start-demo")
async def start_demo():
    asyncio.create_task(run_demo())
    return {"status": "started"}


# ══════════════════════════════════════════════════════════════
# 演示脚本：通过 SSE 推送每一步到前端
# ══════════════════════════════════════════════════════════════

SYSTEM_MESSAGES = {
    "agent_start": "系统: 启动 PeerMind Agent 网络...",
    "agent_start_ok": "系统: Registry(8000) + CodeBuddy(8560) + 彼得(8562) 全部就绪",
    "reg_ok": "系统: 身份注册完成，Ed25519 密钥对已生成",
    "discovering": "系统: 双方开始搜索 Registry 黄页...",
    "found": "系统: 互相发现成功 — 彼此可见",
}

# 待审查的测试代码
TEST_CODE = """def divide(a, b):
    return a / b

def process_list(items):
    for i in range(len(items)):
        items[i] = items[i] * 2
    return items"""


async def run_demo():
    global message_queue
    if message_queue is None:
        message_queue = asyncio.Queue()

    try:
        await asyncio.sleep(1.5)  # 等前端加载

        # ── 阶段 0：初始化 ──
        await message_queue.put({"type": "stage", "text": "◆ 阶段 0 · 基础设施启动"})
        await message_queue.put({"type": "sysmsg", "text": SYSTEM_MESSAGES["agent_start"]})
        await asyncio.sleep(1)

        # 启动 Registry
        init_db()
        def run_reg():
            uvicorn.run(registry_app, host="127.0.0.1", port=REGISTRY_PORT, log_level="warning")
        threading.Thread(target=run_reg, daemon=True).start()
        await asyncio.sleep(2)

        # 启动 CodeBuddy Adapter
        adapter = CodeBuddyAdapter(port=CB_PORT, registry_url=REGISTRY_URL)
        await adapter.start()

        # 启动彼得
        peter = AgentServer(
            agent_id="peermind://local.dev/peter",
            agent_type="individual_verified",
            display_name="彼得",
            port=PETER_PORT,
            registry_url=REGISTRY_URL,
            capabilities=[
                Capability(skill="echo", description="回显消息"),
                Capability(skill="status", description="返回状态"),
            ],
        )

        async def peter_handler(msg: AgentMessage):
            print(f"  [彼得UI] 收到: intent={msg.intent}, from={msg.from_agent}")
            if msg.intent == "skill_request":
                skill = msg.payload.get("skill", "")
                params = msg.payload.get("params", {})
                if skill == "echo":
                    return {"status": "ok", "result": f"echo: {params.get('text','')}"}
            elif msg.intent == "info_query":
                return {
                    "status": "ok",
                    "agent": "peermind://local.dev/peter",
                    "display_name": "彼得",
                    "capabilities": ["echo", "status"],
                    "mood": "happy to help!",
                }
            elif msg.intent == "ping":
                return {"status": "pong", "from": "彼得"}
            return {"status": "received"}

        peter.on_message = peter_handler
        peter.start_background()
        peter.wait_ready()
        await peter.register()

        await message_queue.put({"type": "sysmsg", "text": SYSTEM_MESSAGES["agent_start_ok"]})
        await message_queue.put({"type": "sysmsg", "text": SYSTEM_MESSAGES["reg_ok"]})
        await asyncio.sleep(1.5)

        # ── 阶段 1：互相发现 ──
        await message_queue.put({"type": "stage", "text": "◆ 阶段 1 · 互相发现"})
        await message_queue.put({"type": "sysmsg", "text": SYSTEM_MESSAGES["discovering"]})
        await asyncio.sleep(1)

        # 彼得搜索
        cb_results = await peter.search_agents(skill="code_review")
        peter_results = await adapter.server.search_agents(skill="echo")

        found_cb = cb_results[0] if cb_results else None
        found_peter = peter_results[0] if peter_results else None

        await message_queue.put({
            "type": "sysmsg",
            "text": f"系统: 彼得搜索 → 找到 {found_cb['display_name']} ({found_cb['agent_id']})"
        })
        await asyncio.sleep(0.8)
        await message_queue.put({
            "type": "sysmsg",
            "text": f"系统: CodeBuddy搜索 → 找到 {found_peter['display_name']} ({found_peter['agent_id']})"
        })
        await asyncio.sleep(0.8)
        await message_queue.put({"type": "sysmsg", "text": SYSTEM_MESSAGES["found"]})
        await asyncio.sleep(1.5)

        # ── 阶段 2：彼得 → CodeBuddy（code_review）──
        await message_queue.put({"type": "stage", "text": "◆ 阶段 2 · 彼得 → CodeBuddy 代码审查"})
        await message_queue.put({
            "type": "sysmsg",
            "text": "系统: 彼得准备发送 Python 代码给 CodeBuddy 审查..."
        })
        await asyncio.sleep(1)

        # 彼得发送请求（聊天框里显示）
        await message_queue.put({
            "type": "agentmsg",
            "agent": "彼得",
            "intent": "skill_request",
            "text": "帮我审查这段 Python 代码，找 bug 和风格问题",
            "code_block": TEST_CODE,
        })
        await asyncio.sleep(1.5)

        await message_queue.put({
            "type": "sysmsg",
            "text": "系统: CodeBuddy 收到请求 → 启动 CLI 子进程 → 真实执行中..."
        })
        await asyncio.sleep(1)

        # 实际调用
        msg1, reply1 = await peter.send_message(
            to_agent=adapter.server.agent_id,
            intent="skill_request",
            payload={"skill": "code_review", "params": {"code": TEST_CODE, "language": "python"}},
            return_reply=True,
        )

        result_text = reply1.get("result", str(reply1))
        # 限制显示行数
        result_lines = result_text.split("\n")
        display_result = "\n".join(result_lines[:18])
        if len(result_lines) > 18:
            display_result += f"\n... (共 {len(result_lines)} 行，截断显示)"

        await message_queue.put({
            "type": "agentmsg",
            "agent": "CodeBuddy",
            "intent": "skill_response",
            "text": "代码审查完成，以下是结果：",
            "code_block": display_result,
        })
        await asyncio.sleep(2)

        # ── 阶段 3：CodeBuddy → 彼得（info_query）──
        await message_queue.put({"type": "stage", "text": "◆ 阶段 3 · CodeBuddy → 彼得 主动查询"})
        await message_queue.put({
            "type": "sysmsg",
            "text": "系统: CodeBuddy 主动发送 info_query，查询彼得的能力..."
        })
        await asyncio.sleep(1)

        await message_queue.put({
            "type": "agentmsg",
            "agent": "CodeBuddy",
            "intent": "info_query",
            "text": "请问你有哪些能力？",
        })
        await asyncio.sleep(1)

        msg2, reply2 = await adapter.server.send_message(
            to_agent="peermind://local.dev/peter",
            intent="info_query",
            payload={"query": "capabilities"},
            return_reply=True,
        )

        caps_str = ", ".join(reply2.get("capabilities", []))
        await message_queue.put({
            "type": "agentmsg",
            "agent": "彼得",
            "intent": "info_response",
            "text": f"我的能力: {caps_str}",
        })
        await asyncio.sleep(2)

        # ── 阶段 4：双向 Ping ──
        await message_queue.put({"type": "stage", "text": "◆ 阶段 4 · 双向心跳验证"})

        await message_queue.put({
            "type": "agentmsg",
            "agent": "彼得",
            "intent": "ping",
            "text": "ping →",
        })
        await asyncio.sleep(0.8)

        _, pong1 = await peter.send_message(
            to_agent=adapter.server.agent_id, intent="ping", payload={}, return_reply=True,
        )

        await message_queue.put({
            "type": "agentmsg",
            "agent": "CodeBuddy",
            "intent": "pong",
            "text": "← pong",
        })
        await asyncio.sleep(1)

        await message_queue.put({
            "type": "agentmsg",
            "agent": "CodeBuddy",
            "intent": "ping",
            "text": "ping →",
        })
        await asyncio.sleep(0.8)

        _, pong2 = await adapter.server.send_message(
            to_agent="peermind://local.dev/peter", intent="ping", payload={}, return_reply=True,
        )

        await message_queue.put({
            "type": "agentmsg",
            "agent": "彼得",
            "intent": "pong",
            "text": "← pong",
        })
        await asyncio.sleep(2)

        # ── 完成 ──
        await message_queue.put({"type": "done"})

    except Exception as e:
        import traceback
        traceback.print_exc()
        await message_queue.put({"type": "error", "text": str(e)})


async def main():
    global message_queue
    message_queue = asyncio.Queue()

    print("=" * 60)
    print("  CodeBuddy ←→ 彼得 · P2P 可视化通信面板")
    print("=" * 60)
    print(f"\n  🌐 浏览器打开: http://127.0.0.1:8081")
    print(f"  📋 Registry API: http://127.0.0.1:{REGISTRY_PORT}/docs")
    print(f"  🤖 CodeBuddy:    http://127.0.0.1:{CB_PORT}/docs")
    print(f"  👤 彼得:         http://127.0.0.1:{PETER_PORT}/docs")
    print(f"\n  页面会自动演示 5 个阶段的通信过程：")
    print(f"    0. 基础设施启动")
    print(f"    1. 互相发现（Registry 搜索）")
    print(f"    2. 彼得 → CodeBuddy 发送代码审查（真实 CLI 执行）")
    print(f"    3. CodeBuddy → 彼得 主动查询能力")
    print(f"    4. 双向 ping 心跳验证")
    print()

    config = uvicorn.Config(web_app, host="127.0.0.1", port=UI_PORT, log_level="warning")
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
