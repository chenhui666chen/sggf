"""
剧本转化 Mixin

包含 _transform_to_script 和 _transform_paragraph 方法
"""
import json
import re
import logging
from typing import List, Dict, Any, Optional, Callable

from ._dataclasses import ScriptSegment

logger = logging.getLogger(__name__)


class TransformMixin:
    """剧本转化方法"""
    
    async def _transform_to_script(
        self,
        content: str,
        character_list: List[str],
        analysis: Dict[str, Any],
        audio_adaptation_brief: str = "",
        progress_callback: Optional[Callable[[int, int], None]] = None,
        character_profiles: Optional[List[Dict[str, Any]]] = None,
    ) -> List[ScriptSegment]:
        """
        剧本转化：听觉化改写
        
        核心改编策略：
        1. 心理活动 → 独白/音效暗示
        2. 环境描写 → 音效标注
        3. 复杂描述 → 简化为听觉友好的语言
        4. 对话优化 → 删除拗口词汇
        """
        
        # 分段处理（每次处理500-1000字）
        paragraphs = content.split('\n')
        # 过滤空段落
        paragraphs = [p for p in paragraphs if p.strip() and len(p) >= 10]
        
        # 合并短段落，减少LLM调用次数
        merged_paragraphs = []
        current_batch = []
        current_length = 0
        
        for para in paragraphs:
            if current_length + len(para) > 6000:  # 智能分批：每批次最多6000字，保持较大上下文窗口
                if current_batch:
                    merged_paragraphs.append('\n'.join(current_batch))
                current_batch = [para]
                current_length = len(para)
            else:
                current_batch.append(para)
                current_length += len(para)
        
        if current_batch:
            merged_paragraphs.append('\n'.join(current_batch))
        
        total_paras = len(merged_paragraphs)
        logger.info(f"📝 合并后 {total_paras} 个批次（原 {len(paragraphs)} 段），总长度: {len(content)} 字")
        
        all_segments = []
        
        for idx, para in enumerate(merged_paragraphs, 1):
            logger.info(f"   ⏳ [{idx}/{total_paras}] 处理段落 ({len(para)}字)...")
            
            try:
                segments = await self._transform_paragraph(
                    para,
                    character_list,
                    analysis,
                    audio_adaptation_brief=audio_adaptation_brief,
                    character_profiles=character_profiles,
                )
                all_segments.extend(segments)
                logger.info(f"   ✅ [{idx}/{total_paras}] 完成，生成 {len(segments)} 个片段")
            except Exception as e:
                logger.error(f"   ❌ [{idx}/{total_paras}] 失败: {e}")
                # 继续处理下一段，不中断整个流程
                pass

            if progress_callback:
                progress_callback(idx, total_paras)
        
        logger.info(f"✅ 全部段落处理完成，总计 {len(all_segments)} 个剧本片段")
        
        # 🆕 根据用户偏好：不在这里强制合并短片段，而是尽量在编剧阶段控制片段长度
        logger.info(f"📝 保持原始剧本片段数量：{len(all_segments)}（不做短片段自动合并）")
        
        # 可选：如启用语义验证，仅用于日志提示，不再强制修改结构
        if self.strategy and getattr(self.strategy, 'semantic_validation', False):
            all_segments = self._validate_semantic_integrity(all_segments)
        
        return all_segments
    
    async def _transform_paragraph(
        self,
        paragraph: str,
        character_list: List[str],
        analysis: Dict[str, Any],
        audio_adaptation_brief: str = "",
        character_profiles: Optional[List[Dict[str, Any]]] = None,
    ) -> List[ScriptSegment]:
        """转化单个段落
        
        Args:
            character_profiles: 🆕 完整角色档案（用于对话归属和角色身份识别）
        """
        
        model_name = (getattr(self, "tts_model", None) or "qwen3-tts-instruct-flash").strip()
        if "plus" in model_name:
            tts_block = """**当前TTS模型：CosyVoice v3.5-plus（精品模式）**\n- 适合：精品章节 / 情绪层次丰富场景\n- 特性：精细情感控制、instruction 演绎能力强，但必须使用复刻/设计音色\n"""
            instruct_block = (
                "**Instruct 提示（cosyvoice-v3.5-plus）**\n"
                "- 无系统音色，请默认上游已选择复刻/设计 voice_id\n"
                "- 请输出结构化指令字段：instruct_emotion / instruct_scene / instruct_role / instruct_identity\n"
                "- instruct_emotion 取值：neutral、fearful、angry、sad、surprised、happy、disgusted\n"
                "- 请优先输出通用自然语言约束，不要依赖固定内置音色枚举\n"
            )
        else:
            tts_block = """**当前TTS模型：Qwen3-TTS Instruct Flash（默认模式）**\n- 适合：长篇连载 / 日更章节 / 成本敏感但需要一定表现力的内容\n- 特性：49 音色、稳定性强、成本低，并支持通过自然语言 instructions 控制语气与演绎\n- 限制：当前链路重点是 instructions，不要输出 SSML 语法\n"""
            instruct_block = """**Qwen3 Instruct 提示**\n- 请输出结构化指令字段：instruct_emotion / instruct_scene / instruct_role / instruct_identity\n- performance_notes 会一并映射到 Qwen instructions，请写成可直接执行的演绎说明\n- qwen3-tts-instruct-flash 不依赖 SSML，请直接描述情绪、场景、身份与语气目标\n"""

        six_step_block = """**有声剧本 6 步听觉化重构流程（请严格遵守）**\n1. 心理活动 → 改写为可听见的独白或用音效/环境暗示呈现，避免长篇抽象描写。\n2. 环境描写 → 提炼为可感知的音效标签（如“雨声渐密”“地铁驶过”），填入 sound_effects。\n3. 动作与场景切换 → 用短句 + 停顿 + 过渡性音效，避免连续大段说明。\n4. 对话优化 → 口语化，必要时拆分过长句子，允许适度长句，去掉拗口表达，保证朗读顺畅。\n5. 节奏控制 → 根据情节紧张度调整句长，并通过 pause_before/pause_after 控制呼吸感。\n6. 音乐与情绪 → 为情绪明显的片段给出 music_cue（如“低频紧张弦乐”），避免整章铺满BGM。\n   - 音效密度建议控制在每分钟 2-6 个，仅保留关键动作/场景的音效。\n   - 配乐覆盖建议 15%-40%，低密度时仅保留开头/结尾/高潮等关键位置。\n"""

        adaptation_block = (
            f"**跨模态改编提示**:\n{audio_adaptation_brief}\n\n"
            if audio_adaptation_brief
            else ""
        )
        
        character_block = ""
        if character_profiles:
            character_block = "**角色参考**（用于对话归属和角色身份识别）：\n"
            for char in character_profiles:
                char_desc = f"- {char['name']}"
                if char.get('role_position'):
                    char_desc += f"（{char['role_position']}）"
                if char.get('relations'):
                    char_desc += f"，{char['relations']}"
                character_block += char_desc + "\n"

        prompt = f"""你是专业的有声书剧本改编师，负责将网络小说改编成适合音频化播放的有声剧本。

{tts_block}

{instruct_block}

{six_step_block}

**🎯 片段划分与语义完整性（建议）**
        
下面的规则是"优先参考"而不是硬性约束，你可以在保证听感流畅和语义清晰的前提下灵活使用短片段：
        
1【推荐做法：语义完整优先】
   - 尽量让每个片段在语义上自洽：包含完整的动作/情绪/场景信息，而不是被机械拆成几字一段。
        
2【短片段的合理场景】
   - ✅ 简短而自然的对白/感叹（如"好。""这不可能！"，"你说什么？"）可以作为独立片段存在；
   - ✅ 强烈情绪的短句（惊讶/愤怒/紧张等）适合单独成段，用来制造节奏和冲击力；
   - ❗ 建议避免：完全脱离上下文、让人不知所云的碎片（如单独出现的"就一晚。"而看不到前后铺垫）。
        
3【对话与旁白关系】
   - 对话前后的旁白，可以适当合在一起，形成"动作/心理 + 台词"的完整单位；
   - 对于本来就自然很短的应答（"行。""好。"），可以放心保留为独立片段，不必强行合并。
        
总之：**请优先保证片段本身听起来自然、有完整语气和意义，不必一味追求统一长度，也不需要强行合并所有短句。**
        
**已知角色**: {', '.join(character_list) if character_list else '无'}
{character_block}
**情感基调**: {analysis.get('emotional_tone', 'neutral')}
**建议情感**: {', '.join(analysis.get('recommended_emotions', ['natural']))}
**节奏模式**: {analysis.get('rhythm_pattern', '中等')}
{adaptation_block}

**原文段落**:
{paragraph}

**输出格式**：
请以**纯净的JSON数组格式**输出剧本片段（不要包含任何注释或说明文字）：

**格式选择**：
1. **精品模式**（推荐）：详细配置音效/配乐参数（音量、层级、3D位置、淡入淡出）
2. **简洁模式**：只标注音效/配乐名称（系统会自动使用默认参数）

```json
[
    {{
        "type": "narration|dialogue|monologue",
        "text": "改编后的文本（简洁、听觉友好）",
        "speaker": "角色名或旁白",
        "emotion": "neutral|happy|sad|angry|calm|tense|excited|tender|solemn",
        "instruct_emotion": "neutral|fearful|angry|sad|surprised|happy|disgusted",
        "instruct_scene": "闲聊互动|新闻播报|比赛解说|诗歌朗诵|...（不适用留空）",
        "instruct_role": "一个旁白|温和客服（不适用留空）",
        "instruct_identity": "故事机（不适用留空）",
        "voice_params": {{
            "rate": 1.0,
            "pitch": 1.0,
            "pause_before": 0.2,
            "pause_after": 0.3
        }},
        "performance_notes": "语气提示，如：以故事机的身份温柔讲述 / 激动地高声说 / 低声急促地提醒",
        
        // 🆕 音效配置（二选一）
        // 方式1：精品模式（推荐）
        "sound_effects": [
            {{
                "name": "脚步声",
                "layer": "action",  // bottom(底音) | action(动作) | atmosphere(氛围)
                "volume": 0.3,  // 0.0-1.0，人声为1.0基准
                "timing": "trigger",  // continuous(持续) | trigger(触发式)
                "position_3d": "left_to_right",  // left | right | center | back | left_to_right | right_to_left
                "duration": 2.0,  // 持续时长（秒）
                "fade_out": 0.5  // 淡出时长（秒）
            }}
        ],
        // 方式2：简洁模式（兼容）
        "sound_effects_simple": ["脚步声", "雨声"],
        
        // 🆕 配乐配置（二选一）
        // 方式1：精品模式（推荐）
        "music_cue": {{
            "style": "悬疑低频弦乐",
            "volume": 0.2,  // 0.0-1.0，建议0.15-0.4范围
            "fade_in": 2.0,  // 淡入时长（秒）
            "fade_out": 2.0,  // 淡出时长（秒）
            "emotion_follow": true  // 是否跟随情绪波动调整音量
        }},
        // 方式2：简洁模式（兼容）
        "music_cue_simple": "悬疑低频弦乐",
        
        "original_text": "对应的原文",
        "adaptation_reason": "改编原因说明（如：使用较短句子 + 长停顿营造压迫感）"
    }}
]
```

**🎵 音效/配乐标注指南**：

1. **音效分层原则**：
   - bottom（底音）：持续的环境音，如"雨声""风声""火光燃烧噪噪声"，音量0.08-0.15
   - action（动作）：触发式音效，如"脚步声""开门声""剑刃碰撞"，音量0.3-0.5
   - atmosphere（氛围）：情绪加强，如"诡异回声""雷声""人群噪声"，音量0.2-0.4

2. **3D位置使用**：
   - 角色移动：使用 left_to_right 或 right_to_left
   - 静态场景：center（主角视角）、left/right（配角）、back（远处）

3. **配乐音量控制**：
   - 日常场景：0.15-0.2
   - 情绪高涨：0.3-0.4
   - 高潮场景：0.4-0.5（关键处留白，突出台词）

*重要提醒**：
- 只输出JSON数组，不要添加任何//注释或/*注释*/
- 不要在JSON中添加解释性文字
- emotion字段必须使用推荐情感之一，不要自行发明
- instruct_emotion 可用于 qwen3-tts-instruct-flash / cosyvoice-v3.5-plus；CosyVoice 请使用 neutral、fearful、angry、sad、surprised、happy、disgusted
- instruct_scene / instruct_role / instruct_identity 可用于 qwen3-tts-instruct-flash / cosyvoice-v3.5-plus；CosyVoice 请输出通用自然语言约束，不要依赖固定系统音色枚举
- voice_params必须包含rate和pitch参数，根据情感调整
- pause_before/after单位为秒，范围：0.1-2.0
- 优先使用happy/sad/tense等有强烈情感的标签，避免过多使用neutral
- performance_notes要具体可执行，帮助TTS调节韵律和语气；在 qwen3-tts-instruct-flash 中它会直接参与 instructions 构建
- adaptation_reason说明为什么这样设置句式和停顿，以服务听觉节奏

🔥 **极重要：text字段内容规范**
- text字段必须是**实际要朗读的台词/旁白内容**，不要写对朗读方式的描述
- ❌ 错误示例："旁白将温柔地讲述接下来的情节"（这是剧本指导语，不是台词）
- ❌ 错误示例："旁白怎样怎样选择"（这是对角色的描述，不是台词）
- ✅ 正确示例："夜幕降临，城市的灯光逐渐亮起"（这是实际的旁白台词）
- ✅ 正确示例："你真的要这样做吗？"（这是实际的对话台词）
- 如果需要说明朗读方式，请使用performance_notes字段，不要写在text中
"""
        
        try:
            from core.model_resolution import TaskType
            
            # 使用AUDIOBOOK_SCRIPT任务类型（自动选择deepseek-v4-pro）
            # 剧本转化可能输出很长的JSON数组，需要设置足够大的max_tokens
            max_tokens_value = 32000
            logger.info(f"🔧 [段落转化] 请求 max_tokens: {max_tokens_value}, 段落长度: {len(paragraph)} 字")
            
            response = await self.llm_client.chat(
                messages=[{"role": "user", "content": prompt}],
                task_type=TaskType.AUDIOBOOK_SCRIPT,
                max_tokens=max_tokens_value,
                use_cache=False,
                response_format={"type": "json_object"},  # 启用 deepseek JSON 模式
            )
            
            logger.info(f"📊 [段落转化] 实际返回: {len(response)} 字符 (JSON截断检测: {'TRUNCATED' if len(response) > 40000 else 'OK'})")
            
            # 提取JSON
            json_match = response.find("```json")
            if json_match != -1:
                json_end = response.find("```", json_match + 7)
                json_str = response[json_match + 7:json_end].strip()
            else:
                json_str = response.strip()
            
            # 清理JSON字符串（移除注释和多余逗号）
            import re
            # 移除单行注释 // ...
            json_str = re.sub(r'//.*?$', '', json_str, flags=re.MULTILINE)
            # 移除多行注释 /* ... */
            json_str = re.sub(r'/\*.*?\*/', '', json_str, flags=re.DOTALL)
            # 移除数组/对象末尾的多余逗号
            json_str = re.sub(r',\s*([}\]])', r'\1', json_str)
            
            # 记录清理后的JSON（用于调试）
            if len(json_str) > 500:
                logger.debug(f"清理后的JSON（前500字符）: {json_str[:500]}")
            else:
                logger.debug(f"清理后的JSON: {json_str}")
            
            try:
                segments_data = json.loads(json_str)
            except json.JSONDecodeError as json_err:
                logger.error(f"JSON解析失败，原始响应: {response[:1000]}")
                logger.error(f"清理后JSON: {json_str[:1000]}")
                # 尝试自动截断到最后一个完整对象来修复 JSON（避免因为尾部被截断导致整个数组不可用）
                try:
                    first_bracket = json_str.find("[")
                    last_brace = json_str.rfind("}")
                    if first_bracket != -1 and last_brace != -1 and last_brace > first_bracket:
                        salvage_str = json_str[first_bracket:last_brace + 1]
                        salvage_str = salvage_str.rstrip()
                        if salvage_str.endswith(","):
                            salvage_str = salvage_str[:-1]
                        salvage_str = salvage_str + "]"
                        logger.warning("⚠️ 尝试通过截断到最后一个完整对象来修复JSON...")
                        segments_data = json.loads(salvage_str)
                        logger.info(f"✅ JSON修复成功，保留片段数: {len(segments_data)}")
                    else:
                        raise json_err
                except Exception:
                    # 修复失败，再抛出原始错误
                    raise RuntimeError(f"LLM返回的JSON格式错误: {json_err}")
            
            # 修复：将中文字段名转换为英文（deepseek-v4-pro可能返回中文字段）
            field_mapping = {
                '类型': 'type',
                '文本': 'text',
                '说话人': 'speaker',
                '情绪': 'emotion',
                '情感值': 'instruct_emotion',
                '指令情感': 'instruct_emotion',
                '场景': 'instruct_scene',
                '指令场景': 'instruct_scene',
                '指令角色': 'instruct_role',
                '角色指令': 'instruct_role',
                '身份': 'instruct_identity',
                '指令身份': 'instruct_identity',
                '动作': 'action',
                '音效': 'sound_effects',
                '音乐': 'music_cue',
                '改编理由': 'adaptation_reason',
                'adaptation_理由': 'adaptation_reason',  # 混合情况
            }
            
            # 清理字段名
            cleaned_segments = []
            for seg in segments_data:
                cleaned_seg = {}
                for key, value in seg.items():
                    # 如果是中文字段名，转换为英文
                    english_key = field_mapping.get(key, key)
                    cleaned_seg[english_key] = value
                cleaned_segments.append(cleaned_seg)
            
            # 记录字段映射情况（调试）
            if any(key in field_mapping for seg in segments_data for key in seg.keys()):
                logger.warning("⚠️ LLM返回了中文字段名，已自动转换为英文")
            
            # 转换为ScriptSegment对象
            return [ScriptSegment(**seg) for seg in cleaned_segments]
            
        except Exception as e:
            logger.error(f"段落转化失败: {e}")
