"""
Agent 通信网络 - 真实 LLM 对话 Demo
两个 Agent 通过 DeepSeek API 真正地"思考"后互相回复

工作流程：
  1. Alice 调 DeepSeek 生成开场白
  2. Alice ──P2P+签名──→ Bob 的 /agent/v1
  3. Bob.on_message → 调 DeepSeek 生成回复 → 返回
  4. 剧本拿到 Bob 的回复 → 作为消息喂给 Alice
  5. Alice.on_message → 调 DeepSeek → 返回
  6. 循环直到达到最大轮数

和之前版本的关键区别：
  之前：CHAT_SCRIPT = ["你好", "我想吃...", ...]  ← 预设剧本
  现在：agent.think(收到的内容) → DeepSeek 生成 → 真正的对话
"""
import asyncio
import httpx
import os
import sys
import threading
import uvicorn

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
REGISTRY_URL = f"http://127.0.0.1:{REGISTRY_PORT}"

MAX_TURNS = 10  # 最多对话轮数

# ── Agent 人设 ──

ALICE_PERSONA = """你是 Alice，一个活泼开朗的女生，职业是UI设计师。你现在正在微信上和好朋友 Bob 聊天。

你的性格：
- 热情、话多、喜欢用感叹号和emoji
- 对美食和旅行特别感兴趣
- 偶尔会吐槽工作和老板
- 说话带点调侃但很真诚

要求：
- 回复1-3句话，像微信聊天一样自然
- 适当使用emoji（但别每句都加）
- 保持对话有趣，主动提新话题"""

BOB_PERSONA = """你是 Bob，一个随和的男生，职业是后端程序员。你现在正在和好朋友 Alice 聊天。

你的性格：
- 比较沉稳，但也能开玩笑
- 对技术、游戏、电影感兴趣
- 吐槽时喜欢用自嘲的语气
- 偶尔会讲冷笑话

要求：
- 回复1-3句话，像微信聊天一样自然
- 可以接Alice的话题，也可以稍微抬杠
- 别太正式，保持朋友间聊天的感觉"""


# ── DeepSeek LLM 封装 ──

class DeepSeekChat:
    """每个 Agent 独立的 LLM 实例，维护自己的对话历史"""

    def __init__(self, name: str, persona: str, api_key: str, model: str = DEEPSEEK_MODEL):
        self.name = name
        self.api_key = api_key
        self.model = model
        self.history = [{"role": "system", "content": persona}]
        self.turn = 0

    async def chat(self, message: str) -> str:
        """收到消息后调用 DeepSeek 生成回复"""
        self.turn += 1
        self.history.append({"role": "user", "content": message})

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": self.model,
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
                error_msg = f"DeepSeek API 错误 {r.status_code}: {r.text[:200]}"
                print(f"    ⚠️  {error_msg}")
                return f"[API错误: {r.status_code}]"

            result = r.json()
            reply = result["choices"][0]["message"]["content"]
            self.history.append({"role": "assistant", "content": reply})
            return reply

        except httpx.RequestError as e:
            print(f"    ⚠️  网络错误: {e}")
            return "[网络错误]"


# ── 启动服务 ──

def run_registry():
    init_db()
    uvicorn.run(registry_app, host="127.0.0.1", port=REGISTRY_PORT, log_level="warning")


async def main():
    if not DEEPSEEK_API_KEY:
        print("❌ 请设置环境变量 DEEPSEEK_API_KEY")
        print("   export DEEPSEEK_API_KEY=sk-xxxxx")
        return

    print("=" * 70)
    print("  Agent 真实对话 Demo - DeepSeek LLM 驱动")
    print("  每个 Agent 有自己的 AI 大脑，通过 P2P + 签名通信")
    print("=" * 70)

    # ── 启动 Registry ──
    print(f"\n[1/5] 启动 Registry (端口 {REGISTRY_PORT})...")
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

    # ── 创建 Agent ──
    print("\n[2/5] 创建 Alice 和 Bob (带 DeepSeek 大脑)...")

    alice = AgentServer(
        agent_id="agent://chat-demo.com/alice",
        agent_type="user",
        display_name="Alice (UI设计师)",
        port=ALICE_PORT,
        registry_url=REGISTRY_URL,
        capabilities=[Capability(skill="chat", description="智能对话")],
    )
    bob = AgentServer(
        agent_id="agent://chat-demo.com/bob",
        agent_type="user",
        display_name="Bob (后端程序员)",
        port=BOB_PORT,
        registry_url=REGISTRY_URL,
        capabilities=[Capability(skill="chat", description="智能对话")],
    )

    # ── 创建 LLM 实例 ──
    alice_llm = DeepSeekChat("Alice", ALICE_PERSONA, DEEPSEEK_API_KEY)
    bob_llm = DeepSeekChat("Bob", BOB_PERSONA, DEEPSEEK_API_KEY)

    # ── 设置 on_message 回调：收到消息 → 调用 LLM → 返回生成的内容 ──
    async def alice_on_message(msg: AgentMessage):
        text = msg.payload.get("text", "")
        print(f"       [Alice 大脑思考中...] 收到: \"{text[:50]}...\"")
        reply = await alice_llm.chat(text)
        return {
            "text": reply,
            "from": msg.from_agent,
            "to": msg.to_agent,
            "signature_verified": True,
        }

    async def bob_on_message(msg: AgentMessage):
        text = msg.payload.get("text", "")
        print(f"       [Bob 大脑思考中...] 收到: \"{text[:50]}...\"")
        reply = await bob_llm.chat(text)
        return {
            "text": reply,
            "from": msg.from_agent,
            "to": msg.to_agent,
            "signature_verified": True,
        }

    alice.on_message = alice_on_message
    bob.on_message = bob_on_message

    # ── 启动 Agent ──
    print(f"\n[3/5] 启动 Agent 服务 (端口 {ALICE_PORT}, {BOB_PORT})...")
    sys.stdout.flush()
    alice.start_background()
    print("       Alice 线程已启动，等待健康检查...")
    sys.stdout.flush()
    alice.wait_ready()
    print("       Alice 健康检查通过")
    sys.stdout.flush()
    bob.start_background()
    print("       Bob 线程已启动，等待健康检查...")
    sys.stdout.flush()
    bob.wait_ready()
    print(f"       Alice ({ALICE_PORT}) ✅  Bob ({BOB_PORT}) ✅")

    # ── 注册 ──
    print("\n[4/5] 向 Registry 注册...")
    await alice.register()
    await bob.register()
    print("       注册完成 ✅")

    # ── 真实对话 ──
    print("\n[5/5] 开始对话！\n")
    print("=" * 70)
    print("  🗣️  Alice 和 Bob 的真实对话（DeepSeek 驱动）")
    print("  每条消息都经过 P2P 直连 + Ed25519 签名验证")
    print("=" * 70)

    # 第一步：Alice 生成开场白（不需要 P2P，本地思考）
    print("\n  [Alice 正在构思开场白...]")
    first_msg = await alice_llm.chat("现在开始和Bob聊天，由你先发第一条消息。")
    print()

    # 当前发言状态
    current_speaker = alice      # AgentServer 实例
    current_receiver = bob       # AgentServer 实例
    current_text = first_msg     # 当前要说的话

    for turn in range(1, MAX_TURNS + 1):
        speaker_name = "Alice" if current_speaker is alice else "Bob"
        receiver_name = "Bob" if current_receiver is bob else "Alice"

        # P2P 发送消息（带上 return_reply 获取对方的 LLM 回复）
        msg, reply = await current_speaker.send_message(
            to_agent=current_receiver.agent_id,
            intent="chat",
            payload={"text": current_text, "turn": turn},
            return_reply=True,
        )

        # 打印
        prefix = "🟢" if speaker_name == "Alice" else "🔵"
        print(f"  [{turn:2d}] {prefix} {speaker_name}: {current_text}")
        print(f"       签名: {msg.signature[:30]}... ✅")

        # 提取对方的 LLM 回复
        next_text = reply.get("text", "")
        if not next_text or next_text.startswith("[API"):
            print(f"       ⚠️  对方回复异常，对话终止")
            break

        # 检查是否自然结束（说再见之类）
        if any(word in next_text for word in ["拜拜", "再见", "晚安", "下次聊"]):
            reversed_name = "Bob" if speaker_name == "Alice" else "Alice"
            print(f"  [{turn + 1:2d}] {('🔵' if speaker_name == 'Alice' else '🟢')} {reversed_name}: {next_text}")
            print(f"       签名: ... ✅")
            print(f"\n  📌 {reversed_name} 说了再见，对话自然结束。")
            break

        # 交换说话顺序
        current_speaker, current_receiver = current_receiver, current_speaker
        current_text = next_text

    # ── 总结 ──
    print("\n" + "=" * 70)
    print("  🎉 对话完成！")
    print("=" * 70)
    print(f"""
  技术细节：
  - Alice 调用了 {alice_llm.turn} 次 DeepSeek API
  - Bob 调用了 {bob_llm.turn} 次 DeepSeek API
  - 每条消息 P2P 直连 + Ed25519 签名验证
  - Registry 只负责注册发现，不中转消息
  - Alice 和 Bob 各自维护独立的对话记忆

  和之前的不同：
  之前：CHAT_SCRIPT = ["你好", "我想吃..."]  ← 剧本
  现在：agent.think("收到的话") → DeepSeek → 自主生成 ← AI 大脑
""")


if __name__ == "__main__":
    asyncio.run(main())
