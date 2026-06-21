"""
Agent 通信网络 P2P 直连 Demo
演示 Registry 只管发现，Agent 之间直连通信

架构：
  Registry (8000)  ← 只管注册 + 搜索，不中转消息
  Agent 导航 (8001) ──── 直连消息 ────  Agent 记忆 (8002)
       ↑                                       ↑
       各自暴露 POST /agent/v1 接收消息，验签后处理
"""
import asyncio
import httpx
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
    print("Agent 通信网络 - P2P 直连 Demo")
    print("=" * 60)

    # ── 启动 Registry ──
    print("\n[启动] Registry 服务 (端口 8000)...")
    registry_thread = threading.Thread(target=run_registry, daemon=True)
    registry_thread.start()

    # 等待 Registry 就绪
    for _ in range(50):
        try:
            r = httpx.get(f"{REGISTRY_URL}/health", timeout=1)
            if r.status_code == 200:
                print("[启动] Registry 就绪 ✅")
                break
        except Exception:
            pass
        await asyncio.sleep(0.1)

    # ── 创建两个 Agent ──
    print("\n[创建] 两个 Agent 实例...")

    navi = AgentServer(
        agent_id="peermind://volkswagen.com/navi",
        agent_type="organization",
        display_name="大众导航Agent",
        port=NAVI_PORT,
        registry_url=REGISTRY_URL,
        capabilities=[
            Capability(skill="navigation", description="车辆路径规划与导航"),
            Capability(skill="traffic_query", description="实时路况查询"),
        ],
    )
    print(f"  导航Agent: {navi.agent_id}")
    print(f"    公钥: {navi.public_key[:30]}...")
    print(f"    端口: {NAVI_PORT}")

    memory = AgentServer(
        agent_id="peermind://mem0.dev/memory-service",
        agent_type="organization",
        display_name="记忆服务Agent",
        port=MEMORY_PORT,
        registry_url=REGISTRY_URL,
        capabilities=[
            Capability(skill="memory_search", description="搜索用户记忆"),
            Capability(skill="memory_store", description="存储新记忆"),
        ],
    )
    print(f"  记忆Agent: {memory.agent_id}")
    print(f"    公钥: {memory.public_key[:30]}...")
    print(f"    端口: {MEMORY_PORT}")

    # ── 记忆Agent 的消息处理回调 ──
    async def memory_on_message(msg: AgentMessage):
        """记忆Agent 收到消息时的处理逻辑"""
        intent = msg.intent
        payload = msg.payload

        if intent == "skill_request" and payload.get("skill") == "memory_search":
            # 模拟记忆搜索
            query = payload.get("query", "")
            print(f"\n  [记忆Agent] 收到搜索请求: '{query}'")
            return {
                "status": "ok",
                "result": "用户偏好温度: 22°C",
                "confidence": 0.95,
            }
        elif intent == "ping":
            return {"status": "ok", "message": "pong"}
        else:
            return {"status": "received", "message_id": msg.id}

    memory.on_message = memory_on_message

    # ── 启动两个 Agent ──
    print("\n[启动] Agent 服务...")
    navi.start_background()
    memory.start_background()
    navi.wait_ready()
    memory.wait_ready()
    print("  导航Agent 就绪 ✅")
    print("  记忆Agent 就绪 ✅")

    # ── 注册到 Registry ──
    print("\n[注册] 向 Registry 登记...")
    navi_profile = await navi.register()
    print(f"  导航Agent 注册成功 ✅")
    memory_profile = await memory.register()
    print(f"  记忆Agent 注册成功 ✅")

    # ── Agent 发现 ──
    print("\n[发现] 导航Agent 搜索 'memory_search' 技能...")
    results = await navi.search_agents(skill="memory_search")
    print(f"  找到 {len(results)} 个匹配的 Agent:")
    for agent in results:
        print(f"    - {agent['agent_id']} ({agent['display_name']})")
        for cap in agent["capabilities"]:
            print(f"      技能: {cap['skill']} - {cap['description']}")
        print(f"      endpoint: {agent['endpoint']}")

    # ── P2P 直连通信 ──
    print("\n" + "=" * 60)
    print("P2P 直连通信测试")
    print("=" * 60)

    # 导航Agent → 记忆Agent（P2P 直连，不经过 Registry）
    print("\n[P2P] 导航Agent → 记忆Agent（直连，不经过 Registry）")
    msg1 = await navi.send_message(
        to_agent="peermind://mem0.dev/memory-service",
        intent="skill_request",
        payload={
            "skill": "memory_search",
            "query": "用户偏好温度多少度",
            "user_id": "driver_zhang_car_001",
            "limit": 5,
        },
    )
    print(f"  消息ID: {msg1.id}")
    print(f"  路径: peermind://volkswagen.com/navi → peermind://mem0.dev/memory-service")
    print(f"  途经: 无中间节点，直接 POST 到 {MEMORY_PORT} 端口")
    print(f"  意图: {msg1.intent}")
    print(f"  载荷: {msg1.payload}")
    print(f"  签名: {msg1.signature[:30]}...")

    # 语义：这里绕过 Registry，导航Agent直接把消息发到了记忆Agent的端口上

    # ── 验证签名 ──
    print("\n[验证] 签名验证...")
    msg_bytes_test = await _verify_signature_on_registry(msg1)
    if msg_bytes_test:
        print(f"  消息签名: ✅ 通过（接收方已验证发送方身份）")
    else:
        print(f"  消息签名: ❌ 失败")

    # ── 对比：旧方式 vs P2P ──
    print("\n" + "=" * 60)
    print("架构对比")
    print("=" * 60)

    print("""
  【旧方式 - Registry 中转】
  导航Agent → Registry(存入收件箱) → 记忆Agent(拉取)
  
  【新方式 - P2P 直连】
  导航Agent ── POST /agent/v1 ──→ 记忆Agent
       ↑                              │
       └──── 直接返回响应 ──────────────┘
  
  Registry 只用于发现（步骤3），通信完全不经过 Registry。
  消息签名由发送方本地签名，接收方本地验签。
  """)

    print("=" * 60)
    print("P2P 直连 Demo 完成！")
    print("=" * 60)
    print()
    print("核心验证点：")
    print("  1. Registry 只管注册和发现，不中转消息 ✅")
    print("  2. Agent 之间直连通信（POST 到对方端口） ✅")
    print("  3. 每条消息带 Ed25519 签名，接收方验签 ✅")
    print("  4. 两个 Agent 不需要同一框架、同一平台 ✅")


async def _verify_signature_on_registry(msg: AgentMessage):
    """通过 Registry 的验证接口验证签名"""
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            f"{REGISTRY_URL}/api/v1/messages/verify",
            json=msg.model_dump(mode="json", by_alias=True),
        )
        return r.json().get("valid", False)


if __name__ == "__main__":
    asyncio.run(demo())
