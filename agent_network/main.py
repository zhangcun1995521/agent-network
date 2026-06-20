"""
Agent 通信网络 - 注册中心 API
FastAPI 应用入口
"""
from fastapi import FastAPI, HTTPException, Query
from .database import init_db
from .agent_store import register_agent, get_agent, search_agents
from .message_store import store_message, get_inbox, get_conversation
from .crypto import sign_message, verify_signature, build_message_bytes
from .models import (
    AgentRegisterRequest,
    AgentProfile,
    AgentSearchResult,
    SendMessageRequest,
    AgentMessage,
)

# ── 应用初始化 ──

app = FastAPI(
    title="Agent Communication Network",
    description="Agent 身份注册、发现、通信基础设施",
    version="0.1.0",
)


@app.on_event("startup")
def startup():
    """启动时初始化数据库"""
    init_db()


# ── Agent 注册与查询 ──

@app.post("/api/v1/agents/register", response_model=AgentProfile, status_code=201)
def api_register_agent(req: AgentRegisterRequest):
    """
    注册新 Agent
    需要提供 peermind:// 标识、公钥、端点和技能列表
    """
    try:
        return register_agent(
            agent_id=req.agent_id,
            agent_type=req.agent_type,
            display_name=req.display_name,
            public_key=req.public_key,
            endpoint=req.endpoint,
            capabilities=req.capabilities,
        )
    except Exception as e:
        raise HTTPException(status_code=409, detail=str(e))


@app.get("/api/v1/agents/{agent_id:path}", response_model=AgentProfile)
def api_get_agent(agent_id: str):
    """
    通过 Agent ID 查询完整 Profile
    例如：GET /api/v1/agents/peermind://volkswagen.com/navi
    """
    try:
        return get_agent(agent_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/api/v1/directory/search", response_model=AgentSearchResult)
def api_search_agents(
    q: str = Query(None, description="关键词"),
    skill: str = Query(None, description="按技能过滤"),
    organization: str = Query(None, description="按组织过滤"),
    agent_type: str = Query(None, description="按类型过滤"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
):
    """
    搜索 Agent 黄页
    支持关键词、技能、组织、类型四维过滤
    """
    agents, total = search_agents(
        q=q, skill=skill, organization=organization,
        agent_type=agent_type, page=page, limit=limit,
    )
    return AgentSearchResult(total=total, page=page, limit=limit, agents=agents)


# ── 消息通信 ──

# 存储已注册 Agent 的私钥（Demo 用，生产环境绝不能这样）
# 实际使用时由发送方自行签名，这里为 Demo 简化
_agent_private_keys: dict[str, str] = {}


@app.post("/api/v1/agents/{agent_id:path}/private-key")
def api_store_private_key(agent_id: str, private_key: str = Query(...)):
    """
    Demo 用：存储 Agent 私钥（仅用于 Demo，生产环境绝不做此接口）
    """
    _agent_private_keys[agent_id] = private_key
    return {"status": "ok", "agent_id": agent_id}


@app.post("/api/v1/messages", response_model=AgentMessage)
def api_send_message(req: SendMessageRequest):
    """
    发送结构化消息
    服务端自动用发送方私钥签名，接收方可通过公钥验证
    """
    # 构建消息对象
    msg = AgentMessage(
        from_agent=req.from_agent,
        to_agent=req.to_agent,
        intent=req.intent,
        payload=req.payload,
        in_reply_to=req.in_reply_to,
    )

    # 签名：用发送方的私钥对消息体签名
    private_key = _agent_private_keys.get(req.from_agent)
    if private_key is None:
        raise HTTPException(
            status_code=400,
            detail=f"发送方 {req.from_agent} 的私钥未注册。"
                   f"请先调用 POST /api/v1/agents/{req.from_agent}/private-key?private_key=...",
        )

    msg_bytes = build_message_bytes(msg.model_dump(by_alias=True))
    msg.signature = sign_message(private_key, msg_bytes)

    # 存储
    store_message(msg)

    return msg


@app.get("/api/v1/messages/inbox", response_model=list[AgentMessage])
def api_get_inbox(
    agent_id: str = Query(..., description="Agent ID"),
    limit: int = Query(50, ge=1, le=200),
):
    """
    查询 Agent 的收件箱
    """
    return get_inbox(agent_id, limit)


@app.get("/api/v1/messages/conversation", response_model=list[AgentMessage])
def api_get_conversation(
    a: str = Query(..., description="Agent A ID"),
    b: str = Query(..., description="Agent B ID"),
    limit: int = Query(50, ge=1, le=200),
):
    """
    查询两个 Agent 之间的对话历史
    """
    return get_conversation(a, b, limit)


@app.post("/api/v1/messages/verify")
def api_verify_message(msg: AgentMessage):
    """
    验证消息签名
    输入完整消息，返回签名是否有效
    """
    # 先查发送方的公钥
    try:
        profile = get_agent(msg.from_agent)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"发送方 {msg.from_agent} 不存在")

    msg_bytes = build_message_bytes(msg.model_dump(by_alias=True))
    valid = verify_signature(profile.public_key, msg_bytes, msg.signature)

    return {
        "valid": valid,
        "from_agent": msg.from_agent,
        "message_id": msg.id,
    }


# ── 健康检查 ──

@app.get("/health")
def health():
    return {"status": "ok", "service": "agent-network-registry"}
