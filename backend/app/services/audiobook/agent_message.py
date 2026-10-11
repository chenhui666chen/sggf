"""
Agent间通信消息协议

标准化各Agent之间的数据传递格式
"""
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional
from datetime import datetime
from enum import Enum


class MessagePriority(Enum):
    """消息优先级"""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class AgentType(Enum):
    """Agent类型"""
    AUDIO_DIRECTOR = "audio_director"
    SCRIPT_ADAPTER = "script_adapter"
    SOUND_DESIGNER = "sound_designer"
    MUSIC_COMPOSER = "music_composer"
    QUALITY_REVIEWER = "quality_reviewer"
    COORDINATOR = "coordinator"


@dataclass
class AgentMessage:
    """Agent消息基类"""
    message_id: str  # 消息唯一ID
    sender: AgentType  # 发送者
    recipient: AgentType  # 接收者
    content: Dict[str, Any]  # 消息内容
    priority: MessagePriority = MessagePriority.NORMAL
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    correlation_id: Optional[str] = None  # 关联ID（用于追踪任务）
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        result = asdict(self)
        result['sender'] = self.sender.value
        result['recipient'] = self.recipient.value
        result['priority'] = self.priority.value
        return result


@dataclass
class StrategyMessage(AgentMessage):
    """改编策略消息（AudioDirector → ScriptAdapter）"""
    
    @classmethod
    def create(cls, strategy_data: Dict[str, Any], correlation_id: str):
        return cls(
            message_id=f"strategy_{correlation_id}",
            sender=AgentType.AUDIO_DIRECTOR,
            recipient=AgentType.SCRIPT_ADAPTER,
            content=strategy_data,
            priority=MessagePriority.HIGH,
            correlation_id=correlation_id
        )


@dataclass
class ScriptMessage(AgentMessage):
    """剧本消息（ScriptAdapter → SoundDesigner/MusicComposer）"""
    
    @classmethod
    def create(cls, script_data: Dict[str, Any], recipient: AgentType, correlation_id: str):
        return cls(
            message_id=f"script_{recipient.value}_{correlation_id}",
            sender=AgentType.SCRIPT_ADAPTER,
            recipient=recipient,
            content=script_data,
            priority=MessagePriority.HIGH,
            correlation_id=correlation_id
        )


@dataclass
class QualityReportMessage(AgentMessage):
    """质量报告消息（QualityReviewer → Coordinator）"""
    
    @classmethod
    def create(cls, report_data: Dict[str, Any], correlation_id: str):
        return cls(
            message_id=f"quality_report_{correlation_id}",
            sender=AgentType.QUALITY_REVIEWER,
            recipient=AgentType.COORDINATOR,
            content=report_data,
            priority=MessagePriority.NORMAL,
            correlation_id=correlation_id
        )


class MessageBus:
    """简单的消息总线（内存版本）"""
    
    def __init__(self):
        self.messages: List[AgentMessage] = []
        self.subscribers: Dict[AgentType, List[callable]] = {}
    
    def publish(self, message: AgentMessage):
        """发布消息"""
        self.messages.append(message)
        
        # 通知订阅者
        if message.recipient in self.subscribers:
            for handler in self.subscribers[message.recipient]:
                handler(message)
    
    def subscribe(self, agent_type: AgentType, handler: callable):
        """订阅消息"""
        if agent_type not in self.subscribers:
            self.subscribers[agent_type] = []
        self.subscribers[agent_type].append(handler)
    
    def get_messages_by_correlation(self, correlation_id: str) -> List[AgentMessage]:
        """根据关联ID获取消息链"""
        return [msg for msg in self.messages if msg.correlation_id == correlation_id]
