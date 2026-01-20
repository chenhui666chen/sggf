from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Tuple
import re


@dataclass
class VisemeEvent:
    start_s: float
    end_s: float
    viseme: str
    text: str = ""
    confidence: float = 0.35

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class LipsyncTrack:
    shot_id: str
    character_name: str
    character_id: Optional[str]
    voice_id: Optional[str]
    start_s: float
    end_s: float
    source: str
    events: List[VisemeEvent]

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["events"] = [event.to_dict() for event in self.events]
        return data


class LipsyncManager:
    def __init__(self, mode: str = "estimate") -> None:
        self.mode = (mode or "estimate").strip().lower()

    def build_tracks(self, dialogue_tracks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        tracks: List[Dict[str, Any]] = []
        for track in dialogue_tracks:
            text = str(track.get("text") or "")
            start_s = float(track.get("start_s") or 0.0)
            end_s = float(track.get("end_s") or start_s)
            timestamps = track.get("tts_timestamps") or track.get("phoneme_timestamps")

            if isinstance(timestamps, list) and timestamps:
                events = self._events_from_timestamps(timestamps, start_s, end_s)
                source = "tts"
            else:
                events = self._estimate_events(text, start_s, end_s)
                source = "forced_alignment" if self.mode in {"force", "align", "forced"} else "estimate"

            track_info = LipsyncTrack(
                shot_id=str(track.get("shot_id") or ""),
                character_name=str(track.get("speaker") or ""),
                character_id=track.get("character_id"),
                voice_id=track.get("voice_id") or track.get("voice_profile_id"),
                start_s=start_s,
                end_s=end_s,
                source=source,
                events=events,
            )
            tracks.append(track_info.to_dict())
        return tracks

    def _events_from_timestamps(
        self,
        timestamps: List[Dict[str, Any]],
        start_s: float,
        end_s: float,
    ) -> List[VisemeEvent]:
        events: List[VisemeEvent] = []
        for item in timestamps:
            if not isinstance(item, dict):
                continue
            start = float(item.get("start_s") or item.get("start") or start_s)
            end = float(item.get("end_s") or item.get("end") or start)
            if end <= start:
                continue
            text = str(item.get("text") or item.get("phoneme") or item.get("viseme") or "")
            viseme = str(item.get("viseme") or "").strip() or self._map_viseme(text)
            events.append(
                VisemeEvent(
                    start_s=max(start_s, start),
                    end_s=min(end_s, end),
                    viseme=viseme,
                    text=text,
                    confidence=float(item.get("confidence") or 0.6),
                )
            )

        if not events and end_s > start_s:
            events.append(
                VisemeEvent(
                    start_s=start_s,
                    end_s=end_s,
                    viseme="sil",
                    text="",
                    confidence=0.2,
                )
            )
        return events

    def _estimate_events(self, text: str, start_s: float, end_s: float) -> List[VisemeEvent]:
        duration = max(0.01, end_s - start_s)
        tokens = self._tokenize(text)
        if not tokens:
            return [
                VisemeEvent(
                    start_s=start_s,
                    end_s=end_s,
                    viseme="sil",
                    text="",
                    confidence=0.2,
                )
            ]

        step = duration / float(len(tokens))
        cursor = start_s
        events: List[VisemeEvent] = []
        for token in tokens:
            next_cursor = min(end_s, cursor + step)
            viseme = "sil" if token[1] == "pause" else self._map_viseme(token[0])
            events.append(
                VisemeEvent(
                    start_s=cursor,
                    end_s=max(cursor, next_cursor),
                    viseme=viseme,
                    text=token[0],
                    confidence=0.35,
                )
            )
            cursor = next_cursor

        if events:
            events[-1].end_s = end_s
            if events[-1].end_s < events[-1].start_s + 0.01:
                events[-1].end_s = events[-1].start_s + 0.01
        return events

    def _tokenize(self, text: str) -> List[Tuple[str, str]]:
        tokens: List[Tuple[str, str]] = []
        buf: List[str] = []

        def flush_buf() -> None:
            if buf:
                tokens.append(("".join(buf), "word"))
                buf.clear()

        for ch in text:
            if ch.isspace():
                flush_buf()
                continue
            if re.match(r"[A-Za-z0-9]", ch):
                buf.append(ch)
                continue
            flush_buf()
            if self._is_pause_char(ch):
                tokens.append((ch, "pause"))
            else:
                tokens.append((ch, "char"))

        flush_buf()
        return tokens

    def _is_pause_char(self, ch: str) -> bool:
        return ch in "，。！？；、,.;:!?…"

    def _map_viseme(self, token: str) -> str:
        text = token.lower()
        if not text:
            return "sil"
        if re.search(r"[mbp]$", text):
            return "MBP"
        vowel = self._last_vowel(text)
        if vowel in {"a"}:
            return "AA"
        if vowel in {"e", "i", "y"}:
            return "EE"
        if vowel in {"o", "u", "v"}:
            return "OO"
        return "AA"

    def _last_vowel(self, text: str) -> str:
        for ch in reversed(text):
            if ch in "aeiouyv":
                return ch
        return ""
