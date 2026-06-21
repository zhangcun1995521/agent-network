"""
Agent 通信网络 Demo
演示两个 Agent 的注册、发现、通信全流程

注意：必须从仓库根目录运行：python -m examples.demo
"""
import httpx
import asyncio

from agent_network.crypto import generate_keypair, build_message_bytes, sign_message, verify_signature

BASE_URL = "http://127.0.0.1:8000/api/v1"


async def demo():
    async with httpx.AsyncClient(timeout=10) as client:
        # ── 步骤 1：生成密钥对 ──
        print("=" * 60)
        print("步骤 1：为两个 Agent 生成 Ed25519 密钥对")
        print("=" * 60)

        # Agent A：大众导航 Agent
        navi_priv, navi_pub = generate_keypair()
        print(f"[导航Agent] 私钥: {navi_priv[:20]}...")
        print(f"[导航Agent] 公钥: {navi_pub[:20]}...")

        # Agent B：记忆服务 Agent
        memory_priv, memory_pub = generate_keypair()
        print(f"[记忆Agent] 私钥: {memory_priv[:20]}...")
        print(f"[记忆Agent] 公钥: {memory_pub[:20]}...")

        # ── 步骤 2：注册两个 Agent ──
        print("\n" + "=" * 60)
        print("步骤 2：注册 Agent 到 Registry")
        print("=" * 60)

        # 注册导航Agent
        r = await client.post(f"{BASE_URL}/agents/register", json={
            "agent_id": "peermind://volkswagen.com/navi",
            "agent_type": "organization",
            "display_name": "大众导航Agent",
            "public_key": navi_pub,
            "endpoint": "https://navi.volkswagen.com/agent/v1",
            "capabilities": [
                {"skill": "navigation", "description": "车辆路径规划与导航"},
                {"skill": "traffic_query", "description": "实时路况查询"},
            ],
        })
        navi_profile = r.json()
        print(f"[导航Agent] 注册成功: {navi_profile['agent_id']}")

        # 注册记忆服务Agent
        r = await client.post(f"{BASE_URL}/agents/register", json={
            "agent_id": "peermind://mem0.dev/memory-service",
            "agent_type": "organization",
            "display_name": "记忆服务Agent",
            "public_key": memory_pub,
            "endpoint": "https://memory.mem0.dev/agent/v1",
            "capabilities": [
                {"skill": "memory_search", "description": "搜索用户记忆"},
                {"skill": "memory_store", "description": "存储新记忆"},
            ],
        })
        memory_profile = r.json()
        print(f"[记忆Agent] 注册成功: {memory_profile['agent_id']}")

        # 注册 Agent 私钥（Demo 用，生产环境应有客户端自行签名）
        await client.post(
            f"{BASE_URL}/agents/{navi_profile['agent_id']}/private-key",
            params={"private_key": navi_priv},
        )
        await client.post(
            f"{BASE_URL}/agents/{memory_profile['agent_id']}/private-key",
            params={"private_key": memory_priv},
        )

        # ── 步骤 3：Agent 发现 ──
        print("\n" + "=" * 60)
        print("步骤 3：导航Agent 搜索记忆服务")
        print("=" * 60)

        # 搜索 "memory" 技能的 Agent
        r = await client.get(f"{BASE_URL}/directory/search", params={
            "skill": "memory_search",
        })
        results = r.json()
        print(f"搜索结果: 找到 {results['total']} 个匹配的 Agent")
        for agent in results["agents"]:
            print(f"  - {agent['agent_id']} ({agent['display_name']})")
            for cap in agent["capabilities"]:
                print(f"    技能: {cap['skill']} - {cap['description']}")

        # ── 步骤 4：消息通信 ──
        print("\n" + "=" * 60)
        print("步骤 4：导航Agent 向记忆Agent 发消息")
        print("=" * 60)

        # Agent A → Agent B：请求记忆搜索
        r = await client.post(f"{BASE_URL}/messages", json={
            "from": "peermind://volkswagen.com/navi",
            "to": "peermind://mem0.dev/memory-service",
            "intent": "skill_request",
            "payload": {
                "skill": "memory_search",
                "query": "用户偏好温度多少度",
                "user_id": "driver_zhang_car_001",
                "limit": 5,
            },
        })
        msg1 = r.json()
        print(f"消息已发送: ID={msg1['id']}")
        print(f"  From: {msg1['from_agent']}")
        print(f"  To:   {msg1['to_agent']}")
        print(f"  Intent: {msg1['intent']}")
        print(f"  Payload: {msg1['payload']}")

        # Agent B → Agent A：回复
        r = await client.post(f"{BASE_URL}/messages", json={
            "from": "peermind://mem0.dev/memory-service",
            "to": "peermind://volkswagen.com/navi",
            "intent": "skill_response",
            "payload": {
                "result": "用户偏好温度: 22°C",
                "source": "记忆数据库查询结果",
            },
            "in_reply_to": msg1["id"],
        })
        msg2 = r.json()
        print(f"\n回复已发送: ID={msg2['id']}")
        print(f"  Payload: {msg2['payload']}")

        # ── 步骤 5：签名验证 ──
        print("\n" + "=" * 60)
        print("步骤 5：验证消息签名")
        print("=" * 60)

        for msg_id, desc in [(msg1["id"], "请求消息"), (msg2["id"], "回复消息")]:
            r = await client.post(f"{BASE_URL}/messages/verify", json={
                "id": msg1["id"] if msg_id == msg1["id"] else msg2["id"],
                "from_agent": msg1["from_agent"] if msg_id == msg1["id"] else msg2["from_agent"],
                "to_agent": msg1["to_agent"] if msg_id == msg1["id"] else msg2["to_agent"],
                "intent": msg1["intent"] if msg_id == msg1["id"] else msg2["intent"],
                "payload": msg1["payload"] if msg_id == msg1["id"] else msg2["payload"],
                "timestamp": msg1["timestamp"] if msg_id == msg1["id"] else msg2["timestamp"],
                "signature": msg1["signature"] if msg_id == msg1["id"] else msg2["signature"],
                "in_reply_to": msg1.get("in_reply_to") if msg_id == msg1["id"] else msg2.get("in_reply_to"),
            })
            result = r.json()
            status = "✅ 通过" if result["valid"] else "❌ 失败"
            print(f"  [{desc}] 签名验证: {status}")

        # ── 步骤 6：查看收件箱 ──
        print("\n" + "=" * 60)
        print("步骤 6：查看收件箱")
        print("=" * 60)

        r = await client.get(f"{BASE_URL}/messages/inbox", params={
            "agent_id": "peermind://mem0.dev/memory-service",
        })
        inbox = r.json()
        print(f"[记忆Agent] 收件箱中有 {len(inbox)} 条消息:")
        for msg in inbox:
            print(f"  - 来自 {msg['from_agent']}: {msg['intent']}")

        r = await client.get(f"{BASE_URL}/messages/inbox", params={
            "agent_id": "peermind://volkswagen.com/navi",
        })
        inbox = r.json()
        print(f"\n[导航Agent] 收件箱中有 {len(inbox)} 条消息:")
        for msg in inbox:
            print(f"  - 来自 {msg['from_agent']}: {msg['intent']}")

        # ── 完成 ──
        print("\n" + "=" * 60)
        print("Demo 完成！")
        print("=" * 60)


if __name__ == "__main__":
    print("启动 Agent 通信网络 Demo...\n")
    print("请确保先启动服务端: uvicorn agent_network.main:app --reload\n")
    asyncio.run(demo())
