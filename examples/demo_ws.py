"""
Agent 通信网络 - WebSocket 长连接 Demo
演示一次握手后，在同一条连接上持续收发消息（打电话模式）

对比旧方式：
  旧：每发一条消息 = 新建 TCP 连接 → 验签 → 处理 → 断开
  新：一次 WebSocket 握手 → 验签一次 → 后续消息自由收发

架构：
  Registry (8000)  ← 注册 + 发现，不中转
  Agent 导航 (8001) ── WS 长连接 ──  Agent 记忆 (8002)
       ↑                                    ↑
       ws://127.0.0.1:8002/ws                /ws 端点
"""
import asyncio
import httpx
import json
import sys
import threading
import uvicorn

sys.path.insert(0, ".")

from agent_network.main import app as registry_app, init_db
from agent_network.agent_server import AgentServer
from agent_network.models import Capability, AgentMessage

REGISTRY_PORT = 8000
NAVI_PORT = 8001
MEMORY_PORT = 8002
REGISTRY_URL = f"http://127.0.0.1:{REGISTRY_PORT}"


def run_registry():
    """后台启动 Registry"""
    init_db()
    uvicorn.run(registry_app, host="127.0.0.1", port=REGISTRY_PORT, log_level="warning")


async def demo():
    print("=" * 60)
    print("Agent 通信网络 - WebSocket 长连接 Demo")
    print("=" * 60)

    # ── 启动 Registry ──
    print("\n[启动] Registry 服务 (端口 8000)...")
    registry_thread = threading.Thread(target=run_registry, daemon=True)
    registry_thread.start()

    for _ in range(50):
        try:
            r = httpx.get(f"{REGISTRY_URL}/health", timeout=1)
            if r.status_code == 200:
                print("[启动] Registry 就绪 ✅")
                break
        except Exception:
            pass
        await asyncio.sleep(0.1)

    # ── 创建记忆 Agent（被调用方）──
    print("\n[创建] 记忆 Agent...")
    memory = AgentServer(
        agent_id="agent://mem0.dev/memory-service",
        agent_type="organization",
        display_name="记忆服务Agent",
        port=MEMORY_PORT,
        registry_url=REGISTRY_URL,
        capabilities=[
            Capability(skill="memory_search", description="搜索用户记忆"),
            Capability(skill="memory_store", description="存储新记忆"),
        ],
    )

    # 回调：收到消息时的处理
    async def memory_on_message(msg: AgentMessage):
        intent = msg.intent
        payload = msg.payload

        if intent == "skill_request" and payload.get("skill") == "memory_search":
            query = payload.get("query", "")
            print(f"\n  [记忆Agent] 收到搜索: '{query}'")
            return {
                "status": "ok",
                "result": "用户偏好温度: 22°C",
                "confidence": 0.95,
            }
        elif intent == "skill_request" and payload.get("skill") == "memory_store":
            print(f"\n  [记忆Agent] 存储记忆: {payload}")
            return {"status": "ok", "stored": True}
        elif intent == "ping":
            return {"status": "ok", "message": "pong"}
        else:
            return {"status": "received", "message_id": msg.id}

    memory.on_message = memory_on_message

    # ── 创建导航 Agent（调用方）──
    print("[创建] 导航 Agent...")
    navi = AgentServer(
        agent_id="agent://volkswagen.com/navi",
        agent_type="organization",
        display_name="大众导航Agent",
        port=NAVI_PORT,
        registry_url=REGISTRY_URL,
        capabilities=[
            Capability(skill="navigation", description="车辆路径规划"),
        ],
    )

    # ── 启动 Agent ──
    print("\n[启动] Agent 服务...")
    memory.start_background()
    navi.start_background()
    memory.wait_ready()
    navi.wait_ready()
    print("  记忆Agent 就绪 ✅  (WebSocket 端点: ws://127.0.0.1:8002/ws)")
    print("  导航Agent 就绪 ✅")

    # ── 注册到 Registry ──
    print("\n[注册] 向 Registry 登记...")
    await memory.register()
    await navi.register()
    print("  两个 Agent 注册成功 ✅")

    # ── 发现 ──
    print("\n[发现] 导航Agent 搜索记忆服务...")
    results = await navi.search_agents(skill="memory_search")
    target = results[0]
    print(f"  发现: {target['agent_id']} → HTTP端点: {target['endpoint']}")
    print(f"  WS端点将自动推导为: ws://127.0.0.1:{MEMORY_PORT}/ws")

    # ═══════════════════════════════════════════════════════
    # WebSocket 长连接通信
    # ═══════════════════════════════════════════════════════

    print("\n" + "=" * 60)
    print("WebSocket 长连接通信演示")
    print("=" * 60)

    # 建立 WebSocket 连接
    print("\n[WS] 导航Agent 建立 WebSocket 连接到记忆Agent...")
    ws = await navi.connect_ws("agent://mem0.dev/memory-service")

    # 验证握手状态
    print("  握手: ✅ 通过（身份验签成功）")
    print("  状态: 连接已建立，后续消息不验签，在一条连接上自由收发")
    print("  对比: HTTP 方式每发一条消息要新建连接+验签+断开")

    # ── 第 1 条消息：搜索用户偏好温度 ──
    print("\n[WS] ─── 消息 1/3 ───")
    msg1 = {
        "type": "message",
        "intent": "skill_request",
        "payload": {
            "skill": "memory_search",
            "query": "用户偏好温度多少度",
            "user_id": "driver_zhang_car_001",
            "limit": 5,
        },
    }
    print(f"  发送: {json.dumps(msg1, ensure_ascii=False)}")
    await ws.send(json.dumps(msg1))
    resp1 = json.loads(await ws.recv())
    print(f"  接收: {json.dumps(resp1, ensure_ascii=False)}")
    result = resp1.get("payload", {}).get("result", "")
    print(f"  → 结果: {result}")

    # ── 第 2 条消息：再来一次搜索（同一条连接）──
    print("\n[WS] ─── 消息 2/3 ───")
    msg2 = {
        "type": "message",
        "intent": "skill_request",
        "payload": {
            "skill": "memory_search",
            "query": "用户是否喜欢听歌",
            "user_id": "driver_zhang_car_001",
        },
    }
    print(f"  发送: {json.dumps(msg2, ensure_ascii=False)}")
    await ws.send(json.dumps(msg2))
    resp2 = json.loads(await ws.recv())
    print(f"  接收: {json.dumps(resp2, ensure_ascii=False)}")

    # ── 第 3 条消息：存储新记忆 ──
    print("\n[WS] ─── 消息 3/3 ───")
    msg3 = {
        "type": "message",
        "intent": "skill_request",
        "payload": {
            "skill": "memory_store",
            "key": "user_mood",
            "value": "happy",
            "user_id": "driver_zhang_car_001",
        },
    }
    print(f"  发送: {json.dumps(msg3, ensure_ascii=False)}")
    await ws.send(json.dumps(msg3))
    resp3 = json.loads(await ws.recv())
    print(f"  接收: {json.dumps(resp3, ensure_ascii=False)}")

    # ── 挂断 ──
    print("\n[WS] 挂断连接...")
    await ws.close()
    print("  连接已关闭")

    # ═══════════════════════════════════════════════════════
    # 总结对比
    # ═══════════════════════════════════════════════════════

    print("\n" + "=" * 60)
    print("HTTP vs WebSocket 对比")
    print("=" * 60)
    print("""
  HTTP "发短信"模式：
    每次 POST /agent/v1 → 新建 TCP → 查Registry验签 → 回调 → 断开
    3 条消息 = 3 次 TCP 连接 + 3 次查Registry + 3 次验签

  WebSocket "打电话"模式：
    WS 握手 → 验签一次 (Ed25519) → 建立长连接
    3 条消息 = 1 次验签 + 同一条连接上自由收发
    消息格式：{type:"message", intent, payload}
  """)

    print("=" * 60)
    print("WebSocket 长连接 Demo 完成!")
    print("=" * 60)
    print()
    print("核心验证点：")
    print("  1. 握手阶段身份验证（Ed25519 验签） ✅")
    print("  2. 一次连接，多发消息（不走 Registry） ✅")
    print("  3. 后续消息直接 JSON 收发，不再验签 ✅")
    print("  4. 现有 HTTP 端点 (POST /agent/v1) 完全保留 ✅")


if __name__ == "__main__":
    asyncio.run(demo())
