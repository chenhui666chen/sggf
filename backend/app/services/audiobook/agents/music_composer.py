"""
MusicComposer - 音乐设计师Agent（AI增强版）

核心职责：
1. 设计情绪音乐和主题音乐
2. 规划音乐的插入时机
3. 设计音乐与对话的混音关系
4. **AI生成音乐**（昆仑万维Mureka O1集成）
"""

import logging
import asyncio
import hashlib
import json
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parents[4]
AUDIO_LIBRARY_DIR = BACKEND_DIR / "data" / "audio_library"
DEFAULT_MUSIC_INDEX_PATH = AUDIO_LIBRARY_DIR / "music_index.json"

# 导入AI音乐生成器
try:
    from ..ai_music import AIMusicGenerator, MusicGenerationRequest, MusicStyle
    AI_MUSIC_AVAILABLE = True
except ImportError:
    logger.warning("⚠️ AI音乐生成模块未安装，将使用静态音乐库")
    AI_MUSIC_AVAILABLE = False


class MusicType(str, Enum):
    """音乐类型"""
    UNDERSCORE = "underscore"  # 背景音乐（对话下）
    THEME = "theme"  # 主题音乐
    TRANSITION = "transition"  # 转场音乐
    OPENING = "opening"  # 开场音乐
    ENDING = "ending"  # 结尾音乐


class MusicMood(str, Enum):
    """音乐情绪"""
    TENSE = "tense"  # 紧张
    JOYFUL = "joyful"  # 欢快
    SAD = "sad"  # 悲伤
    MYSTERIOUS = "mysterious"  # 神秘
    ROMANTIC = "romantic"  # 浪漫
    EPIC = "epic"  # 史诗
    PEACEFUL = "peaceful"  # 平静


@dataclass
class MusicCue:
    """音乐提示"""
    scene_id: str
    timestamp: float  # 触发时间（秒）
    music_type: MusicType
    mood: MusicMood
    description: str
    audio_file: str = ""  # 音乐文件路径
    volume: float = 0.2  # 音量（0-1）
    fade_in: float = 3.0  # 淡入时长（秒）
    fade_out: float = 5.0  # 淡出时长（秒）
    duration: float = 30.0  # 持续时长（秒）
    sync_with_dialogue: bool = True  # 对话时自动降低音量
    dialogue_volume_reduction: float = 0.5  # 对话时音量降低比例


class MusicComposer:
    """
    音乐设计师Agent（AI增强版）
    
    基于情节节奏和情感基调设计背景音乐
    支持AI动态生成（Mureka O1）+ 静态音乐库降级
    """
    
    def __init__(self, ai_generator: Optional[Any] = None, enable_ai: bool = True, index_path: Optional[str] = None):
        """
        Args:
            ai_generator: AI音乐生成器（可选，默认自动创建）
            enable_ai: 是否启用AI生成（默认True）
            index_path: 外部音乐索引文件路径（可选），默认使用 DEFAULT_MUSIC_INDEX_PATH
        """
        self.music_library = self._init_music_library()
        self.prompt_library = self._init_prompt_library()
        self.music_cues: List[MusicCue] = []
        self._chapter_total_duration: float = 600.0
        self._music_pool_cache: Dict[str, List[str]] = {}
        self.project_theme: Optional[str] = None
        self.project_style: Optional[str] = None
        
        self.index_path = Path(index_path) if index_path else DEFAULT_MUSIC_INDEX_PATH
        self.audio_library_dir = self.index_path.parent
        self._load_external_music_library()
        
        # AI音乐生成器
        self.enable_ai = enable_ai and AI_MUSIC_AVAILABLE
        if self.enable_ai:
            if ai_generator is None and AI_MUSIC_AVAILABLE:
                from ..ai_music import create_music_generator
                self.ai_generator = create_music_generator(enable_cache=True)
                logger.info("✅ AI音乐生成器已启用（Mureka O1）")
            else:
                self.ai_generator = ai_generator
        else:
            self.ai_generator = None
            logger.info("📚 使用静态音乐库模式")
    
    def apply_project_style(self, *, theme: Optional[str] = None, style: Optional[str] = None) -> None:
        self.project_theme = (theme or "").strip() or None
        self.project_style = (style or "").strip() or None

    def _apply_project_style_to_prompt(self, prompt: str) -> str:
        base = str(prompt or "").strip()
        if not base:
            return base
        parts = []
        if self.project_theme:
            parts.append(f"主题基调：{self.project_theme}")
        if self.project_style:
            parts.append(f"风格要求：{self.project_style}")
        if not parts:
            return base
        return f"{base}\n" + "；".join(parts)

    def _init_music_library(self) -> Dict[str, Dict[str, Any]]:
        """初始化音乐库（占位）"""
        return {
            # 紧张悬疑
            "suspense_strings": {"mood": "tense", "description": "悬疑感的低频弦乐", "file": "suspense_1.mp3"},
            "tension_build": {"mood": "tense", "description": "紧张感逐渐升高", "file": "tension_1.mp3"},
            
            # 欢快
            "cheerful_piano": {"mood": "joyful", "description": "欢快的钢琴曲", "file": "joy_1.mp3"},
            "upbeat_melody": {"mood": "joyful", "description": "明快的旋律", "file": "joy_2.mp3"},
            
            # 悲伤
            "sad_violin": {"mood": "sad", "description": "悲伤的小提琴", "file": "sad_1.mp3"},
            "melancholic": {"mood": "sad", "description": "忧郁的氛围音乐", "file": "sad_2.mp3"},
            
            # 神秘
            "mysterious_ambient": {"mood": "mysterious", "description": "神秘的环境音乐", "file": "mystery_1.mp3"},
            
            # 浪漫
            "romantic_strings": {"mood": "romantic", "description": "浪漫的弦乐", "file": "romance_1.mp3"},
            
            # 史诗
            "epic_orchestral": {"mood": "epic", "description": "史诗感的管弦乐", "file": "epic_1.mp3"},
            
            # 平静
            "peaceful_ambient": {"mood": "peaceful", "description": "平静的氛围音乐", "file": "peaceful_1.mp3"},
        }
    
    def _init_prompt_library(self) -> Dict[str, str]:
        """初始化AI音乐提示模版库
        
        使用精细设计的中文提示，覆盖开篇、日常、悬疑、战斗、离别、重逢、搞笑、仙侠、都市科幻等常见配乐场景。
        """
        return {
            # 1. 开篇主题曲（史诗感、带主旋律）
            "opening": "有声小说章节片头短配乐，时长8-12秒，纯音乐，无人声，不抢人声。开头以低频氛围或轻弦乐快速建立类型感，中段轻微渐强但不进入完整高潮，结尾可自然淡出，方便接入旁白正文。旋律简洁、音色克制、响度稳定，适合作为章节开场底色。",
            # 也可作为整部作品主主题
            "theme": "东方幻想长篇小说主线主题曲，电影级配乐风格，情绪从神秘氛围逐步递进至壮阔宏大，无压迫感；核心旋律清晰易记、线条流畅，以五声音阶为基础融入东方韵味，适配全书招牌BGM定位。配器：弦乐群（小提琴主旋律+大提琴和声铺垫）、合成器低频铺底、少量交响打击乐与辅助钢琴单音强化主旋律辨识度，节奏中速偏慢（约80 BPM）、4/4拍，适配世界观引入与主线相关的重要场景。",
            
            # 2. 日常温暖场景（轻松、治愈）
            "daily": "都市/校园日常场景背景音乐，情绪放松舒缓，带自然小确幸感，不抢对白（音量占比≤对白的60%）；旋律简单清新、重复度适中，以轻快音阶递进为主，无复杂转调。配器：原声吉他（指弹分解和弦+轻扫弦，温暖木质感，占比35%）、钢琴（单音+双音旋律，明亮柔和音色，占比30%）、轻微打击乐（卡林巴/沙锤/轻柔军鼓，无重音，占比20%），辅助小提琴长音弱铺底（细腻质感，占比15%）。节奏中等（100 BPM），4/4拍，织体通透稀疏，混响用房间混响（短混响避免模糊），动态平稳无突兀起伏，适配角色日常聊天、温馨互动、校园漫步等轻松场景，整体氛围治愈不拖沓。",
            
            # 3. 悬疑铺垫（低频紧张、渐进）
            "suspense": "悬疑场景铺垫配乐，整体色调偏暗，低频氛围感饱满，核心通过音色堆叠与节奏变化制造不安感，几乎无明显主旋律，不抢剧情张力。配器：弦乐低音组（大提琴/低音提琴，持续长音+轻微颤音，占比40%）、合成器（低频底噪+失真铺垫音，无刺耳高频，占比30%）、轻微环境音效（远处模糊风声/金属细微摩擦声，音量微弱，占比15%），辅助打击乐（木鱼/轻微鼓刷，间歇性点缀，占比15%）。节奏缓慢（70 BPM），4/4拍，动态层次：从弱起（织体极简，仅低频铺底）→ 每20秒增加一层音色堆叠（弦乐颤音渐密+合成器底噪增强）→ 结尾处轻微减弱留悬念，无突然爆发音；混响用暗色调房间混响（缩短反射时间），适配角色即将发现秘密、踏入危险区域前的铺垫场景，营造“暗流涌动”的紧张感。",
            
            # 4. 激烈战斗（高燃、鼓点强）
            "battle": "近身战斗/群战场景高燃配乐，情绪紧张激昂、爆发力拉满，适配战斗全程主BGM；旋律以短节奏型riff为主，简洁有力，无冗长段落。配器：重型打击乐（核心：底鼓+军鼓密集爆发，辅助：镲片/通鼓增强冲击力，占比45%）、电吉他（失真riff循环+高把位solo点缀高潮，占比30%）、重型弦乐（小提琴快速音阶+大提琴强力和弦，强化史诗感，占比20%），辅助合成器高频音效（短促脉冲音，增强穿透力，占比5%）。节奏快速（140 BPM），4/4拍，动态层次：开篇全乐器强奏入高潮→ 中间40-60秒短暂减弱（仅保留鼓点+轻吉他，留呼吸感）→ 60秒后迅速回归高燃高潮（全乐器齐奏，响度拉满但无失真过载）；混响用舞台混响（增强空间爆发力），适配刀剑交锋、群战厮杀、角色热血对抗场景，整体冲击力足且层次清晰。",
            
            # 5. 悲伤离别（克制、带弦乐独奏）
            "farewell": "角色告别/死亡场景配乐，情绪深沉克制，心酸内敛不煽情过度，不抢对白（音量占比≤对白的50%）；旋律线条清晰流畅，以缓慢下行音阶为主，无炫技段落，突出“安静伤感”氛围。配器：独奏小提琴（核心旋律，细腻颤音+弱音处理，占比40%）、钢琴（单音+分解和弦，柔和延音，占比35%）、大提琴弱铺底（长音和声，占比20%），辅助轻微竖琴点缀（偶尔单音，增强细腻感，占比5%）。节奏缓慢（65 BPM），4/4拍，织体稀疏通透，混响用小厅混响（温暖不空旷），动态平稳偏弱，高潮部分仅轻微渐强（不突破克制感），适配角色含泪告别、牺牲场景，营造“安静心酸、余韵悠长”的听觉效果。",
            
            # 6. 重逢与和解（温暖上扬）
            "reunion": "久别重逢/误会化解场景暖色调配乐，情绪先克制带轻微伤感，副段转为明亮充满希望，适配“心结打开”的治愈感；旋律有明显向上级进，转折自然不突兀。配器：钢琴（前半段单音叙事，后半段和弦提亮，占比30%）、弦乐群（小提琴+中提琴和声，前半段弱铺底，后半段渐强齐奏，占比35%）、柔和木管（长笛/单簧管，点缀副段主旋律，温暖通透，占比20%），辅助轻微打击乐（三角铁/轻碰铃，提亮情绪，占比15%）。节奏中慢速（80 BPM），4/4拍，动态层次：前40秒克制铺垫（织体简单，仅钢琴+弱弦乐）→ 40秒后副段转折（木管切入+弦乐渐强，旋律上扬）→ 结尾轻微渐弱留温暖余韵，混响用大厅混响（增强包容感），整体氛围治愈有力量，适配角色重逢拥抱、误会冰释的场景。",
            # 也可复用为浪漫情感场景
            "romantic": "久别重逢/误会化解场景暖色调配乐，情绪先克制带轻微伤感，副段转为明亮充满希望，适配“心结打开”的治愈系浪漫情感戏；旋律有明显向上级进，配器以钢琴、弦乐群与柔和木管为主，节奏中慢速（约80 BPM）、4/4拍，结尾轻微渐弱留温暖余韵。",
            
            # 7. 夜晚城市/科幻都市（冷色电子）
            "urban_sci_fi": "夜晚科幻都市/霓虹街景背景音乐，冷色调电子风格，带轻赛博朋克气质，不抢台词（音量占比≤对白的60%）；无复杂主旋律，以“律动氛围”为主，融入都市霓虹的疏离感与科技感。配器：电子合成器（核心：冷色pad铺底+轻微滤波扫频，占比40%）、律动bassline（低频饱满，中等力度，16分音符循环推进，占比25%）、简单电子鼓点（底鼓+hi-hat轻律动，无重音，占比20%），辅助轻微环境音效（远处霓虹电流声/模糊城市背景音，音量微弱，占比15%）。节奏中速（100 BPM），4/4拍，织体紧凑不杂乱，混响用电子混响（短反射+轻微延迟，增强科技感），动态平稳，适配角色独自走在夜色街头、内心独白、科幻都市夜景穿梭场景，整体冷感不压抑，贴合都市夜晚的静谧与科技感。",
            
            # 8. 古风仙侠世界观展示（空灵、国风）
            "xianxia": "古风仙侠世界观展示配乐，空灵缥缈带云雾感，国风韵味纯正，无明显节拍（自由速度，约60 BPM等效节奏），适配山川仙境、门派全景、宗门大典等宏大场景。配器：传统乐器为主（古筝：分解和弦+泛音，空灵质感，占比30%；笛子/竹笛：主旋律，悠扬婉转，占比25%；埙：低频铺垫，沧桑空灵，占比15%），辅助柔和弦乐群（长音铺底，无突兀旋律，占比20%）、轻微古琴点缀（单音强化国风底蕴，占比10%）。旋律以五声音阶为核心，线条舒展，无急促段落；动态层次：弱起（仅笛子+古筝泛音）→ 渐入（弦乐+埙铺底，织体渐丰富）→ 结尾渐弱（回归笛子+古琴，留空灵余韵），混响用大厅混响（长反射时间，增强仙境空间感），整体氛围宁静宏大，贴合仙侠世界的缥缈与庄严。",
            
            # 9. 紧张追逐/逃亡（节奏推进）
            "chase": "追逐/逃亡场景配乐，核心以节奏推进营造时间紧迫感，主旋律弱化，以重复节奏动机为主，适配角色狂奔、躲避追兵的紧张片段。配器：打击乐（核心：底鼓+军鼓快速循环，每30秒增加打击密度，占比40%）、合成器（高频脉冲音+低频bass强化节奏，占比30%）、弦乐（小提琴快速音阶+颤音，增强紧张感，占比20%），辅助电吉他短riff点缀（无冗长solo，占比10%）。节奏中快（130 BPM，可在1分钟后微加速至135 BPM强化紧迫感），4/4拍，动态层次：开篇节奏清晰切入（织体紧凑）→ 每20秒增加一层乐器（打击乐密度提升+弦乐渐强）→ 结尾处打击乐爆发后轻微收束（留悬念），混响用短舞台混响（避免模糊，增强节奏感），整体无拖沓段落，节奏鲜明不杂乱，适配高速追逐、紧急逃亡的剧情推进场景。",
            
            # 10. 诡异超自然（氛围噪音+不稳定和弦）
            "supernatural": "超自然/灵异场景配乐，核心通过不稳定和弦、音程冲突、环境噪音制造毛骨悚然、时空错位的诡异感，几乎无传统旋律，无明显节拍（自由速度，极慢）。配器：失真钢琴（不和谐和弦+刮键效果，占比30%）、弦乐特殊技法（拉弦边缘+泛音失真，无正常长音，占比25%）、环境噪音（呼吸声/模糊耳语/金属摩擦声/低频嗡鸣，音量控制在“可感知但不刺耳”，占比25%），辅助合成器（不和谐音程铺垫+轻微延迟失真，占比20%）。动态层次：弱起（仅低频嗡鸣+轻微呼吸声）→ 逐步加入不和谐音色（和弦冲突渐强+噪音密度提升）→ 中间穿插短暂“静音留白”强化诡异感→ 结尾以微弱失真音收束，无突兀爆发；混响用暗色调洞穴混响（长反射+轻微回声，增强阴森感），适配灵异事件、超自然现象、诡异空间探索场景，整体氛围压抑但不刺耳，贴合“毛骨悚然”的恐怖质感。",
            
            # 11. 热血觉醒/突破（逐层堆叠、最终爆发）
            "awakening": "主角觉醒/突破/领悟新力量瞬间配乐，情绪从低调压抑逐步叠加至极致爆发，给人“突破极限”的爽感，适配关键成长节点场景。配器：弦乐群（前期大提琴低频压抑和声，后期小提琴+中提琴高亢主旋律，占比35%）、人声合唱/合成合唱音色（庄严史诗感，高潮部分加入，占比20%）、交响打击乐（定音鼓/大鼓爆发+小军鼓节奏推进，占比25%）、电吉他（失真riff强化力量感，高潮solo点缀，占比15%）、钢琴（单音强化转折节点，占比5%）。节奏中快（120 BPM），4/4拍，动态层次：前40秒低调压抑（仅大提琴+弱打击乐，织体稀疏）→ 40-80秒逐层堆叠（弦乐渐强+合唱渐入+吉他切入）→ 80秒后关键节点爆发（全乐器齐奏，主旋律高亢上扬，响度拉满但无失真）→ 结尾短暂延续高潮后轻微收束，混响用大剧院混响（增强史诗空间感），整体力量感十足，爆发节点精准，贴合“突破极限”的热血情绪。",
            
            # 12. 轻松搞笑桥段（俏皮、节奏感强）
            "comic": "轻松搞笑/日常吐槽场景BGM，风格活泼俏皮，带轻微卡通感，适配角色闹笑话、斗嘴、生活趣事等轻松片段，不抢剧情笑点。旋律以短句重复为主，轻快跳跃，无复杂段落，加入轻微滑音/装饰音强化俏皮感。配器：木吉他（轻快扫弦+单音旋律，占比30%）、木琴/钟琴（明亮清脆，点缀主旋律，占比25%）、口风琴（柔和俏皮音色，辅助旋律，占比15%）、手鼓/沙锤（轻节奏推进，无重音，占比20%），辅助轻微木鱼/响板点缀（增强节奏感，占比10%）。节奏中速（110 BPM），4/4拍，织体通透轻快，动态平稳无大起伏，混响用小房间混响（短反射，增强亲切感），整体氛围欢乐不聒噪，适配喜剧向日常桥段，贴合“轻松解压”的情绪需求。",
            
            # 13. 宏大势力登场/全景展示（庄严、合唱感）
            "faction_intro": "强大势力/军团/宗门首次登场全景配乐，情绪庄严宏大，突出力量与威严，适配势力亮相、全景展示、盛典开场等场景。主旋律大气磅礴，以大调音阶为主，加入混合调式增强厚重感，线条舒展不拖沓。配器：弦乐群（小提琴+中提琴和声+大提琴低频支撑，占比35%）、铜管乐器（圆号/长号，强化庄严感，占比25%）、人声合唱/合成合唱音色（史诗感合唱，无歌词仅元音，高潮加入，占比20%）、交响打击乐（定音鼓/大鼓+钹，厚重节奏，占比20%）。节奏稳重（90 BPM），4/4拍，动态层次：前30秒庄严铺垫（弦乐+铜管渐入）→ 30秒后主旋律渐出（合唱切入+打击乐强化）→ 60秒后进入宏大高潮（全乐器齐奏，混响用大剧院混响增强空间威严感），整体响度均衡，高潮部分不刺耳，贴合势力登场的“震撼感”与“威严感”。",
            
            # 14. 尾声/片尾曲风（总结情绪、留有余韵）
            "ending": "小说章节尾声/整卷收尾配乐，情绪定位“卷帙未尽、故事仍在继续”，无纯悲伤或纯团圆感，带淡淡留恋与期待，适配章节结尾过渡场景。主旋律完整流畅，不过分抓耳，以舒缓线条为主，融入全书核心旋律片段（强化记忆点）。配器：钢琴（主旋律+分解和弦，温暖质感，占比35%）、弦乐群（长音和声铺垫，细腻柔和，占比30%）、轻微电子合成器（pad铺底，增强余韵，无突兀音色，占比20%）、辅助大提琴独奏点缀（强化深沉感，占比15%）。节奏中慢（80 BPM），4/4拍，动态层次：前40秒舒缓铺垫（钢琴+弱弦乐）→ 40-80秒主旋律完整呈现（织体渐丰富）→ 80秒后渐弱收尾（回归钢琴+轻微弦乐，留余韵），混响用大厅混响（长反射，增强留恋感），整体响度平稳，无突兀爆发，让听众在淡淡的回味中结束本章，适配“故事未完待续”的收尾需求。",
        }
    
    def _select_ai_prompt_for_scene(self, scene: Dict[str, Any]) -> str:
        """根据场景信息选择合适的AI音乐提示模版"""
        # 显式标注优先
        prompt_key = scene.get("music_prompt_key")
        if prompt_key and prompt_key in self.prompt_library:
            return self._apply_project_style_to_prompt(self.prompt_library[prompt_key])

        mood = self._normalize_music_mood(scene.get("mood", "peaceful"))
        description = scene.get("description", "")
        text = f"{description}{scene.get('tag', '')}"

        # 高优先级：特定剧情类型
        if any(kw in text for kw in ["战斗", "打斗", "厮杀", "爆炸"]):
            return self._apply_project_style_to_prompt(self.prompt_library.get("battle", ""))
        if any(kw in text for kw in ["追逐", "逃亡", "追击"]):
            return self._apply_project_style_to_prompt(self.prompt_library.get("chase", "") or self.prompt_library.get("battle", ""))
        if any(kw in text for kw in ["灵异", "超自然", "鬼", "幽灵", "亡灵", "诡异空间"]):
            return self._apply_project_style_to_prompt(self.prompt_library.get("supernatural", "") or self.prompt_library.get("suspense", ""))

        if any(kw in text for kw in ["悬疑", "调查", "谜团"]):
            return self._apply_project_style_to_prompt(self.prompt_library.get("suspense", ""))

        if any(kw in text for kw in ["离别", "诀别", "告别"]):
            return self._apply_project_style_to_prompt(self.prompt_library.get("farewell", ""))

        if any(kw in text for kw in ["重逢", "相认", "团聚", "和解"]):
            return self._apply_project_style_to_prompt(self.prompt_library.get("reunion", ""))

        if any(kw in text for kw in ["搞笑", "逗趣", "吐槽", "闹笑话"]):
            return self._apply_project_style_to_prompt(self.prompt_library.get("comic", ""))

        if any(kw in text for kw in ["仙侠", "修仙", "飞升", "渡劫"]):
            return self._apply_project_style_to_prompt(self.prompt_library.get("xianxia", ""))

        if any(kw in text for kw in ["机甲", "星舰", "未来", "都市", "科幻", "霓虹"]):
            return self._apply_project_style_to_prompt(self.prompt_library.get("urban_sci_fi", ""))

        if any(kw in text for kw in ["觉醒", "突破", "领悟", "爆发"]):
            return self._apply_project_style_to_prompt(self.prompt_library.get("awakening", ""))

        if any(kw in text for kw in ["势力", "军团", "宗门", "登场", "盛典", "全景展示"]):
            return self._apply_project_style_to_prompt(self.prompt_library.get("faction_intro", ""))

        if any(kw in text for kw in ["尾声", "片尾", "终章", "收尾", "完结"]):
            return self._apply_project_style_to_prompt(self.prompt_library.get("ending", ""))

        # 默认：根据情绪选择一个通用模版
        if mood in ["tense", "mysterious"]:
            return self._apply_project_style_to_prompt(self.prompt_library.get("suspense", ""))
        if mood == "epic":
            return self._apply_project_style_to_prompt(self.prompt_library.get("battle", ""))
        if mood == "joyful":
            return self._apply_project_style_to_prompt(self.prompt_library.get("comic", ""))
        if mood == "romantic":
            return self._apply_project_style_to_prompt(self.prompt_library.get("romantic", ""))
        if mood == "sad":
            return self._apply_project_style_to_prompt(self.prompt_library.get("farewell", ""))
        if mood == "peaceful":
            return self._apply_project_style_to_prompt(self.prompt_library.get("daily", ""))

        return ""

    def _normalize_music_mood(self, mood: Any) -> str:
        """将剧本情绪归一到 MusicMood 枚举，避免扩展情绪标签中断配乐设计。"""
        normalized = str(mood or "").strip().lower()
        alias_map = {
            "angry": "tense",
            "fearful": "tense",
            "nervous": "tense",
            "shout": "tense",
            "surprised": "tense",
            "suspense": "tense",
            "excited": "joyful",
            "happy": "joyful",
            "calm": "peaceful",
            "neutral": "peaceful",
            "tender": "romantic",
            "solemn": "epic",
        }
        normalized = alias_map.get(normalized, normalized)
        valid_moods = {item.value for item in MusicMood}
        return normalized if normalized in valid_moods else "peaceful"

    def _music_file_exists(self, file_ref: str) -> bool:
        """验证音乐文件引用是否可解析到本地素材。"""
        raw = str(file_ref or "").strip()
        if not raw:
            return False
        path = Path(raw)
        if path.is_absolute():
            return path.exists()
        return (self.audio_library_dir / path).exists()

    def _load_external_music_library(self) -> None:
        """从外部索引加载音乐库

        支持的索引格式（与 sound_effects_index.json 对齐）：
        - JSON 数组：[ {"id": ..., "mood": ..., "file_path": ..., ...}, ... ]
        """
        index_path = self.index_path
        if not index_path or not index_path.exists():
            return

        try:
            with index_path.open("r", encoding="utf-8") as f:
                data = json.load(f)

            if isinstance(data, dict):
                records = list(data.values())
            else:
                records = list(data)

            loaded = 0
            bucket_groups: Dict[str, List[str]] = {}

            for item in records:
                entry_id = item.get("id") or item.get("name")
                if not entry_id:
                    continue

                mood = self._normalize_music_mood(item.get("mood") or "peaceful")
                file_path = item.get("file_path") or item.get("file")
                description = item.get("description") or item.get("prompt") or item.get("name") or entry_id
                bucket = item.get("bucket") or ""
                music_type = item.get("type") or item.get("music_type") or ""

                if not file_path:
                    continue

                if not self._music_file_exists(file_path):
                    logger.warning("⚠️ 音乐索引条目文件不存在: %s", file_path)
                    continue

                existing = self.music_library.get(entry_id)
                if existing and self._music_file_exists(existing.get("file", "")):
                    continue

                self.music_library[entry_id] = {
                    "mood": mood,
                    "description": str(description)[:200],
                    "file": file_path,
                    "source": item.get("source", "index"),
                }
                loaded += 1

                if bucket and file_path:
                    bucket_groups.setdefault(bucket, []).append(file_path)

            if bucket_groups:
                for bucket_key, paths in bucket_groups.items():
                    cache_key_parts = bucket_key.split(":")
                    if len(cache_key_parts) >= 2:
                        mood_part = cache_key_parts[-1]
                        duration = 20
                        pool_size = len(paths)
                        cache_key = f"{bucket_key}|{mood_part}|{duration}|{pool_size}"
                        if cache_key not in self._music_pool_cache:
                            self._music_pool_cache[cache_key] = paths

            if loaded:
                logger.info(f"🎵 从外部音乐索引加载 %d 个条目: %s", loaded, index_path)
        except Exception as e:
            logger.warning(f"⚠️ 加载音乐索引失败: {e}")
    
    async def design_music(
        self,
        chapter_structure: Dict[str, Any],
        emotion_curve: Optional[List[Dict[str, Any]]] = None,
        skip_intro_outro: bool = False,  # 新增参数：是否跳过开场/结尾音乐
        allow_asset_generation: bool = True,
    ) -> List[MusicCue]:
        """
        设计音乐方案
        
        Args:
            chapter_structure: 章节结构
                {
                    "total_duration": 1200.0,  # 总时长（秒）
                    "scenes": [
                        {
                            "scene_id": "scene_1",
                            "start_time": 0.0,
                            "duration": 300.0,
                            "mood": "tense",
                            "description": "开场悬疑场景"
                        }
                    ]
                }
            emotion_curve: 情绪曲线（可选）
            skip_intro_outro: 低密度时跳过开场/结尾音乐，只保留关键场景配乐
            allow_asset_generation: 是否允许生成/补全配乐素材（AI或素材池）
        
        Returns:
            音乐提示列表
        """
        logger.info("🎼 设计音乐方案...")
        
        music_cues = []
        self._chapter_total_duration = float(chapter_structure.get("total_duration") or 0.0) or 600.0

        chapter_id = chapter_structure.get("chapter_id")
        audiobook_project_id = chapter_structure.get("audiobook_project_id")
        
        # 1. 开场音乐（低密度时可跳过）
        if not skip_intro_outro:
            opening_cue = await self._create_opening_music_async(
                chapter_structure,
                allow_asset_generation=allow_asset_generation,
            )
            if opening_cue:
                music_cues.append(opening_cue)
        
        # 2. 场景音乐
        for scene in chapter_structure.get("scenes", []):
            scene_with_ids = dict(scene or {})
            if chapter_id is not None:
                scene_with_ids["chapter_id"] = chapter_id
            if audiobook_project_id is not None:
                scene_with_ids["audiobook_project_id"] = audiobook_project_id

            scene_cue = await self._design_scene_music(
                scene_with_ids,
                allow_asset_generation=allow_asset_generation,
            )
            if scene_cue:
                music_cues.append(scene_cue)
        
        # 3. 结尾音乐（低密度时可跳过）
        if not skip_intro_outro:
            total_duration = chapter_structure.get("total_duration", 0)
            ending_cue = await self._create_ending_music_async(
                float(total_duration or 0.0),
                allow_asset_generation=allow_asset_generation,
            )
            if ending_cue:
                music_cues.append(ending_cue)
        
        self.music_cues = music_cues
        logger.info(f"   ✅ 设计完成: {len(music_cues)} 个音乐提示")
        
        return music_cues

    async def _create_opening_music_async(
        self,
        chapter_structure: Dict[str, Any],
        allow_asset_generation: bool = True,
    ) -> Optional[MusicCue]:
        """创建开场音乐（优先AI，降级静态库）。"""
        overall_mood = self._normalize_music_mood(chapter_structure.get("overall_mood", "mysterious"))

        if allow_asset_generation and self.enable_ai and self.ai_generator:
            try:
                bucket = f"opening:{overall_mood}"
                prompt = self.prompt_library.get("opening", "") or f"{overall_mood}氛围的开场主题音乐，纯音乐，无人声"
                prompt = self._apply_project_style_to_prompt(prompt)
                result = await self.ai_generator.generate_for_bucket(
                    prompt=prompt,
                    mood=str(overall_mood),
                    duration=15,
                    variant=0,
                    bucket=bucket,
                )
                if result.success and result.audio_file_path:
                    return MusicCue(
                        scene_id="opening",
                        timestamp=0.0,
                        music_type=MusicType.OPENING,
                        mood=MusicMood(overall_mood),
                        description="开场音乐（AI）",
                        audio_file=result.audio_file_path,
                        volume=0.3,
                        fade_in=2000 / 1000.0,
                        fade_out=4000 / 1000.0,
                        duration=15.0,
                        sync_with_dialogue=True,
                    )
            except Exception as e:
                logger.warning(f"⚠️ 开场音乐AI生成失败，降级到静态库: {e}")

        return self._create_opening_music(chapter_structure)

    async def _create_ending_music_async(
        self,
        chapter_duration: float,
        allow_asset_generation: bool = True,
    ) -> Optional[MusicCue]:
        """创建结尾音乐（优先AI，降级静态库）。"""
        if allow_asset_generation and self.enable_ai and self.ai_generator:
            try:
                bucket = "ending:peaceful"
                prompt = self.prompt_library.get("ending", "") or "章节尾声/收尾配乐，留白与余韵，纯音乐，无人声"
                prompt = self._apply_project_style_to_prompt(prompt)
                result = await self.ai_generator.generate_for_bucket(
                    prompt=prompt,
                    mood="peaceful",
                    duration=20,
                    variant=0,
                    bucket=bucket,
                )
                if result.success and result.audio_file_path:
                    return MusicCue(
                        scene_id="ending",
                        timestamp=max(0.0, float(chapter_duration or 0.0) - 20.0),
                        music_type=MusicType.ENDING,
                        mood=MusicMood.PEACEFUL,
                        description="结尾音乐（AI）",
                        audio_file=result.audio_file_path,
                        volume=0.25,
                        fade_in=3.0,
                        fade_out=5.0,
                        duration=20.0,
                        sync_with_dialogue=False,
                    )
            except Exception as e:
                logger.warning(f"⚠️ 结尾音乐AI生成失败，降级到静态库: {e}")

        return self._create_ending_music(chapter_duration)
    
    def _create_opening_music(
        self,
        chapter_structure: Dict[str, Any]
    ) -> Optional[MusicCue]:
        """创建开场音乐"""
        # 根据整体基调选择开场音乐
        overall_mood = self._normalize_music_mood(chapter_structure.get("overall_mood", "mysterious"))
        
        music_info = self._match_music(overall_mood, seed="opening")
        
        cue = MusicCue(
            scene_id="opening",
            timestamp=0.0,
            music_type=MusicType.OPENING,
            mood=MusicMood(overall_mood),
            description=f"开场音乐 - {music_info['description']}",
            audio_file=music_info["file"],
            volume=0.3,
            fade_in=2.0,
            fade_out=4.0,
            duration=15.0,
            sync_with_dialogue=True
        )
        
        return cue
    
    async def _design_scene_music(
        self,
        scene: Dict[str, Any],
        allow_asset_generation: bool = True,
    ) -> Optional[MusicCue]:
        """设计场景音乐（AI增强）"""
        mood = self._normalize_music_mood(scene.get("mood", "peaceful"))
        start_time = scene.get("start_time", 0.0)
        duration = scene.get("duration", 60.0)
        scene_description = scene.get("description", "场景")
        
        # 选择“可复用桶”的基准风格提示词：避免每个场景都拼接细节，导致缓存无法命中
        bucket_prompt = self._select_ai_prompt_for_scene(scene) or ""
        if not bucket_prompt:
            bucket_prompt = f"{mood}氛围的影视配乐风格背景音乐，纯音乐，无人声，适合长篇小说朗读作底色"
        bucket_prompt = self._apply_project_style_to_prompt(bucket_prompt)
            
        # 只为关键场景（高潮、转折）添加音乐
        is_key_scene = scene.get("is_climax", False) or scene.get("is_turning_point", False)
            
        if not is_key_scene and mood == "peaceful":
            return None  # 平静场景不一定需要音乐
            
        # 尝试AI生成（优先）
        if allow_asset_generation and self.enable_ai and self.ai_generator:
            try:
                return await self._generate_scene_music_with_ai(
                    scene=scene,
                    bucket_prompt=bucket_prompt,
                    mood=mood,
                    start_time=start_time,
                    duration=min(duration, 120.0)
                )
            except Exception as e:
                logger.warning(f"⚠️ AI生成音乐失败，降级到静态库: {e}")
            
        # 降级到静态音乐库
        project_id = str(scene.get("audiobook_project_id") or "")
        chapter_id = str(scene.get("chapter_id") or "")
        scene_id = str(scene.get("scene_id") or "scene")
        seed = f"{project_id}|{chapter_id}|{scene_id}|{start_time}|{mood}"
        music_info = self._match_music(mood, seed=seed)
            
        cue = MusicCue(
            scene_id=scene_id,
            timestamp=start_time,
            music_type=MusicType.UNDERSCORE,
            mood=MusicMood(mood),
            description=f"场景音乐 - {music_info['description']}",
            audio_file=music_info["file"],
            volume=0.15,  # 背景音乐音量更低
            fade_in=3.0,
            fade_out=3.0,
            duration=min(duration, 120.0),  # 最長2分钟
            sync_with_dialogue=True,
            dialogue_volume_reduction=0.6  # 对话时降低40%
        )
        
        return cue
    
    def _create_ending_music(
        self,
        chapter_duration: float
    ) -> Optional[MusicCue]:
        """创建结尾音乐"""
        cue = MusicCue(
            scene_id="ending",
            timestamp=max(0, chapter_duration - 20.0),  # 最后20秒
            music_type=MusicType.ENDING,
            mood=MusicMood.PEACEFUL,
            description="结尾音乐",
            audio_file="peaceful_ambient.mp3",
            volume=0.25,
            fade_in=3.0,
            fade_out=5.0,
            duration=20.0,
            sync_with_dialogue=False
        )
        
        return cue
    
    def _match_music(self, mood: str, seed: str = "") -> Dict[str, Any]:
        """匹配音乐库，基于 seed 稳定随机选取以增加变化"""
        matches = [
            info for info in self.music_library.values()
            if info.get("mood") == mood
        ]
        if matches:
            if len(matches) == 1:
                return matches[0]
            chosen_index = self._stable_choice_index(seed or mood, len(matches))
            return matches[chosen_index]

        return {
            "mood": "peaceful",
            "description": "平静的氛围音乐",
            "file": "peaceful_ambient.mp3"
        }
    
    async def create_theme_music(
        self,
        character_name: str,
        character_traits: Dict[str, Any]
    ) -> MusicCue:
        """
        为角色创建主题音乐（AI增强）
        
        Args:
            character_name: 角色名
            character_traits: 角色特质
        
        Returns:
            主题音乐提示
        """
        logger.info(f"🎵 为角色 {character_name} 创建主题音乐...")
        
        # 根据角色特质选择音乐情绪
        personality = character_traits.get("personality", "")
        
        if "神秘" in personality:
            mood = MusicMood.MYSTERIOUS
        elif "温柔" in personality or "浪漫" in personality:
            mood = MusicMood.ROMANTIC
        elif "英勇" in personality or "强大" in personality:
            mood = MusicMood.EPIC
        elif "活泼" in personality:
            mood = MusicMood.JOYFUL
        else:
            mood = MusicMood.PEACEFUL
        
        # 尝试AI生成
        if self.enable_ai and self.ai_generator:
            try:
                result = await self.ai_generator.generate_theme_music(
                    character_name=character_name,
                    personality=personality,
                    duration=30
                )
                
                if result.success:
                    return MusicCue(
                        scene_id=f"theme_{character_name}",
                        timestamp=0.0,
                        music_type=MusicType.THEME,
                        mood=mood,
                        description=f"{character_name}的主题音乐（AI生成）",
                        audio_file=result.audio_file_path,
                        volume=0.2,
                        fade_in=2.0,
                        fade_out=3.0,
                        duration=30.0,
                        sync_with_dialogue=True
                    )
            except Exception as e:
                logger.warning(f"⚠️ AI生成主题音乐失败: {e}")
        
        # 降级到静态库
        music_info = self._match_music(mood.value, seed=f"theme_{character_name}")
        
        cue = MusicCue(
            scene_id=f"theme_{character_name}",
            timestamp=0.0,
            music_type=MusicType.THEME,
            mood=mood,
            description=f"{character_name}的主题音乐",
            audio_file=music_info["file"],
            volume=0.2,
            fade_in=2.0,
            fade_out=3.0,
            duration=30.0,
            sync_with_dialogue=True
        )
        
        return cue
    
    def optimize_music_placement(
        self,
        max_music_coverage: float = 0.4
    ) -> List[MusicCue]:
        """
        优化音乐布局（避免音乐过多）
        
        Args:
            max_music_coverage: 最大音乐覆盖率（0-1）
        
        Returns:
            优化后的音乐列表
        """
        logger.info("🔧 优化音乐布局...")
        
        if not self.music_cues:
            return []
        
        # 计算当前音乐覆盖率
        total_duration = sum(cue.duration for cue in self.music_cues)
        
        # 如果覆盖率过高，移除一些非关键音乐
        optimized_cues = []
        
        # 保留开场、结尾和主题音乐
        for cue in self.music_cues:
            if cue.music_type in [MusicType.OPENING, MusicType.ENDING, MusicType.THEME]:
                optimized_cues.append(cue)
        
        # 根据情绪优先级添加场景音乐
        mood_priority = {
            MusicMood.TENSE: 1,
            MusicMood.EPIC: 2,
            MusicMood.SAD: 3,
            MusicMood.MYSTERIOUS: 4,
            MusicMood.JOYFUL: 5,
            MusicMood.ROMANTIC: 5,
            MusicMood.PEACEFUL: 6
        }
        
        scene_cues = [c for c in self.music_cues if c.music_type == MusicType.UNDERSCORE]
        scene_cues.sort(key=lambda x: (mood_priority.get(x.mood, 10), x.timestamp))
        
        # 逐个添加，直到达到覆盖率上限
        current_coverage = sum(c.duration for c in optimized_cues)
        max_allowed_duration = max_music_coverage * float(getattr(self, "_chapter_total_duration", 600.0) or 600.0)
        
        for cue in scene_cues:
            if self._overlaps_existing_music(cue, optimized_cues, min_gap=5.0):
                logger.debug("   跳过重叠配乐: %s at %.1fs", cue.description, cue.timestamp)
                continue
            if current_coverage + cue.duration <= max_allowed_duration:
                optimized_cues.append(cue)
                current_coverage += cue.duration
        
        logger.info(f"   ✅ 优化完成: {len(self.music_cues)} → {len(optimized_cues)} 个音乐提示")
        
        self.music_cues = optimized_cues
        return optimized_cues

    def _overlaps_existing_music(
        self,
        cue: MusicCue,
        existing_cues: List[MusicCue],
        *,
        min_gap: float = 5.0,
    ) -> bool:
        """避免多个 underscore 在同一时间段叠加，保留优先级更高的先入选配乐。"""
        if cue.music_type != MusicType.UNDERSCORE:
            return False
        cue_start = float(cue.timestamp or 0.0)
        cue_end = cue_start + max(0.0, float(cue.duration or 0.0))
        for existing in existing_cues:
            if existing.music_type != MusicType.UNDERSCORE:
                continue
            existing_start = float(existing.timestamp or 0.0)
            existing_end = existing_start + max(0.0, float(existing.duration or 0.0))
            if cue_start < existing_end + min_gap and cue_end + min_gap > existing_start:
                return True
        return False
    
    def export_music_timeline(self) -> Dict[str, Any]:
        """导出音乐时间线（用于混音）"""
        timeline = {
            "total_cues": len(self.music_cues),
            "cues_by_type": self._count_by_type(),
            "cues_by_mood": self._count_by_mood(),
            "timeline": [
                {
                    "scene_id": cue.scene_id,
                    "timestamp": cue.timestamp,
                    "type": cue.music_type.value,
                    "mood": cue.mood.value,
                    "description": cue.description,
                    "file": cue.audio_file,
                    "volume": cue.volume,
                    "duration": cue.duration,
                    "fade_in": cue.fade_in,
                    "fade_out": cue.fade_out,
                    "sync_with_dialogue": cue.sync_with_dialogue,
                    "dialogue_volume_reduction": cue.dialogue_volume_reduction,
                }
                for cue in sorted(self.music_cues, key=lambda x: x.timestamp)
            ]
        }
        
        return timeline
    
    def _count_by_type(self) -> Dict[str, int]:
        """按类型统计"""
        counts = {}
        for cue in self.music_cues:
            t = cue.music_type.value
            counts[t] = counts.get(t, 0) + 1
        return counts
    
    def _count_by_mood(self) -> Dict[str, int]:
        """按情绪统计"""
        counts = {}
        for cue in self.music_cues:
            m = cue.mood.value
            counts[m] = counts.get(m, 0) + 1
        return counts
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息（增强AI统计）"""
        stats = {
            "total_cues": len(self.music_cues),
            "cues_by_type": self._count_by_type(),
            "cues_by_mood": self._count_by_mood(),
            "music_library_size": len(self.music_library)
        }
        
        # AI生成器统计
        if self.enable_ai and self.ai_generator:
            ai_stats = self.ai_generator.get_statistics()
            stats["ai_music_stats"] = ai_stats
        
        return stats

    def purge_low_quality_assets(self, min_score: float = 40.0, dry_run: bool = False) -> Dict[str, Any]:
        """从索引和磁盘删除低质音乐素材。"""
        return self._purge_assets(
            predicate=lambda rec: self._is_low_quality_record(rec, min_score),
            dry_run=dry_run,
            label="低质素材",
        )

    def _is_low_quality_record(self, rec: Dict[str, Any], min_score: float) -> bool:
        """仅清理已有明确质量结论的低质条目，避免误删历史无质量元数据素材。"""
        if rec.get("quality_status") == "rejected":
            return True
        if "quality_score" not in rec:
            return False
        try:
            return float(rec.get("quality_score")) < min_score
        except (TypeError, ValueError):
            return False

    def purge_orphan_entries(self, dry_run: bool = False) -> Dict[str, Any]:
        """清理索引中文件已不存在的孤立条目。"""
        return self._purge_assets(
            predicate=lambda rec: not self._music_file_exists(
                rec.get("file_path") or rec.get("file", "")
            ),
            dry_run=dry_run,
            label="孤立条目",
        )

    def _purge_assets(
        self,
        predicate,
        dry_run: bool = False,
        label: str = "",
    ) -> Dict[str, Any]:
        """通用素材清理：按 predicate 筛选索引条目并删除索引记录 + 磁盘文件。"""
        index_path = self.index_path
        if not index_path or not index_path.exists():
            return {"purged_count": 0, "freed_bytes": 0, "details": []}

        try:
            with index_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                records = list(data.values())
            else:
                records = list(data)

            to_purge = [r for r in records if predicate(r)]
            to_keep = [r for r in records if not predicate(r)]

            details = []
            freed_bytes = 0
            purged_count = 0

            for rec in to_purge:
                entry_id = rec.get("id", "?")
                file_ref = rec.get("file_path") or rec.get("file", "")
                resolved = self._resolve_deletable_asset_path(file_ref)
                file_size = 0
                if resolved and resolved.exists():
                    file_size = resolved.stat().st_size
                    if not dry_run:
                        try:
                            resolved.unlink()
                        except OSError:
                            pass
                freed_bytes += file_size
                purged_count += 1
                details.append({"id": entry_id, "file": file_ref, "size": file_size})

                self.music_library.pop(entry_id, None)

            if not dry_run and purged_count > 0:
                with index_path.open("w", encoding="utf-8") as f:
                    json.dump(to_keep, f, ensure_ascii=False, indent=2)

            logger.info(
                "🗑️ %s清理%s: 删除 %d 条, 释放 %d 字节%s",
                label,
                "（预演）" if dry_run else "",
                purged_count,
                freed_bytes,
                "" if dry_run else f", 索引剩余 {len(to_keep)} 条",
            )
            return {"purged_count": purged_count, "freed_bytes": freed_bytes, "details": details}
        except Exception as e:
            logger.warning("⚠️ 素材清理失败: %s", e)
            return {"purged_count": 0, "freed_bytes": 0, "details": [], "error": str(e)}

    def _resolve_deletable_asset_path(self, file_ref: str) -> Optional[Path]:
        """仅允许清理当前音乐索引素材库目录内的文件。"""
        raw = str(file_ref or "").strip()
        if not raw:
            return None
        base_dir = self.audio_library_dir.resolve()
        path = Path(raw)
        candidate = path if path.is_absolute() else self.audio_library_dir / path
        try:
            resolved = candidate.resolve()
            resolved.relative_to(base_dir)
        except (OSError, ValueError):
            return None
        return resolved

    def _stable_choice_index(self, seed: str, pool_size: int) -> int:
        if pool_size <= 1:
            return 0
        digest = hashlib.md5(seed.encode("utf-8")).hexdigest()
        return int(digest[:8], 16) % pool_size

    def _get_cached_music_pool(
        self,
        *,
        bucket: str,
        mood: str,
        duration: int,
        pool_size: int,
    ) -> Optional[List[str]]:
        """返回满足请求数量的预热音乐池，兼容索引中已有更多变体的情况。"""
        cache_key = f"{bucket}|{mood}|{duration}|{pool_size}"
        cached = self._music_pool_cache.get(cache_key)
        if cached:
            return cached

        prefix = f"{bucket}|{mood}|{duration}|"
        for existing_key, paths in self._music_pool_cache.items():
            if existing_key.startswith(prefix) and len(paths) >= pool_size:
                selected = paths[:pool_size]
                self._music_pool_cache[cache_key] = selected
                return selected
        return None

    async def _ensure_music_pool(
        self,
        *,
        bucket: str,
        mood: str,
        prompt: str,
        duration: int,
        pool_size: int = 5,
    ) -> List[str]:
        """确保音乐池存在（每个bucket生成/命中多个变体），返回可用的相对路径列表。"""
        if not (self.enable_ai and self.ai_generator):
            return []

        cache_key = f"{bucket}|{mood}|{duration}|{pool_size}"
        cached = self._get_cached_music_pool(
            bucket=bucket,
            mood=mood,
            duration=duration,
            pool_size=pool_size,
        )
        if cached:
            return cached

        tasks = [
            self.ai_generator.generate_for_bucket(
                prompt=prompt,
                mood=mood,
                duration=duration,
                variant=i,
                bucket=bucket,
            )
            for i in range(pool_size)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        file_paths: List[str] = []
        for r in results:
            if isinstance(r, Exception):
                continue
            if getattr(r, "success", False) and getattr(r, "audio_file_path", ""):
                file_paths.append(r.audio_file_path)

        seen = set()
        deduped: List[str] = []
        for p in file_paths:
            if p in seen:
                continue
            seen.add(p)
            deduped.append(p)

        if deduped:
            self._music_pool_cache[cache_key] = deduped
        return deduped
    
    async def _generate_scene_music_with_ai(
        self,
        scene: Dict[str, Any],
        bucket_prompt: str,
        mood: str,
        start_time: float,
        duration: float
    ) -> MusicCue:
        """使用AI生成场景音乐（音乐池 + 可复现随机组合）"""
        # 固定池内片段时长，提升跨场景复用与缓存命中（避免因场景时长波动导致反复建池）
        pool_duration = 20
        pool_bucket = f"underscore:{mood}"

        pool = await self._ensure_music_pool(
            bucket=pool_bucket,
            mood=mood,
            prompt=bucket_prompt,
            duration=pool_duration,
            pool_size=5,
        )
        if not pool:
            raise RuntimeError("音乐池为空")

        project_id = str(scene.get("audiobook_project_id") or "")
        chapter_id = str(scene.get("chapter_id") or "")
        scene_id = str(scene.get("scene_id") or "scene")
        ts = str(scene.get("start_time") or start_time)
        seed = f"{project_id}|{chapter_id}|{scene_id}|{ts}|{mood}|{pool_bucket}"
        picked_index = self._stable_choice_index(seed, len(pool))
        picked_file = pool[picked_index]

        logger.info(f"   ✅ 音乐池选曲: bucket={pool_bucket} picked={picked_index+1}/{len(pool)}")

        return MusicCue(
            scene_id=scene_id,
            timestamp=start_time,
            music_type=MusicType.UNDERSCORE,
            mood=MusicMood(mood),
            description=f"场景音乐（AI池） - {scene.get('description', '场景')}",
            audio_file=picked_file,
            volume=0.15,
            fade_in=3.0,
            fade_out=3.0,
            duration=min(duration, 120.0),
            sync_with_dialogue=True,
            dialogue_volume_reduction=0.6
        )
