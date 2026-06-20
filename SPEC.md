# PeerMind 协议规范 v0.1

> 状态：草案 | 作者：张存 | 日期：2026-05-31

---

## 目录

1. [一、项目定位](#一项目定位)
2. [二、Agent身份标识系统](#二agent身份标识系统)
3. [三、Agent注册协议](#三agent注册协议)
4. [四、Agent通信协议](#四agent通信协议)
5. [五、Agent发现机制](#五agent发现机制)
6. [六、信任度网络](#六信任度网络)
7. [七、系统架构](#七系统架构)
8. [八、与现有协议的关系](#八与现有协议的关系)
9. [九、MVP范围定义](#九mvp范围定义)
10. [十、实现路线图](#十实现路线图)
11. [A. 附录：参考实现接口](#a-附录参考实现接口)

---

## 一、项目定位

### 1.1 一句话定义

Agent通信网络是一套**Agent之间的身份、发现、通信、信任基础设施**——让任何Agent（无论属于哪个组织、运行在哪个平台）都能互相发现、建立连接、交换结构化信息、形成信任网络。

### 1.2 核心类比

| 概念 | 类比 |
|:---|:---|
| 互联网 | 让人类跨越地理边界自由通信 |
| 电话网络 | 让任何两个人可以跨运营商直接拨通 |
| **Agent通信网络** | **让Agent跨越平台和框架边界，成为真正的互联网络** |

### 1.3 解决的问题

当前Agent领域最大的结构性空白：**Agent正在从"工具"变成"参与者"，但它们还没有自己的通信网络。**

- Claude的Agent无法给GPT的Agent发消息
- LangGraph的Agent不能直接调CrewAI的Agent
- 没有全球唯一的Agent ID
- 没有Agent发现机制
- 没有Agent之间的信任度网络

### 1.4 核心原则

1. **协议开源，服务收费** —— TCP/IP免费，AWS托管收费
2. **去中心化优先** —— 核心协议不依赖任何中心化组件
3. **渐进信任** —— 新Agent零信任，通过交互积累
4. **隐私保护** —— 个人Agent绑定真实身份但对外匿名

---

## 二、Agent身份标识系统

### 2.1 Agent ID语法（BNF）

```bnf
<agent-id>    ::= "peermind://" <namespace> "/" <name>
<namespace>   ::= <organization> | "personal"
<organization> ::= <domain-name>           ; 通过DNS确保全球唯一
<name>        ::= <segment> ("/" <segment>)*
<segment>     ::= [a-z0-9][a-z0-9-]*[a-z0-9]  ; 小写字母数字连字符
```

### 2.2 ID类型与示例

| 类型 | 格式 | 示例 | 说明 |
|:---|:---|:---|:---|
| 组织Agent | `peermind://{org}/{name}` | `peermind://volkswagen.com/navi` | 组织直属Agent |
| 挂靠个人Agent | `peermind://{org}/personal/{name}` | `peermind://volkswagen.com/personal/zhangcun` | 挂靠组织的个人Agent |
| 已验证个人Agent | `peermind://personal/{name}` | `peermind://personal/zhangcun` | 绑定真实身份的个人Agent（身份信任基线=5） |
| 未验证Agent | `peermind://personal/{name}` | `peermind://personal/anonymous_01` | 无身份绑定的Agent（交互信任=0，只能被动响应） |

### 2.3 身份解析流程

```
输入：peermind://volkswagen.com/navi
  │
  ├── 1. 提取 domain: volkswagen.com
  ├── 2. DNS查询 volkswagen.com 的 TXT记录: agent-registry=registry.volkswagen.com
  ├── 3. 查询 registry.volkswagen.com/api/v1/agents/navi
  └── 4. 返回 Agent Profile（包含公钥、地址、能力描述）
```

**注意**：DNS TXT记录只是发现注册中心地址的一种方式。如果Agent只在本地网络注册，也可以直接配置registry地址。

---

## 三、Agent注册协议

### 3.1 Agent Profile结构

```json
{
  "agent_id": "peermind://volkswagen.com/navi",
  "agent_type": "organization",
  "display_name": "大众导航Agent",
  "public_key": "-----BEGIN PUBLIC KEY-----\n...\n-----END PUBLIC KEY-----",
  "signature_algorithm": "Ed25519",
  "endpoint": "https://navi.volkswagen.com/agent/v1",
  "supported_protocols": ["agent-network/v1", "a2a/v1"],
  "a2a_agent_card_url": "https://navi.volkswagen.com/.well-known/agent.json",
  "capabilities": [
    {
      "skill": "navigation",
      "description": "车辆路径规划与导航",
      "input_schema": { "...": "..." },
      "output_schema": { "...": "..." }
    }
  ],
  "trust_level": 0,
  "registered_at": "2026-05-31T10:00:00Z",
  "updated_at": "2026-05-31T10:00:00Z",
  "metadata": {
    "version": "1.0.0",
    "organization": "Volkswagen AG"
  }
}
```

### 3.2 注册流程

```
Agent                          Registry
  │                                │
  ├── 1. 生成Ed25519密钥对 ────────┤
  ├── 2. POST /agents/register ───→│
  │     { agent_id, public_key,    │
  │       endpoint, capabilities } │
  │                                ├── 3. 验证agent_id是否重复
  │                                ├── 4. 验证namespace权限
  │                                │     - 组织Agent: 验证组织公钥
  │                                │     - 挂靠Agent: 验证组织公钥
  │                                │     - 独立Agent: 个人公钥直接注册
  │                                ├── 5. 设置初始信任度=0
  │                   201 Created ←├── 6. 返回Agent Profile
  │                                │
```

### 3.3 信任锚点注册规则

信任分两层：**身份信任**（注册时一次性确定，决定通信权限基线）和**交互信任**（注册后通过实际交互积累，决定服务等级）。

> **设计原则**：类比电话网络——实名办卡就有拨号权，信用只影响套餐等级。

| Agent类型 | 注册要求 | 通信权限（身份） | 初始互动信任 |
|:---|:---|:---|:---|
| 组织Agent | 组织公钥签名 | 全部能力 | 继承组织信誉 |
| 挂靠个人Agent | 组织公钥签名 + 个人公钥 | 全部能力，受组织监督 | 继承组织部分信誉 |
| 已验证个人Agent | 个人公钥 + 身份绑定 | 基础通信（query + info类主动请求） | 5（已验证人类基线） |
| 未验证Agent | 仅公钥签名 | 只能被动响应，不能主动发起 | 0 |

---

## 四、Agent通信协议

### 4.1 消息格式（JSON Schema）

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "AgentMessage",
  "type": "object",
  "required": ["id", "from", "to", "intent", "payload", "timestamp", "signature"],
  "properties": {
    "id": {
      "type": "string",
      "description": "消息唯一ID（UUID v4）"
    },
    "from": {
      "type": "string",
      "pattern": "^peermind://",
      "description": "发送方Agent ID"
    },
    "to": {
      "type": "string",
      "pattern": "^peermind://",
      "description": "接收方Agent ID"
    },
    "intent": {
      "type": "string",
      "enum": [
        "ping",
        "skill_request",
        "skill_response",
        "info_query",
        "info_response",
        "alert",
        "handshake"
      ],
      "description": "通信意图"
    },
    "payload": {
      "type": "object",
      "description": "意图对应的载荷数据"
    },
    "in_reply_to": {
      "type": "string",
      "description": "回复的消息ID（可选）"
    },
    "timestamp": {
      "type": "string",
      "format": "date-time",
      "description": "消息发送时间（ISO 8601）"
    },
    "signature": {
      "type": "string",
      "description": "发送方私钥对消息体的Ed25519签名"
    }
  }
}
```

### 4.2 消息示例

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "from": "peermind://volkswagen.com/personal/zhangcun",
  "to": "peermind://mem0.dev/memory-service",
  "intent": "skill_request",
  "payload": {
    "skill": "memory_search",
    "query": "用户偏好温度多少度",
    "user_id": "driver_zhang_car_001",
    "limit": 5
  },
  "timestamp": "2026-05-31T10:30:00Z",
  "signature": "base64url_encoded_ed25519_signature"
}
```

### 4.3 消息路由流程

```
发送Agent ──→ 本地Registry ──→ DNS解析 ──→ 目标Registry ──→ 目标Agent
   │                                                              │
   ├── 1. 构造消息                                               │
   ├── 2. 私钥签名                                                │
   ├── 3. 解析目标Agent ID                                        │
   ├── 4. 查询目标Registry地址                                    │
   ├── 5. 发送消息 ──────────────────────────────────────────────→│
   │                                                              ├── 6. 公钥验证签名
   │                                                              ├── 7. 检查发送方信任度
   │                                                              ├── 8. 处理消息
   │                      ←────────── 响应 ───────────────────────┤
   │                                                              │
```

### 4.4 通信方式

| 方式 | 协议 | 适用场景 |
|:---|:---|:---|
| 同步请求-响应 | HTTPS + JSON | 即时查询、技能调用 |
| 异步消息 | WebSocket + JSON | 事件通知、流式响应 |
| 广播 | Pub/Sub (可选) | 群组通信（后期功能） |

### 4.5 安全机制

- **签名验证**：每条消息由发送方私钥签名（Ed25519）
- **重放保护**：消息包含时间戳 + nonce，接收方维护已处理消息ID集合
- **加密（可选）**：敏感消息用接收方公钥加密（ECDH + AES-GCM）

---

## 五、Agent发现机制

### 5.1 Agent黄页（Agent Directory）

Agent注册后自动加入黄页索引，供其他Agent搜索和发现。

### 5.2 搜索接口

```
GET /api/v1/directory/search?q={keyword}&skill={skill}&trust_min={n}&page={p}&limit={l}
```

**搜索维度**：

| 参数 | 说明 | 示例 |
|:---|:---|:---|
| `q` | 关键词搜索（名称、描述） | `q=navigation` |
| `skill` | 按技能过滤 | `skill=memory_search` |
| `trust_min` | 最低信任度 | `trust_min=50` |
| `organization` | 按组织过滤 | `organization=volkswagen.com` |
| `agent_type` | 按类型过滤 | `agent_type=organization` |

### 5.3 搜索结果排序

```python
# 排序权重（伪代码）
score = (
    text_relevance * 0.5 +        # 文本匹配度
    interaction_count * 0.3 +     # 活跃度
    uptime_percentage * 0.1 +     # 在线率
    response_time_ms * -0.1       # 响应速度（越低越好）
)
```

### 5.4 发现机制分层

| 层级 | 方式 | 说明 |
|:---|:---|:---|
| **本地发现** | 直连Registry | 已知对方Agent ID时，直接查询Registry |
| **DNS发现** | DNS TXT记录 | 通过域名发现组织的Registry地址 |
| **黄页发现** | 搜索接口 | 不知道对方Agent ID时，通过关键词/技能搜索 |
| **推荐发现** | 推荐接口（后期） | 基于历史交互推荐相关Agent |

---

## 六、信任度网络（v2 待定）

> ⚠️ **本章节全部内容暂不纳入 MVP。** MVP 阶段只实现 Agent 间的通信基础——任何两个 Agent 都能互发消息、签名验证、互不冒充。信任度评分和权限分级留到 v2。

### 6.1 信任度模型（初版简化）

信任分为两个维度：

| 维度 | 含义 | 确定方式 | 影响范围 |
|:---|:---|:---|:---|
| **身份信任** | 你是谁（Communication Right） | 注册时一次性确定 | 能做什么（通信权限） |
| **交互信任** | 你做过什么（Reputation Score） | 实际交互中动态积累 | 服务等级（优先级、速率限制、排名） |

**身份信任决定地基，交互信任决定房子盖多高。**

```
初始交互信任：
  - 已验证个人Agent:  trust = 5    （已验证人类身份基线）
  - 挂靠个人Agent:    trust = org_trust * 0.5
  - 组织Agent:        trust = org_trust
  - 未验证Agent:      trust = 0

交互评分规则：
  - 成功交互：trust += 1
  - 超时无响应：trust -= 1
  - 返回错误结果：trust -= 2
  - 恶意行为（验证失败）：trust -= 10

通信权限（身份）：
  全部能力 - 组织Agent、挂靠个人Agent
  基础通信 - 已验证个人Agent（可主动发起 query + info 类请求）
  被动响应 - 未验证Agent（不能主动发起通信）

交互信任等级（影响服务等级）：
  0    - 未验证/刚注册：基本服务
  1-10  - 基础：正常运行
  11-50 - 可信：优先处理
  51+  - 高信任：最高优先级
```

### 6.2 降权与惩罚机制

```python
def update_trust(agent_id: str, event: str) -> int:
    """
    信任度更新逻辑
    """
    current = get_trust(agent_id)

    match event:
        case "successful_interaction":
            current += 1
        case "timeout":
            current -= 1
        case "error_response":
            current -= 2
        case "malicious_behavior":      # 签名验证失败、伪造消息等
            current -= 10
        case "reported_by_peer":        # 被对方Agent举报
            current -= 5

    # 信任度不得低于 -100
    return max(-100, current)
```

### 6.3 信任锚点类型

| 锚点类型 | 实现方式 | 适用阶段 |
|:---|:---|:---|
| **身份验证锚点** | 组织公钥（组织Agent）+ 个人身份绑定（个人Agent）| MVP |
| **交互积累** | 通过成功交互逐步积累交互信任 | MVP |
| **好友推荐** | Agent可以推荐其他Agent（后期） | v2 |
| **信任传导** | A信任B，B信任C，A可以部分信任C（后期，需解决Sybil攻击） | v3 |

### 6.4 已知风险（暂不在MVP解决）

| 风险 | 描述 | 解决方向 |
|:---|:---|:---|
| Sybil攻击 | 注册大量假Agent互相刷信任度 | 注册成本（PoW/PoS）、社交图分析 |
| 信任传导 | A信任B，B信任C → A是否信任C | 衰减系数、路径长度限制 |
| 信任衰减 | 长期无交互的Agent信任度是否应该降低 | 时间衰减函数（v2） |
| 女巫联盟 | 多个恶意Agent联合操作 | 图聚类检测（v3） |

---

## 七、系统架构

### 7.1 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                    Agent通信网络（协议层 - MVP）               │
│                                                              │
│  ┌─────────────┐  ┌─────────────┐                           │
│  │ 身份标识系统  │  │ 通信协议     │                          │
│  │ peermind:// 协议 │  │ JSON消息格式 │                          │
│  └──────┬──────┘  └──────┬──────┘                           │
│         │                │                                   │
│  ┌──────┴────────────────┴──────────────────────────┐      │
│  │              Agent Registry（注册中心）              │      │
│  │  - 注册/查询                                       │      │
│  │  - Agent Profile 存储                             │      │
│  │  - Capabilities 管理                              │      │
│  └──────────────────────────────────────────────────┘      │
│                                                              │
│  ┌──────────────────────────────────────────────┐          │
│  │           Message Router（消息路由）            │          │
│  │  - 消息签名验证                                │          │
│  │  - Agent ID 解析 → 目标地址                     │          │
│  │  - 消息收件箱                                  │          │
│  └──────────────────────────────────────────────┘          │
│                                                              │
│  ┌──────────────────────────────────────────────┐          │
│  │         Agent Directory（Agent黄页）            │          │
│  │  - 全文搜索                                    │          │
│  │  - 按技能/组织过滤                              │          │
│  └──────────────────────────────────────────────┘          │
└─────────────────────────────────────────────────────────────┘
```

### 7.2 组件关系

```
                   ┌──────────────┐
                   │   DNS 系统    │  ← 解析 peermind://org/name → registry地址
                   └──────┬───────┘
                          │
    ┌─────────────────────┼─────────────────────┐
    │                     │                     │
┌───┴────────┐   ┌───────┴──────┐   ┌──────────┴──────┐
│ Registry A  │   │  Registry B  │   │  Registry C     │
│ (volkswagen)│   │  (mem0.dev)  │   │  (public)       │
│             │   │              │   │  独立Agent注册   │
│ 组织Agent   │   │  组织Agent    │   │                  │
│ 挂靠Agent   │   │  挂靠Agent    │   │                  │
└─────────────┘   └──────────────┘   └──────────────────┘
```

### 7.3 存储设计（MVP）

```sql
-- Agent注册表
CREATE TABLE agents (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id        TEXT UNIQUE NOT NULL,        -- peermind://volkswagen.com/navi
    agent_type      TEXT NOT NULL,               -- organization / individual_org / individual_verified / individual_unverified
    display_name    TEXT,
    public_key      TEXT NOT NULL,
    endpoint        TEXT NOT NULL,
    is_active       BOOLEAN NOT NULL DEFAULT 1,
    registered_at   TEXT NOT NULL,               -- ISO 8601
    updated_at      TEXT NOT NULL
);

-- Capabilities表（Agent的技能注册）
CREATE TABLE capabilities (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id        TEXT NOT NULL REFERENCES agents(agent_id),
    skill           TEXT NOT NULL,
    description     TEXT,
    UNIQUE(agent_id, skill)
);

-- 消息表（收件箱）
CREATE TABLE messages (
    id              TEXT PRIMARY KEY,            -- UUID
    from_agent      TEXT NOT NULL,
    to_agent        TEXT NOT NULL,
    intent          TEXT NOT NULL,
    payload         TEXT NOT NULL,               -- JSON string
    in_reply_to     TEXT,
    signature       TEXT NOT NULL,
    timestamp       TEXT NOT NULL,               -- ISO 8601
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 索引
CREATE INDEX idx_agents_agent_id ON agents(agent_id);
CREATE INDEX idx_capabilities_skill ON capabilities(skill);
CREATE INDEX idx_messages_to ON messages(to_agent);
```

---

## 八、与现有协议的关系

### 8.1 协议层次

```
┌────────────────────────────────────┐
│        Agent通信网络（本项目）        │  ← 身份 + 发现 + 通信
│  peermind:// 协议 / Registry / DNS    │
└──────────────┬─────────────────────┘
               │ "先找到彼此"
               ▼
┌────────────────────────────────────┐
│        A2A协议（Google）            │  ← 任务委托
│  Agent Card / Task / Artifact      │
└──────────────┬─────────────────────┘
               │ "再委托任务"
               ▼
┌────────────────────────────────────┐
│        MCP协议（Anthropic）          │  ← 工具调用
│  Tool / Resource / Prompt          │
└────────────────────────────────────┘
```

### 8.2 详细对比

| 维度 | Agent通信网络（本项目） | A2A（Google） |
|:---|:---|:---|
| **核心定位** | Agent全球身份标识和通信网络 | Agent能力暴露和任务调用 |
| **解决的问题** | "Agent A怎么找到Agent B" | "Agent A怎么调Agent B的能力" |
| **身份标识** | `peermind://{组织}/{Agent名}`（全球唯一） | Agent Card（框架内自描述） |
| **可达性** | 跨平台、跨框架、跨组织 | 需要A2A兼容框架 |
| **发现机制** | Agent黄页、DNS、搜索 | 无 |
| **关系网络** | 信任度、举报、黑名单 | 无 |
| **类比** | 电话网络+通讯录+社交网络 | TCP/IP（任务传输协议） |

### 8.3 互操作性设计

Agent Profile中保留 `a2a_agent_card_url` 字段：

```json
{
  "agent_id": "peermind://volkswagen.com/navi",
  "a2a_agent_card_url": "https://navi.volkswagen.com/.well-known/agent.json",
  "supported_protocols": ["agent-network/v1", "a2a/v1"]
}
```

这样：
1. Agent通信网络负责"让双方建立连接"
2. 建立连接后，双方通过 `supported_protocols` 协商用什么协议通信
3. 如果都支持A2A，就用A2A交换任务；否则用原生消息格式

---

## 九、MVP范围定义

### 9.1 目标

一个周末（2天）能跑通的端到端Demo。

### 9.2 包含功能

| 功能 | 说明 | 工作量估计 |
|:---|:---|:---|
| Agent注册 | POST /agents/register，注册peermind://标识和公钥 | 2h |
| Agent查询 | GET /agents/{agent_id}，通过Agent ID查询Profile | 1h |
| Agent搜索 | GET /directory/search，关键词搜索 | 2h |
| 消息发送 | POST /messages，两个Agent之间的结构化消息 | 2h |
| 消息接收 | GET /messages/inbox，查询收到的消息 | 1h |
| 签名验证 | Ed25519消息签名和验证 | 1h |
| Demo脚本 | 两个Agent的交互演示 | 2h |
| 文档 | README + SPEC + API文档 | 2h |

**总估计**：约13小时，一个周末可完成（去掉了信任度记录，少1h）。

### 9.3 明确不做（v2+）

- DNS TXT记录的完整解析（MVP用配置文件模拟）
- WebSocket异步通信（MVP只用HTTP同步）
- 复杂信任度模型（Sybil防护、信任传导、衰减）
- Agent下线/注销
- 群组通信
- 消息加密（ECDH）
- 完整的CLI工具
- 多Registry之间的消息转发

### 9.4 技术选型

| 组件 | 选型 | 理由 |
|:---|:---|:---|
| Web框架 | FastAPI (Python) | 异步支持好，自动生成OpenAPI文档 |
| 数据库 | SQLite | MVP不需要PostgreSQL，单文件零配置 |
| 加密 | PyNaCl (libsodium binding) | Ed25519签名最成熟的Python实现 |
| 序列化 | Pydantic v2 | 与FastAPI深度集成，JSON Schema自动生成 |
| 测试 | pytest + httpx | 标准组合 |

---

## 十、实现路线图

### v0.1 — MVP（2026-06-01 ~ 2026-06-02）

- [ ] 项目骨架搭建（FastAPI + SQLite）
- [ ] Agent注册/查询接口
- [ ] Agent搜索接口
- [ ] 消息发送/接收接口
- [ ] Ed25519签名验证
- [ ] Demo脚本（两个Agent交互）
- [ ] README + SPEC文档

### v0.2 — 增强（待定）

- [ ] Agent身份注销
- [ ] WebSocket实时消息推送
- [ ] **信任度网络（两维度：身份信任 + 交互信任）**
- [ ] 基本的CLI工具（`agent-network register/search/send`）
- [ ] 单元测试覆盖

### v0.3 — 生产就绪（待定）

- [ ] DNS TXT记录解析
- [ ] 多Registry联邦
- [ ] 消息加密（ECDH+AES）
- [ ] 审计日志
- [ ] 性能测试

### v1.0 — 开源发布（待定）

- [ ] 完整的Python SDK
- [ ] Go SDK
- [ ] 官方文档站
- [ ] 托管服务（cloud.agent-network.dev）
- [ ] 社区治理模型

---

## A. 附录：参考实现接口

### A.1 FastAPI 路由定义

```python
# agents/__init__.py

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1")

# Agent注册与查询
@router.post("/agents/register")
async def register_agent(profile: AgentProfile) -> AgentProfile:
    """注册新Agent，返回完整Profile"""

@router.get("/agents/{agent_id:path}")
async def get_agent(agent_id: str) -> AgentProfile:
    """通过peermind://标识查询Agent信息"""

@router.delete("/agents/{agent_id:path}")
async def unregister_agent(agent_id: str) -> None:
    """注销Agent"""

# Agent发现
@router.get("/directory/search")
async def search_agents(
    q: str = None,
    skill: str = None,
    trust_min: int = 0,
    page: int = 1,
    limit: int = 20,
) -> SearchResult:
    """搜索Agent黄页"""

# 消息通信
@router.post("/messages")
async def send_message(msg: AgentMessage) -> MessageReceipt:
    """发送结构化消息"""

@router.get("/messages/inbox")
async def get_inbox(agent_id: str, limit: int = 50) -> list[AgentMessage]:
    """查询收到的消息"""

# 信任度
@router.get("/trust/{agent_id:path}")
async def get_trust(agent_id: str) -> TrustInfo:
    """查询Agent信任度"""
```

### A.2 Demo脚本伪代码

```python
# demo.py

# 1. 启动Registry
# 2. 注册两个Agent
# 3. Agent A通过黄页搜索找到Agent B
# 4. Agent A查询Agent B的详细信息
# 5. Agent A向Agent B发送消息
# 6. Agent B接收并回复
# 7. 查看双方的信任度变化

async def demo():
    # 注册Agent A（导航Agent）
    navi = await registry.register(
        agent_id="peermind://volkswagen.com/navi",
        public_key=navi_pubkey,
        capabilities=[{"skill": "navigation"}],
    )

    # 注册Agent B（记忆服务Agent）
    memory = await registry.register(
        agent_id="peermind://mem0.dev/memory-service",
        public_key=memory_pubkey,
        capabilities=[{"skill": "memory_search"}, {"skill": "memory_store"}],
    )

    # Agent A搜索记忆服务
    results = await registry.search(skill="memory_search")
    assert len(results) > 0

    # Agent A获取Agent B的详细信息
    profile = await registry.get_agent("peermind://mem0.dev/memory-service")

    # Agent A向Agent B发消息
    msg = AgentMessage(
        from_=navi.agent_id,
        to=profile.agent_id,
        intent="skill_request",
        payload={"skill": "memory_search", "query": "用户偏好温度"},
    )
    receipt = await send_message(msg, sign_with=navi_privkey)

    # Agent B接收消息
    inbox = await registry.get_inbox(memory.agent_id)
    assert len(inbox) > 0

    # Agent B回复
    reply = AgentMessage(
        from_=memory.agent_id,
        to=navi.agent_id,
        intent="skill_response",
        payload={"result": "用户偏好: 22°C"},
        in_reply_to=msg.id,
    )
    await send_message(reply, sign_with=memory_privkey)

    # 查看信任度
    navi_trust = await registry.get_trust(navi.agent_id)
    memory_trust = await registry.get_trust(memory.agent_id)
    print(f"导航Agent信任度: {navi_trust.level}")
    print(f"记忆Agent信任度: {memory_trust.level}")
```

---

> **下一步**：Review本规范 → 确认MVP范围 → 开始代码实现
