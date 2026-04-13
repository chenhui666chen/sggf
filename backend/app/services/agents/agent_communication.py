"""
Agent通信模块 - 支持Agent之间的直接通信和协作
"""
import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from datetime import datetime
from enum import Enum


logger = logging.getLogger(__name__)


class MessageType(Enum):
    """消息类型"""
    REQUEST = "request"           # 请求
    RESPONSE = "response"         # 响应
    FEEDBACK = "feedback"         # 反馈
    QUESTION = "question"         # 提问
    SUGGESTION = "suggestion"     # 建议
    CONFLICT = "conflict"         # 冲突


@dataclass
class Message:
    """Agent之间的消息"""
    sender: str                          # 发送者Agent名称
    receiver: str                        # 接收者Agent名称
    message_type: MessageType            # 消息类型
    content: str                         # 消息内容
    timestamp: Optional[datetime] = None # 时间戳
    context: Optional[Dict[str, Any]] = None # 上下文信息
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()
        if self.context is None:
            self.context = {}
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "sender": self.sender,
            "receiver": self.receiver,
            "type": self.message_type.value,
            "content": self.content,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "context": self.context
        }


class AgentCommunicationHub:
    """Agent通信中心 - 管理Agent之间的通信"""
    
    def __init__(self):
        """初始化通信中心"""
        self.message_queue: List[Message] = []
        self.message_history: List[Message] = []
        self.agent_registry: Dict[str, Any] = {}
        self.conflict_log: List[Dict[str, Any]] = []
    
    def register_agent(self, agent_name: str, agent_instance: Any):
        """注册Agent"""
        self.agent_registry[agent_name] = agent_instance
        logger.debug(f"✓ Agent '{agent_name}' 已注册到通信中心")
    
    def send_message(self, message: Message) -> bool:
        """发送消息"""
        if message.receiver not in self.agent_registry:
            logger.debug(f"✗ 接收者 '{message.receiver}' 未注册")
            return False
        
        self.message_queue.append(message)
        self.message_history.append(message)
        
        logger.debug(f"📨 [{message.sender}] → [{message.receiver}]: {message.message_type.value}")
        logger.debug(f"   内容: {message.content[:100]}...")
        
        return True
    
    def process_messages(self) -> Dict[str, List[Message]]:
        """处理消息队列中的所有消息"""
        responses = {}
        
        while self.message_queue:
            message = self.message_queue.pop(0)
            receiver = self.agent_registry[message.receiver]
            
            # 调用接收者的处理方法
            response_content = receiver.process(message.content, message.context)
            
            # 创建响应消息
            response = Message(
                sender=message.receiver,
                receiver=message.sender,
                message_type=MessageType.RESPONSE,
                content=response_content,
                context=message.context
            )
            
            if message.receiver not in responses:
                responses[message.receiver] = []
            responses[message.receiver].append(response)
        
        return responses
    
    def request_collaboration(self, requester: str, collaborators: List[str], 
                            task: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
        """请求多个Agent协作"""
        logger.debug(f"\n【协作请求】{requester} 请求 {collaborators} 协作")
        logger.debug(f"任务: {task}\n")
        
        results = {}
        
        for collaborator in collaborators:
            message = Message(
                sender=requester,
                receiver=collaborator,
                message_type=MessageType.REQUEST,
                content=task,
                context=context or {}
            )
            
            self.send_message(message)
            
            # 处理消息
            if collaborator in self.agent_registry:
                agent = self.agent_registry[collaborator]
                response = agent.process(task, context or {})
                results[collaborator] = response
                logger.debug(f"✓ {collaborator} 完成任务\n")
        
        return results
    
    def detect_conflicts(self, outputs: Dict[str, str]) -> List[Dict[str, Any]]:
        """检测Agent输出之间的冲突"""
        conflicts = []
        
        agent_names = list(outputs.keys())
        for i, agent1 in enumerate(agent_names):
            for agent2 in agent_names[i+1:]:
                # 简单的冲突检测：检查是否有相互矛盾的关键词
                output1 = outputs[agent1].lower()
                output2 = outputs[agent2].lower()
                
                # 检查常见的冲突模式
                conflict_patterns = [
                    ("不应该", "应该"),
                    ("不能", "可以"),
                    ("不会", "会"),
                    ("反对", "支持"),
                ]
                
                for pattern1, pattern2 in conflict_patterns:
                    if pattern1 in output1 and pattern2 in output2:
                        conflict = {
                            "agent1": agent1,
                            "agent2": agent2,
                            "pattern": f"{pattern1} vs {pattern2}",
                            "timestamp": datetime.now().isoformat()
                        }
                        conflicts.append(conflict)
                        self.conflict_log.append(conflict)
        
        return conflicts
    
    def resolve_conflicts(self, conflicts: List[Dict[str, Any]], 
                         mediator: str) -> Dict[str, str]:
        """通过中介Agent解决冲突"""
        logger.debug(f"\n【冲突解决】由 {mediator} 调解\n")
        
        resolutions = {}
        
        for conflict in conflicts:
            agent1 = conflict["agent1"]
            agent2 = conflict["agent2"]
            
            mediation_request = f"""
            {agent1} 和 {agent2} 在以下方面存在冲突:
            {conflict['pattern']}
            
            请分析冲突原因，提出解决方案。
            """
            
            if mediator in self.agent_registry:
                mediator_agent = self.agent_registry[mediator]
                resolution = mediator_agent.process(mediation_request, {})
                resolutions[f"{agent1}_vs_{agent2}"] = resolution
                logger.debug(f"✓ 冲突已调解: {agent1} vs {agent2}\n")
        
        return resolutions
    
    def get_message_history(self, sender: Optional[str] = None, receiver: Optional[str] = None) -> List[Message]:
        """获取消息历史"""
        history = self.message_history
        
        if sender:
            history = [m for m in history if m.sender == sender]
        if receiver:
            history = [m for m in history if m.receiver == receiver]
        
        return history
    
    def print_communication_log(self):
        """打印通信日志"""
        logger.debug(f"\n{'='*70}")
        logger.debug("【通信日志】")
        logger.debug(f"{'='*70}\n")
        
        for msg in self.message_history:
            timestamp_str = msg.timestamp.strftime('%H:%M:%S') if msg.timestamp else 'N/A'
            logger.debug(f"[{timestamp_str}] {msg.sender} → {msg.receiver}")
            logger.debug(f"  类型: {msg.message_type.value}")
            logger.debug(f"  内容: {msg.content[:100]}...")
            logger.debug()
        
        if self.conflict_log:
            logger.debug(f"\n【冲突日志】")
            for conflict in self.conflict_log:
                logger.debug(f"  {conflict['agent1']} vs {conflict['agent2']}: {conflict['pattern']}")
    
    def clear_history(self):
        """清空历史"""
        self.message_queue.clear()
        self.message_history.clear()
        self.conflict_log.clear()
        logger.debug("✓ 通信历史已清空")


class AgentTeam:
    """Agent团队 - 管理多个Agent的协作"""
    
    def __init__(self, team_name: str):
        """初始化Agent团队"""
        self.team_name = team_name
        self.members: Dict[str, Any] = {}
        self.communication_hub = AgentCommunicationHub()
        self.team_context: Dict[str, Any] = {}
    
    def add_member(self, agent_name: str, agent_instance: Any):
        """添加团队成员"""
        self.members[agent_name] = agent_instance
        self.communication_hub.register_agent(agent_name, agent_instance)
    
    def set_team_context(self, **kwargs):
        """设置团队上下文"""
        self.team_context.update(kwargs)
        logger.debug(f"✓ 团队上下文已更新")
    
    def get_team_context(self) -> Dict[str, Any]:
        """获取团队上下文"""
        return self.team_context
    
    def execute_collaborative_task(self, task: str, lead_agent: str) -> Dict[str, Any]:
        """执行协作任务"""
        logger.debug(f"\n{'='*70}")
        logger.debug(f"【团队任务】{self.team_name}")
        logger.debug(f"【领导】{lead_agent}")
        logger.debug(f"【任务】{task}")
        logger.debug(f"{'='*70}\n")
        
        # 请求所有成员协作
        collaborators = [name for name in self.members.keys() if name != lead_agent]
        
        results: Dict[str, Any] = self.communication_hub.request_collaboration(
            requester=lead_agent,
            collaborators=collaborators,
            task=task,
            context=self.team_context
        )
        
        # 检测冲突
        conflicts = self.communication_hub.detect_conflicts(results)
        
        if conflicts:
            logger.debug(f"\n⚠ 检测到 {len(conflicts)} 个冲突")
            resolutions = self.communication_hub.resolve_conflicts(conflicts, lead_agent)
            results["resolutions"] = resolutions
        
        return results
    
    def print_team_status(self):
        """打印团队状态"""
        logger.debug(f"\n{'='*70}")
        logger.debug(f"【团队状态】{self.team_name}")
        logger.debug(f"{'='*70}")
        logger.debug(f"成员数: {len(self.members)}")
        logger.debug(f"成员: {', '.join(self.members.keys())}")
        logger.debug(f"上下文: {self.team_context}")
        logger.debug(f"{'='*70}\n")

