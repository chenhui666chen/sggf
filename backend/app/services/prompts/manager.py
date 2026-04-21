"""
提示词管理器 - JSON 化集中管理

核心功能：
1. 从 agents.json 加载所有 Agent 的 system prompt
2. 支持变量替换（模板引擎）
3. 内存缓存，避免重复文件读取
4. 热更新支持（可重新加载）
5. 版本追踪

使用方式：
    from app.services.prompts.manager import prompt_manager
    system_prompt = prompt_manager.get_agent_prompt("character_designer")
    user_prompt = prompt_manager.get_user_prompt("content_creator_scene", scene_name="xxx")
"""
import copy
import json
import logging
import os
import tempfile
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# 默认文件路径（相对于项目根目录）
_DEFAULT_JSON_PATH = os.path.join(
    os.path.dirname(__file__),
    "agents.json",
)

_DEFAULT_OVERRIDES_JSON_PATH = os.path.join(
    os.path.dirname(__file__),
    "agents.overrides.json",
)


class PromptManager:
    """提示词管理器 - 从 JSON 集中中管理提示词"""

    def __init__(self, json_path: Optional[str] = None, overrides_path: Optional[str] = None):
        self._json_path = json_path or _DEFAULT_JSON_PATH
        self._overrides_path = overrides_path or _DEFAULT_OVERRIDES_JSON_PATH
        self._base_data: Dict[str, Any] = {}
        self._overrides_data: Dict[str, Any] = {}
        self._data: Dict[str, Any] = {}
        self._cache: Dict[str, str] = {}
        self._version: str = ""
        self._last_load_time: float = 0.0
        self._load_ok: bool = False

    @property
    def is_loaded(self) -> bool:
        return self._load_ok

    @property
    def version(self) -> str:
        return self._version

    def load(self, force: bool = False) -> bool:
        """加载 JSON 配置文件

        Args:
            force: 是否强制重新加载（热更新）

        Returns:
            加载是否成功
        """
        if not force and self._load_ok:
            return True

        try:
            self._base_data = self._read_json_file(self._json_path)
            self._overrides_data = self._read_json_file(self._overrides_path, allow_missing=True)
            self._data = self._merge_overrides(self._base_data, self._overrides_data)

            self._version = self._base_data.get("version", "unknown")
            self._last_load_time = time.time()
            self._cache.clear()
            self._load_ok = True

            agent_count = len(self._data.get("agents", {}))
            prompt_count = len(self._data.get("user_prompts", {}))
            override_agent_count = len(self._overrides_data.get("agents", {}))
            override_prompt_count = len(self._overrides_data.get("user_prompts", {}))
            logger.info(
                "PromptManager 加载成功: version=%s, agents=%d, user_prompts=%d, override_agents=%d, override_user_prompts=%d",
                self._version,
                agent_count,
                prompt_count,
                override_agent_count,
                override_prompt_count,
            )
            return True
        except Exception as e:
            logger.error("PromptManager 加载失败 (%s): %s", self._json_path, e)
            self._load_ok = False
            return False

    def get_agent_prompt(self, agent_key: str, variables: Optional[Dict[str, str]] = None, force_default: bool = False) -> str:
        """获取指定 Agent 的 system prompt

        Args:
            agent_key: Agent 标识（对应 JSON 中的 agents 键名）
            variables: 变量替换字典
            force_default: 是否强制从 JSON 文件重新读取默认提示词（忽略缓存和内存修改）

        Returns:
            替换变量后的 system prompt，如果未找到则返回空字符串
        """
        if force_default:
            try:
                data = self._read_json_file(self._json_path)
                agents = data.get("agents", {})
                agent_config = agents.get(agent_key, {})
                return agent_config.get("system_prompt", "")
            except Exception as e:
                logger.error("读取默认提示词失败: %s", e)
                return ""

        if not self._load_ok:
            self.load()

        cache_key = f"agent:{agent_key}"
        if cache_key in self._cache and not variables:
            return self._cache[cache_key]

        agents = self._data.get("agents", {})
        agent_config = agents.get(agent_key)
        if not agent_config:
            logger.warning("Agent prompt 未找到: %s", agent_key)
            return ""

        prompt = agent_config.get("system_prompt", "")
        if variables:
            prompt = self._replace_variables(prompt, variables)

        if not variables:
            self._cache[cache_key] = prompt

        return prompt

    def get_user_prompt(self, prompt_key: str, variables: Optional[Dict[str, str]] = None, force_default: bool = False) -> str:
        """获取 user prompt 模板

        Args:
            prompt_key: prompt 标识（对应 JSON 中的 user_prompts 键名）
            variables: 变量替换字典
            force_default: 是否强制从 JSON 文件重新读取默认模板

        Returns:
            替换变量后的 user prompt，如果未找到则返回空字符串
        """
        if force_default:
            try:
                data = self._read_json_file(self._json_path)
                user_prompts = data.get("user_prompts", {})
                prompt_config = user_prompts.get(prompt_key, {})
                return prompt_config.get("template", "")
            except Exception as e:
                logger.error("读取默认 user prompt 失败: %s", e)
                return ""

        if not self._load_ok:
            self.load()

        cache_key = f"user:{prompt_key}"
        if cache_key in self._cache and not variables:
            return self._cache[cache_key]

        user_prompts = self._data.get("user_prompts", {})
        prompt_config = user_prompts.get(prompt_key)
        if not prompt_config:
            logger.warning("User prompt 未找到: %s", prompt_key)
            return ""

        template = prompt_config.get("template", "")
        if variables:
            template = self._replace_variables(template, variables)

        if not variables:
            self._cache[cache_key] = template

        return template

    def get_agent_name(self, agent_key: str) -> str:
        """获取 Agent 显示名称"""
        if not self._load_ok:
            self.load()

        agents = self._data.get("agents", {})
        agent_config = agents.get(agent_key, {})
        return agent_config.get("name", agent_key)

    def list_agents(self) -> Dict[str, str]:
        """列出所有已注册的 Agent (key -> name)"""
        if not self._load_ok:
            self.load()

        return {
            key: config.get("name", key)
            for key, config in self._data.get("agents", {}).items()
        }

    def list_user_prompts(self) -> Dict[str, str]:
        """列出所有已注册的 user prompt (key -> description)"""
        if not self._load_ok:
            self.load()

        return {
            key: config.get("description", key)
            for key, config in self._data.get("user_prompts", {}).items()
        }

    def reload(self) -> bool:
        """热更新 - 重新加载 JSON"""
        logger.info("PromptManager 热更新...")
        return self.load(force=True)

    def update_agent_prompt(self, agent_key: str, new_prompt: str) -> bool:
        """更新指定 Agent 的提示词（写入覆盖文件并刷新内存）

        Args:
            agent_key: Agent 标识
            new_prompt: 新的提示词内容

        Returns:
            更新是否成功
        """
        if not self._load_ok:
            self.load()

        agents = self._data.get("agents", {})
        if agent_key not in agents:
            logger.warning("Agent 不存在，无法更新: %s", agent_key)
            return False

        default_prompt = self.get_agent_prompt(agent_key, force_default=True)
        override_agents = self._overrides_data.setdefault("agents", {})
        if new_prompt == default_prompt:
            override_agents.pop(agent_key, None)
        else:
            override_entry = override_agents.setdefault(agent_key, {})
            override_entry["system_prompt"] = new_prompt

        self._persist_overrides()
        return self.reload()

    def get_agent_user_prompt_keys(self, agent_key: str) -> list:
        """获取指定 Agent 关联的 user prompt key 列表"""
        if not self._load_ok:
            self.load()

        mapping = self._data.get("agent_user_prompt_map", {})
        return mapping.get(agent_key, [])

    def update_user_prompt(self, prompt_key: str, new_template: str) -> bool:
        """更新指定 user prompt 模板（写入覆盖文件并刷新内存）

        Args:
            prompt_key: prompt 标识
            new_template: 新的模板内容

        Returns:
            更新是否成功
        """
        if not self._load_ok:
            self.load()

        user_prompts = self._data.get("user_prompts", {})
        if prompt_key not in user_prompts:
            logger.warning("User prompt 不存在，无法更新: %s", prompt_key)
            return False

        default_template = self.get_user_prompt(prompt_key, force_default=True)
        override_prompts = self._overrides_data.setdefault("user_prompts", {})
        if new_template == default_template:
            override_prompts.pop(prompt_key, None)
        else:
            override_entry = override_prompts.setdefault(prompt_key, {})
            override_entry["template"] = new_template

        self._persist_overrides()
        return self.reload()

    def reset_agent_prompt(self, agent_key: str) -> bool:
        """移除指定 Agent 的覆盖配置并恢复默认值。"""
        if not self._load_ok:
            self.load()

        if agent_key not in self._data.get("agents", {}):
            logger.warning("Agent 不存在，无法重置: %s", agent_key)
            return False

        override_agents = self._overrides_data.setdefault("agents", {})
        override_agents.pop(agent_key, None)
        self._persist_overrides()
        return self.reload()

    def reset_user_prompt(self, prompt_key: str) -> bool:
        """移除指定 user prompt 的覆盖配置并恢复默认值。"""
        if not self._load_ok:
            self.load()

        if prompt_key not in self._data.get("user_prompts", {}):
            logger.warning("User prompt 不存在，无法重置: %s", prompt_key)
            return False

        override_prompts = self._overrides_data.setdefault("user_prompts", {})
        override_prompts.pop(prompt_key, None)
        self._persist_overrides()
        return self.reload()

    @staticmethod
    def _read_json_file(path: str, allow_missing: bool = False) -> Dict[str, Any]:
        if allow_missing and not os.path.exists(path):
            return {}

        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def _merge_overrides(base_data: Dict[str, Any], overrides_data: Dict[str, Any]) -> Dict[str, Any]:
        merged = copy.deepcopy(base_data)

        base_agents = merged.setdefault("agents", {})
        for agent_key, override in overrides_data.get("agents", {}).items():
            if agent_key not in base_agents:
                continue
            base_agents[agent_key].update(override)

        base_user_prompts = merged.setdefault("user_prompts", {})
        for prompt_key, override in overrides_data.get("user_prompts", {}).items():
            if prompt_key not in base_user_prompts:
                continue
            base_user_prompts[prompt_key].update(override)

        return merged

    def _persist_overrides(self) -> None:
        overrides_payload = {
            "version": self._base_data.get("version", "unknown"),
            "agents": self._overrides_data.get("agents", {}),
            "user_prompts": self._overrides_data.get("user_prompts", {}),
        }
        target_dir = os.path.dirname(self._overrides_path) or "."

        if not overrides_payload["agents"] and not overrides_payload["user_prompts"]:
            if os.path.exists(self._overrides_path):
                os.remove(self._overrides_path)
            return

        os.makedirs(target_dir, exist_ok=True)
        temp_fd, temp_path = tempfile.mkstemp(
            prefix="agents.overrides.",
            suffix=".json",
            dir=target_dir,
        )
        try:
            with os.fdopen(temp_fd, "w", encoding="utf-8") as temp_file:
                json.dump(overrides_payload, temp_file, ensure_ascii=False, indent=2)
                temp_file.write("\n")
            os.replace(temp_path, self._overrides_path)
            logger.info("Prompt overrides 已持久化: %s", self._overrides_path)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    @staticmethod
    def _replace_variables(text: str, variables: Dict[str, str]) -> str:
        """替换模板中的变量

        支持两种格式：
        - {variable_name}
        - {variable_name:default_value}

        Args:
            text: 原始文本
            variables: 变量字典

        Returns:
            替换后的文本
        """
        import re

        def _replacer(match):
            var_name = match.group(1)
            default = match.group(3) if match.group(3) is not None else ""
            return variables.get(var_name, default if default else f"{{{var_name}}}")

        pattern = r"\{(\w+)(:([^}]*))?\}"
        return re.sub(pattern, _replacer, text)


# 全局单例
_prompt_manager: Optional[PromptManager] = None


def get_prompt_manager(
    json_path: Optional[str] = None,
    overrides_path: Optional[str] = None,
) -> PromptManager:
    """获取 PromptManager 单例"""
    global _prompt_manager
    if _prompt_manager is None:
        _prompt_manager = PromptManager(json_path, overrides_path=overrides_path)
        _prompt_manager.load()
    return _prompt_manager


# 快捷访问
prompt_manager = get_prompt_manager()
