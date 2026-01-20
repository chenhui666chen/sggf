from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


class SoundEffectManager:
    """音效管理：从脚本标记解析音效，并生成每镜头SFX轨道。"""

    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir
        self.sfx_dir = run_dir / "sfx"
        self.sfx_dir.mkdir(exist_ok=True)
        self.ffmpeg = os.getenv("FFMPEG_PATH", "ffmpeg")

        self.project_root = Path(__file__).resolve().parents[1]
        self.audio_library_root = self.project_root / "backend" / "data" / "audio_library"
        self.sfx_root = self.audio_library_root / "sound_effects"
        self.file_index: Dict[str, str] = {}
        self._build_file_index()

        self.designer = None
        self._init_designer()

    def _build_file_index(self) -> None:
        if not self.sfx_root.exists():
            return
        for path in self.sfx_root.rglob("*"):
            if path.is_file():
                self.file_index[path.name.lower()] = str(path)

    def _init_designer(self) -> None:
        source = str(os.getenv("DREAMWEAVER_SFX_SOURCE") or "library").strip().lower()
        if source in {"model", "video", "none"}:
            return

        backend_root = self.project_root / "backend"
        if not backend_root.exists():
            return
        if str(backend_root) not in sys.path:
            sys.path.insert(0, str(backend_root))

        try:
            from app.services.audiobook.agents.sound_effect_designer import SoundEffectDesigner  # type: ignore

            self.designer = SoundEffectDesigner()
            auto_generate = str(os.getenv("DREAMWEAVER_SFX_AUTO_GENERATE", "0")).strip().lower() in {
                "1",
                "true",
                "yes",
                "y",
                "on",
            }
            if auto_generate:
                self.designer._ensure_core_assets_ready()
        except Exception:
            self.designer = None

    def _normalize_dialogue(self, text: str) -> str:
        raw = str(text or "").strip().lower()
        if not raw:
            return ""
        raw = re.sub(r"[\s\W]+", "", raw, flags=re.UNICODE)
        return raw

    def _extract_dialogues_from_shot(self, shot: Dict[str, Any]) -> List[Dict[str, str]]:
        dialogues: List[Dict[str, str]] = []
        markers = shot.get("audio_markers")
        if isinstance(markers, list):
            for marker in markers:
                if not isinstance(marker, dict):
                    continue
                text = str(marker.get("dialogue_text") or "").strip()
                speaker = str(marker.get("character_name") or "").strip()
                if text:
                    dialogues.append({"speaker": speaker, "text": text})
        if dialogues:
            return dialogues

        desc = str(shot.get("desc") or "")
        for line in desc.splitlines():
            line = line.strip()
            if not line:
                continue
            match = re.match(r"^([A-Za-z\u4e00-\u9fa5]+)[：:]\s*(.+)$", line)
            if match:
                speaker = match.group(1).strip()
                text = match.group(2).strip()
                if text:
                    dialogues.append({"speaker": speaker, "text": text})
        return dialogues

    def _resolve_effect_file(self, effect_desc: str) -> Optional[str]:
        if not effect_desc:
            return None

        candidate = Path(effect_desc)
        if candidate.is_absolute() and candidate.exists():
            return str(candidate)

        if effect_desc.lower() in self.file_index:
            return self.file_index[effect_desc.lower()]

        if self.designer:
            try:
                cue = self.designer._match_effect(
                    description=effect_desc,
                    timestamp=0.0,
                    scene_id="inline",
                )
                if cue and getattr(cue, "audio_file", ""):
                    file_ref = str(cue.audio_file).strip()
                    if file_ref.lower() in self.file_index:
                        return self.file_index[file_ref.lower()]
                    file_path = self.audio_library_root / file_ref
                    if file_path.exists():
                        return str(file_path)
            except Exception:
                return None

        return None

    def build_shot_effects_map(
        self,
        *,
        storyboard: List[Dict[str, Any]],
        audio_markers: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, List[Dict[str, Any]]]:
        effects_by_dialogue: Dict[str, List[str]] = {}
        if isinstance(audio_markers, list):
            for marker in audio_markers:
                if not isinstance(marker, dict):
                    continue
                effects = marker.get("sound_effects")
                if not isinstance(effects, list) or not effects:
                    continue
                key = self._normalize_dialogue(marker.get("dialogue_line") or "")
                if not key:
                    continue
                effects_by_dialogue[key] = [str(e).strip() for e in effects if str(e).strip()]

        shot_map: Dict[str, List[Dict[str, Any]]] = {}
        for shot in storyboard:
            if not isinstance(shot, dict):
                continue
            shot_id = str(shot.get("shot_id") or "").strip()
            if not shot_id:
                continue
            dialogues = self._extract_dialogues_from_shot(shot)
            effect_names: List[str] = []
            for dialogue in dialogues:
                key = self._normalize_dialogue(dialogue.get("text"))
                if key and key in effects_by_dialogue:
                    effect_names.extend(effects_by_dialogue[key])

            deduped: List[str] = []
            for name in effect_names:
                if name and name not in deduped:
                    deduped.append(name)

            if not deduped:
                continue

            items: List[Dict[str, Any]] = []
            for name in deduped:
                file_path = self._resolve_effect_file(name)
                if not file_path:
                    continue
                items.append(
                    {
                        "name": name,
                        "audio_path": file_path,
                        "volume": 0.5,
                    }
                )
            if items:
                shot_map[shot_id] = items

        return shot_map

    def render_shot_sfx(
        self,
        *,
        shot_id: str,
        duration_s: float,
        effect_items: List[Dict[str, Any]],
    ) -> Optional[str]:
        if not effect_items or duration_s <= 0:
            return None

        valid = [item for item in effect_items if Path(str(item.get("audio_path") or "")).exists()]
        if not valid:
            return None

        output_path = self.sfx_dir / f"{shot_id}_sfx.wav"
        if output_path.exists():
            return str(output_path)

        inputs: List[str] = [
            "-f",
            "lavfi",
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-t",
            str(float(duration_s)),
        ]
        for item in valid:
            inputs.extend(["-i", str(item.get("audio_path"))])

        filter_parts: List[str] = []
        count = len(valid)
        step = float(duration_s) / max(1, count)
        for idx, item in enumerate(valid):
            start_s = min(float(idx) * step, max(float(duration_s) - 0.1, 0.0))
            delay_ms = int(max(0.0, start_s) * 1000)
            volume = float(item.get("volume") or 0.5)
            filter_parts.append(
                f"[{idx + 1}:a]adelay={delay_ms}|{delay_ms},volume={volume}[a{idx}]"
            )

        mix_inputs = "[0:a]" + "".join([f"[a{idx}]" for idx in range(count)])
        filter_complex = ";".join(filter_parts) + f";{mix_inputs}amix=inputs={count + 1}:duration=first:dropout_transition=2[outa]"

        cmd = [
            self.ffmpeg,
            "-y",
            *inputs,
            "-filter_complex",
            filter_complex,
            "-map",
            "[outa]",
            "-c:a",
            "aac",
            str(output_path),
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True)
            return str(output_path)
        except Exception:
            return None
