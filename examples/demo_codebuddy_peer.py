"""
Demo：CodeBuddy Adapter ←→ 彼得 Agent 双向通信

架构：
  Registry(8000)  ← 只管发现，不中转消息
      ↑ 注册               ↑ 注册
  CodeBuddy(8560)  ←──→  彼得(8562)
      │                       │
  技能: code_review        技能: echo, status
        code_generate            (on_message 回调直接回复)
        bug_fix
        file_read

演示流程：
  1. 全部启动 + 注册
  2. 彼得搜索 → 找到 CodeBuddy → 发送 code_review → 收结果
  3. CodeBuddy 搜索 → 找到彼得 → 发送 info_query → 收结果

成功标准：
  - 双方都能在 Registry 搜到对方
  - 彼得发任务给 CodeBuddy，收到 CLI 返回的真实结果
  - CodeBuddy 发查询给彼得，收到正确的能力列表
"""
import sys
import asyncio
import uvicorn
import threading
import time
import os

sys.path.insert(0, "D:/projects/agent-network")

# ── 分段演示辅助 ──
def wait(txt, seconds=3):
    """打印提示后暂停，让用户能看到过程"""
    print(f"\n  ⏸  {txt}")
    print(f"     等待 {seconds} 秒（请阅读上面的输出）...")
    sys.stdout.flush()
    time.sleep(seconds)

def stage_header(n, total, title):
    """打印阶段标题"""
    print(f"\n{'='*65}")
    print(f"  [{n}/{total}] {title}")
    print(f"{'='*65}")
    sys.stdout.flush()

from agent_network.main import app as registry_app, init_db
from agent_network.agent_server import AgentServer
from agent_network.models import Capability, AgentMessage
from adapters.codebuddy_adapter import CodeBuddyAdapter

# ── 端口配置 ──
REGISTRY_PORT = 8000
CB_PORT = 8560          # CodeBuddy Adapter
PETER_PORT = 8562       # 彼得 Agent
REGISTRY_URL = f"http://127.0.0.1:{REGISTRY_PORT}"


def start_registry():
    """后台启动 Registry"""
    init_db()
    def run():
        uvicorn.run(registry_app, host="127.0.0.1", port=REGISTRY_PORT, log_level="warning")
    t = threading.Thread(target=run, daemon=True)
    t.start()
    time.sleep(2)


async def main():
    print("=" * 65)
    print("  PeerMind 网络：CodeBuddy ←→ 彼得 双向通信演示")
    print("=" * 65)

    # ══════════════════════════════════════════════════════════
    # 阶段 1：启动基础设施
    # ══════════════════════════════════════════════════════════
    stage_header(1, 5, "启动基础设施")
    start_registry()
    print("  Registry     → http://127.0.0.1:8000  ✓")

    # 启动 CodeBuddy Adapter
    adapter = CodeBuddyAdapter(port=CB_PORT, registry_url=REGISTRY_URL)
    await adapter.start()
    print(f"  CodeBuddy    → port={CB_PORT}, id={adapter.server.agent_id}  ✓")

    # 创建彼得 Agent（手动配置，不用 Adapter 基类）
    peter = AgentServer(
        agent_id="peermind://local.dev/peter",
        agent_type="individual_verified",
        display_name="彼得",
        port=PETER_PORT,
        registry_url=REGISTRY_URL,
        capabilities=[
            Capability(skill="echo", description="回显消息，验证通信链路"),
            Capability(skill="status", description="返回 agent 自身状态"),
        ],
    )

    # 彼得的消息处理回调
    async def peter_on_message(msg: AgentMessage):
        """彼得收到消息时的处理逻辑"""
        print(f"\n  [彼得] 收到消息: intent={msg.intent}, 来自={msg.from_agent}")
        print(f"  [彼得] payload={msg.payload}")

        if msg.intent == "skill_request":
            skill = msg.payload.get("skill", "")
            if skill == "echo":
                text = msg.payload.get("text", "")
                return {"status": "ok", "result": f"彼得回显: {text}"}
            elif skill == "status":
                return {
                    "status": "ok",
                    "result": "彼得状态: 在线, 能力=[echo, status], 心情=😊"
                }
            else:
                return {"status": "error", "error": f"彼得不会技能: {skill}"}

        elif msg.intent == "info_query":
            return {
                "status": "ok",
                "agent": "peermind://local.dev/peter",
                "display_name": "彼得",
                "capabilities": ["echo", "status"],
                "mood": "ready to help!",
            }

        elif msg.intent == "ping":
            return {"status": "pong", "from": "彼得"}

        return {"status": "received"}

    peter.on_message = peter_on_message

    # 启动彼得
    peter.start_background()
    peter.wait_ready()
    await peter.register()
    print(f"  彼得          → port={PETER_PORT}, id={peter.agent_id}  ✓")
    print(f"  能力: echo, status")
    sys.stdout.flush()

    wait("准备进入阶段 2：互相发现")

    # ══════════════════════════════════════════════════════════
    # 阶段 2：互相发现
    # ══════════════════════════════════════════════════════════
    stage_header(2, 5, "互相发现：搜索 Registry")

    # 彼得搜索 CodeBuddy
    print("\n  彼得 搜索 'code_review' 技能...")
    cb_results = await peter.search_agents(skill="code_review")
    for a in cb_results:
        caps = [c["skill"] for c in a.get("capabilities", [])]
        print(f"    找到: {a['display_name']} ({a['agent_id']})")
        print(f"    能力: {caps}")
        print(f"    地址: {a['endpoint']}")

    print()

    # CodeBuddy 搜索 彼得
    print("  CodeBuddy 搜索 'echo' 技能...")
    peter_results = await adapter.server.search_agents(skill="echo")
    for a in peter_results:
        caps = [c["skill"] for c in a.get("capabilities", [])]
        print(f"    找到: {a['display_name']} ({a['agent_id']})")
        print(f"    能力: {caps}")
        print(f"    地址: {a['endpoint']}")
    sys.stdout.flush()

    wait("准备进入阶段 3：彼得发送任务给 CodeBuddy（重头戏！）")

    # ══════════════════════════════════════════════════════════
    # 阶段 3：彼得 → CodeBuddy（发送代码审查任务）
    # ══════════════════════════════════════════════════════════
    stage_header(3, 5, "彼得 → CodeBuddy：发送代码审查任务")

    test_code = """def divide(a, b):
    return a / b

def process_list(items):
    for i in range(len(items)):
        items[i] = items[i] * 2
    return items"""
    print(f"\n  彼得 说: 帮我审查这段 Python 代码")
    print(f"  {'─' * 45}")
    for line in test_code.strip().split("\n"):
        print(f"  │ {line}")
    print(f"  {'─' * 45}")

    print(f"\n  [网络] 彼得 --P2P直连--> CodeBuddy Adapter")
    print(f"  [网络] 路径: peermind://local.dev/peter → peermind://local.dev/codebuddy-adapter")
    print(f"  [网络] 协议: POST {peter.agent_id}/agent/v1 (带 Ed25519 签名)")
    print(f"  [网络] intent=skill_request, skill=code_review")
    print(f"\n  [CodeBuddy] 正在启动 CLI 子进程...")
    print(f"  [CodeBuddy] 命令: codebuddy -p -y (stdin=审查 prompt)")
    print(f"  [CodeBuddy] 等待中（最多 120 秒）...\n")

    msg1, reply1 = await peter.send_message(
        to_agent=adapter.server.agent_id,
        intent="skill_request",
        payload={
            "skill": "code_review",
            "params": {"code": test_code, "language": "python"},
        },
        return_reply=True,
    )

    print(f"  [网络] CodeBuddy Adapter --回复--> 彼得")
    print(f"  [网络] 签名验证: ✓ (接收方已验证发送方身份)")
    print(f"\n  CodeBuddy 的回复：")
    print(f"  {'─' * 45}")
    result = reply1.get("result", str(reply1))
    for line in result.split("\n")[:25]:
        print(f"  │ {line}")
    print(f"  {'─' * 45}")
    sys.stdout.flush()

    wait("准备进入阶段 4：CodeBuddy 主动查询彼得")

    # ══════════════════════════════════════════════════════════
    # 阶段 4：CodeBuddy → 彼得（主动查询对方能力）
    # ══════════════════════════════════════════════════════════
    stage_header(4, 5, "CodeBuddy → 彼得：主动查询对方信息")

    print(f'\n  CodeBuddy 说: 我来查查这个"彼得"agent有哪些能力')
    print(f"\n  [网络] CodeBuddy --P2P直连--> 彼得")
    print(f"  [网络] 路径: peermind://local.dev/codebuddy-adapter → peermind://local.dev/peter")
    print(f"  [网络] intent=info_query")

    msg2, reply2 = await adapter.server.send_message(
        to_agent="peermind://local.dev/peter",
        intent="info_query",
        payload={"query": "capabilities"},
        return_reply=True,
    )

    print(f"\n  [网络] 彼得 --回复--> CodeBuddy")
    print(f"\n  彼得的回复：")
    print(f"  {'─' * 45}")
    for k, v in reply2.items():
        print(f"  │ {k}: {v}")
    print(f"  {'─' * 45}")
    sys.stdout.flush()

    wait("准备进入阶段 5：最终验证")

    # ══════════════════════════════════════════════════════════
    # 阶段 5：Ping 测试（轻量双向验证）
    # ══════════════════════════════════════════════════════════
    stage_header(5, 5, "Ping 心跳验证（双向）")

    print(f"\n  彼得 → CodeBuddy: ping")
    _, pong1 = await peter.send_message(
        to_agent=adapter.server.agent_id,
        intent="ping",
        payload={},
        return_reply=True,
    )
    print(f"  CodeBuddy 回复: {pong1}")

    print(f"\n  CodeBuddy → 彼得: ping")
    _, pong2 = await adapter.server.send_message(
        to_agent="peermind://local.dev/peter",
        intent="ping",
        payload={},
        return_reply=True,
    )
    print(f"  彼得 回复: {pong2}")

    # ══════════════════════════════════════════════════════════
    # 总结
    # ══════════════════════════════════════════════════════════
    print("\n" + "=" * 65)
    print("  演示完成！")
    print("=" * 65)
    print(f"""
  通信矩阵验证：
  ┌─────────────────┬──────────────┬──────────┐
  │ 方向              │ 意图          │ 结果     │
  ├─────────────────┼──────────────┼──────────┤
  │ 彼得 → CodeBuddy │ skill_request│ CLI执行  │
  │ CodeBuddy → 彼得  │ info_query   │ 能力列表 │
  │ 彼得 → CodeBuddy │ ping         │ pong    │
  │ CodeBuddy → 彼得  │ ping         │ pong    │
  └─────────────────┴──────────────┴──────────┘

  关键要点：
  - CodeBuddy Adapter 是完整的 AgentServer，既能接也能发
  - P2P 直连，Registry 只做发现，不中转消息
  - 每条消息带 Ed25519 签名，接收方到 Registry 验签
  - code_review 调的是真实的 CodeBuddy CLI 子进程
  - 彼得是轻量 agent（on_message 回调直接回复），无需外部工具

  服务地址：
    Registry   : http://127.0.0.1:{REGISTRY_PORT}/docs
    CodeBuddy  : http://127.0.0.1:{CB_PORT}/docs
    彼得        : http://127.0.0.1:{PETER_PORT}/docs
""")


if __name__ == "__main__":
    asyncio.run(main())
