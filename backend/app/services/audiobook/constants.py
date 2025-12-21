"""Shared constants for audiobook services."""

# Qwen3-TTS currently doesn't expose dedicated "instruction" voices, so this set
# remains empty. If future models reintroduce instruction-capable timbres,
# populate this list with their speaker IDs to re-enable the special handling.
INSTRUCT_SPEAKER_IDS: set[str] = set()

# Legacy CosyVoice speaker IDs -> Qwen3-TTS voices.
# Ensures old project configs continue working after the engine switch.
COSYVOICE_TO_QWEN = {
    # Male voices
    "longanyang": "Ethan",
    "longanyun_v3": "Elias",
    "longanzhi_v3": "Ryan",
    "longyichen_v3": "Dylan",
    "longlaobo_v3": "Marcus",
    "longhan_v3": "Roy",
    "longyingxun_v3": "Peter",
    "longanlang_v3": "Li",
    "longhouge_v3": "Nofish",
    "longshange_v3": "Eric",
    "longjing": "Marcus",
    "longshaohua": "Ethan",
    "longfei": "Dylan",
    # Female voices
    "longwanjun_v3": "Cherry",
    "longanhuan": "Sunny",
    "longanmin_v3": "Momo",
    "longanya_v3": "Katerina",
    "longanwen_v3": "Serena",
    "longlaoyi_v3": "Chelsie",
    "longanrou_v3": "Jada",
    "longanqin_v3": "Kiki",
    "longhuhu_v3": "Momo",
    "longcaitou": "Cherry",
    "longxiaochun": "Jennifer",
    "longxiaoxuan": "Sunny",
    "longwan": "Serena",
}


def normalize_speaker_id(speaker_id: str) -> str:
    """Map legacy CosyVoice IDs to the new Qwen3-TTS speakers if needed."""
    return COSYVOICE_TO_QWEN.get(speaker_id, speaker_id)
