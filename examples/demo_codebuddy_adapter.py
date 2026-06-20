"""
Demo：CodeBuddy Adapter 端到端验证

流程概览
  Registry(8000) ←── 注册 ──→ CodeBuddy Adapter(8560)
       ↑                              ↑
       │ Alice 搜索                    │ P2P 直连投递任务
       │      └────────────────────→
                                        │
                                        ├ code_review  → 调 CodeBuddy CLI
                                        ├ code_generate → 调 CodeBuddy CLI
                                        └ 返回结果给 Alice

成功标准
  1. Adapter 成功注册到 Registry
  2. Alice 能在 Registry 搜到 CodeBuddy Adapter
  3. Alice 发送 code_review → Adapter 返回审查结果
  4. Alice 发送 code_generate → Adapter 返回生成的代码
"""
import sys
import asyncio
import uvicorn
import threading

sys.path.insert(0, "D:/projects/agent-network")

from agent_network.main import app as registry_app, init_db  # Registry 入口
from agent_network.agent_server import AgentServer            # P2P 通信
from agent_network.models import Capability                   # 数据模型
from adapters.codebuddy_adapter import CodeBuddyAdapter       # CodeBuddy 适配器

# ── 配置端口 ──
REGISTRY_PORT = 8000
ADAPTER_PORT = 8560
ALICE_PORT = 8561
REGISTRY_URL = f"http://127.0.0.1:{REGISTRY_PORT}"


def start_registry():
    """后台启动 Registry（和现有 demo 保持一致的方式）"""
    init_db()
    def run():
        uvicorn.run(registry_app, host="127.0.0.1", port=REGISTRY_PORT, log_level="warning")
    t = threading.Thread(target=run, daemon=True)
    t.start()

    import time
    time.sleep(2)
    print("[Registry] 已启动。\n")


async def main():
    # ── 1. 启动基础设施 ──
    print("=" * 60)
    print("  PeerMind × CodeBuddy 连接验证")
    print("=" * 60)
    start_registry()

    # ── 2. 启动 CodeBuddy Adapter ──
    adapter = CodeBuddyAdapter(
        port=ADAPTER_PORT,
        registry_url=REGISTRY_URL,
    )
    await adapter.start()
    print(f"[CodeBuddy Adapter] 已就绪，端口 {ADAPTER_PORT}")
    print(f"  身份: {adapter.server.agent_id}")
    print(f"  能力: {list(adapter.SKILLS.keys())}\n")

    # ── 3. 创建 Alice（验证调用方）──
    alice = AgentServer(
        agent_id="peermind://local.dev/alice",
        agent_type="individual_verified",
        display_name="Alice",
        port=ALICE_PORT,
        registry_url=REGISTRY_URL,
    )
    alice.start_background()
    alice.wait_ready()
    await alice.register()
    print(f"[Alice] 已就绪，端口 {ALICE_PORT}\n")

    # ── 4. Alice 搜索 CodeBuddy ──
    print("─" * 40)
    print("  Alice 搜索 Registry 中...")
    print("─" * 40)
    results = await alice.search_agents(skill="code_review")
    for agent in results:
        caps = [c["skill"] for c in agent.get("capabilities", [])]
        print(f"  找到: {agent['display_name']}")
        print(f"    ID: {agent['agent_id']}")
        print(f"    能力: {caps}")
    print()

    adapter_agent_id = adapter.server.agent_id

    # ── 5. 发送任务 ──

    # 任务 A：code_review
    print("─" * 40)
    print("  任务 A: code_review（代码审查）")
    print("─" * 40)
    test_code = """def divide(a, b):
    return a / b

def process_list(items):
    for i in range(len(items)):
        items[i] = items[i] * 2
    return items"""
    print(f"  Alice → CodeBuddy: 请审查这段 Python 代码")
    print(f"  {test_code[:60]}...")
    print()

    msg, reply = await alice.send_message(
        to_agent=adapter_agent_id,
        intent="skill_request",
        payload={
            "skill": "code_review",
            "params": {"code": test_code, "language": "python"},
        },
        return_reply=True,
    )
    print(f"  CodeBuddy 回复：")
    print(f"  {'─' * 40}")
    result = reply.get("result", reply)
    for line in result.split("\n")[:30]:  # 限制输出行数
        print(f"  {line}")
    print(f"  {'─' * 40}")
    print()

    # 任务 B：code_generate
    print("─" * 40)
    print("  任务 B: code_generate（代码生成）")
    print("─" * 40)
    print(f"  Alice → CodeBuddy: 生成一个快速排序函数（Python 3行注释版）")
    print()

    msg, reply = await alice.send_message(
        to_agent=adapter_agent_id,
        intent="skill_request",
        payload={
            "skill": "code_generate",
            "params": {
                "description": "快速排序函数，Python 3行注释版",
                "language": "python",
            },
        },
        return_reply=True,
    )
    print(f"  CodeBuddy 回复：")
    print(f"  {'─' * 40}")
    result = reply.get("result", reply)
    for line in result.split("\n")[:30]:
        print(f"  {line}")
    print(f"  {'─' * 40}")
    print()

    # ── 6. 完成 ──
    print("=" * 60)
    print("  验证完成！")
    print(f"  Registry  : http://127.0.0.1:{REGISTRY_PORT}/docs")
    print(f"  Adapter   : http://127.0.0.1:{ADAPTER_PORT}/docs")
    print(f"  Alice     : http://127.0.0.1:{ALICE_PORT}/docs")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
