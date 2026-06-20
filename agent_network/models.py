"""
Pydantic 数据模型：请求/响应的类型定义
"""
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime, timezone
import uuid


# ── Agent 相关模型 ──

class Capability(BaseModel):
    """Agent 的技能描述"""
    skill: str = Field(..., description="技能名称，如 memory_search")
    description: str = Field("", description="技能说明")


class AgentRegisterRequest(BaseModel):
    """Agent 注册请求"""
    agent_id: str = Field(
        ...,
        pattern=r"^peermind://[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*/.+$",
        description="Agent ID，格式 peermind://org/name（org 可含点也可不含）",
        examples=["peermind://volkswagen.com/navi", "peermind://personal/kafka/taoken"]
    )
    agent_type: str = Field(
        "individual_verified",
        description="Agent 类型: organization / individual_org / individual_verified / individual_unverified"
    )
    display_name: str = Field(..., description="显示名称")
    public_key: str = Field(..., description="Base64 编码的 Ed25519 公钥")
    endpoint: str = Field(..., description="Agent 的 HTTP 端点地址")
    capabilities: list[Capability] = Field(default_factory=list, description="技能列表")


class AgentProfile(BaseModel):
    """Agent 完整信息（响应）"""
    agent_id: str
    agent_type: str
    display_name: str
    public_key: str
    endpoint: str
    capabilities: list[Capability]
    is_active: bool
    registered_at: str
    updated_at: str


class AgentSearchRequest(BaseModel):
    """Agent 搜索请求"""
    q: Optional[str] = Field(None, description="关键词搜索（名称、描述）")
    skill: Optional[str] = Field(None, description="按技能过滤")
    organization: Optional[str] = Field(None, description="按组织过滤")
    agent_type: Optional[str] = Field(None, description="按类型过滤")
    page: int = Field(1, ge=1, description="页码")
    limit: int = Field(20, ge=1, le=100, description="每页数量")


class AgentSearchResult(BaseModel):
    """搜索结果"""
    total: int
    page: int
    limit: int
    agents: list[AgentProfile]


# ── 消息相关模型 ──

class MessagePayload(BaseModel):
    """消息载荷（可扩展）"""
    skill: Optional[str] = Field(None, description="请求的技能名")
    query: Optional[str] = Field(None, description="查询内容")
    result: Optional[str] = Field(None, description="返回结果")
    user_id: Optional[str] = Field(None, description="用户标识")
    limit: Optional[int] = Field(None, description="结果数量限制")


class SendMessageRequest(BaseModel):
    """发送消息请求（不含签名，签名由 API 层计算）"""
    from_agent: str = Field(..., alias="from", description="发送方 Agent ID")
    to_agent: str = Field(..., alias="to", description="接收方 Agent ID")
    intent: str = Field(..., description="通信意图")
    payload: dict = Field(default_factory=dict, description="载荷数据")
    in_reply_to: Optional[str] = Field(None, description="回复的消息ID")


class AgentMessage(BaseModel):
    """完整消息（含签名和时间戳，API 在存储时自动补充）"""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    from_agent: str
    to_agent: str
    intent: str
    payload: dict
    in_reply_to: Optional[str] = None
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    signature: str = ""
