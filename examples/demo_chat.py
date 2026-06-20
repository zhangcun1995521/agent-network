"""
Agent 通信网络 - 多轮对话 Demo
演示两个 Agent 通过 P2P 直连互相聊天（10 轮对话）

架构：
  Registry (8000)  ← 只管注册 + 发现
  Alice (8001) ──── P2P 直连 ──── Bob (8002)

关键机制：
  send_message(return_reply=True) → (消息, 对方回复)
  利用这个返回值可以看到真实的 Agent-to-Agent 通信
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

REGISTRY_PORT = 9000
ALICE_PORT = 9001
BOB_PORT = 9002
REGISTRY_URL = f"http://127.0.0.1:{REGISTRY_PORT}"

# 对话脚本：每轮指定谁说话、对谁说、说什么
CHAT_SCRIPT = [
    ("Alice", "Bob", "你好 Bob，今晚想吃什么？"),
    ("Bob", "Alice", "我想吃麻辣烫，你呢？"),
    ("Alice", "Bob", "我也想吃辣的！那我们一起点吧，你加购物车了吗？"),
    ("Bob", "Alice", "还没呢，我刚打开外卖 APP，你喜欢啥菜？"),
    ("Alice", "Bob", "我喜欢毛肚、牛肉丸、藕片，再要点宽粉"),
    ("Bob", "Alice", "好嘞，我都加上了。再加一份豆腐皮？"),
    ("Alice", "Bob", "可以！对了，辣度选中辣还是特辣？"),
    ("Bob", "Alice", "中辣吧，上次特辣我俩第二天都不行了"),
    ("Alice", "Bob", "哈哈哈确实。那就中辣，下单吧！"),
    ("Bob", "Alice", "已下单！预计 35 分钟到，准备碗筷"),
]


def run_registry():
    """后台启动 Registry"""
    init_db()
    uvicorn.run(registry_app, host="127.0.0.1", port=REGISTRY_PORT, log_level="warning")


async def demo():
    print("=" * 60)
    print("  Agent 通信网络 - 多轮对话 Demo")
    print("  两个 Agent 通过 P2P 直连互相聊天")
    print("=" * 60)

    # ── 启动 Registry ──
    print(f"\n[启动] Registry 服务 (端口 {REGISTRY_PORT})...")
    registry_thread = threading.Thread(target=run_registry, daemon=True)
    registry_thread.start()

    for _ in range(50):
        try:
            r = httpx.get(f"{REGISTRY_URL}/health", timeout=1)
            if r.status_code == 200:
                print("  Registry 就绪 ✅")
                break
        except Exception:
            pass
        await asyncio.sleep(0.1)

    # ── 创建两个 Agent ──
    print("\n[创建] 两个 Agent 实例...")

    alice = AgentServer(
        agent_id="agent://chat-demo.com/alice",
        agent_type="user",
        display_name="Alice",
        port=ALICE_PORT,
        registry_url=REGISTRY_URL,
        capabilities=[
            Capability(skill="chat", description="日常闲聊"),
            Capability(skill="order_food", description="点外卖"),
        ],
    )

    bob = AgentServer(
        agent_id="agent://chat-demo.com/bob",
        agent_type="user",
        display_name="Bob",
        port=BOB_PORT,
        registry_url=REGISTRY_URL,
        capabilities=[
            Capability(skill="chat", description="日常闲聊"),
            Capability(skill="add_to_cart", description="加购物车"),
        ],
    )

    print(f"  Alice: {alice.agent_id}  → 端口 {ALICE_PORT}")
    print(f"  Bob:   {bob.agent_id}  → 端口 {BOB_PORT}")

    # ── 设置消息处理回调 ──
    # 每个 Agent 的 on_message 回调会在收到消息时被调用
    # 返回值会作为 HTTP 响应发送回发送方

    async def alice_on_message(msg: AgentMessage):
        """Alice 收到消息时：签名已验证通过，直接处理"""
        return {
            "status": "ok",
            "received_by": "Alice",
            "from": msg.from_agent,
            "intent": msg.intent,
            "message_received": msg.payload.get("text", ""),
            "signature_verified": True,
        }

    async def bob_on_message(msg: AgentMessage):
        """Bob 收到消息时：签名已验证通过，直接处理"""
        return {
            "status": "ok",
            "received_by": "Bob",
            "from": msg.from_agent,
            "intent": msg.intent,
            "message_received": msg.payload.get("text", ""),
            "signature_verified": True,
        }

    alice.on_message = alice_on_message
    bob.on_message = bob_on_message

    # ── 启动两个 Agent ──
    print("\n[启动] Agent 服务...")
    alice.start_background()
    bob.start_background()
    alice.wait_ready()
    bob.wait_ready()
    print("  Alice 就绪 ✅  Bob 就绪 ✅")

    # ── 注册到 Registry ──
    print("\n[注册] 向 Registry 登记...")
    await alice.register()
    await bob.register()
    print("  Alice 注册成功 ✅  Bob 注册成功 ✅")

    # ── 10 轮对话 ──
    print("\n" + "=" * 60)
    print("  🗣️  对话开始 (10 轮 P2P 直连)")
    print("  Registry 只负责发现，消息不经过 Registry")
    print("=" * 60)

    for i, (sender_name, receiver_name, text) in enumerate(CHAT_SCRIPT):
        await asyncio.sleep(0.4)  # 模拟打字间隔

        # 确定发送方和接收方
        if sender_name == "Alice":
            sender = alice
            receiver_id = bob.agent_id
            sender_tag = "🟢 Alice"
            receiver_tag = "Bob"
        else:
            sender = bob
            receiver_id = alice.agent_id
            sender_tag = "🔵 Bob"
            receiver_tag = "Alice"

        # P2P 直连发送，并要求返回对方回复
        msg, reply = await sender.send_message(
            to_agent=receiver_id,
            intent="chat",
            payload={"text": text, "turn": i + 1},
            return_reply=True,
        )

        # 打印详细通信记录
        print(f"\n  [{i+1:2d}] {sender_tag} → {receiver_tag}")
        print(f"      发送: \"{text}\"")
        print(f"      回复: {reply}")
        print(f"      路径: {sender.agent_id} ──POST──→ {receiver_id}")
        print(f"      签名: {msg.signature[:40]}... ✓")

    # ── 总结 ──
    print("\n" + "=" * 60)
    print("  🎉 10 轮对话完成！")
    print("=" * 60)
    print()
    print("  你看到的核心机制：")
    print("  1. Alice 和 Bob 各有自己的端口 + 密钥对")
    print("  2. 发消息：构造消息 → 本地签名 → POST 到对方端口")
    print("  3. 收消息：对方端口收到 → 从 Registry 拉发送方公钥 → 验签 → 调 on_message")
    print("  4. 回复：on_message 的返回值直接作为 HTTP 响应发回")
    print("  5. Registry 在整个通信过程中零参与（只做了注册）")
    print()
    print("  这就是 Agent 之间的 P2P 通信基础设施。")
    print("  真实场景中 on_message 回调会接 LLM，但通信层不变。")


if __name__ == "__main__":
    asyncio.run(demo())
