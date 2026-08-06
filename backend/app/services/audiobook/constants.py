"""Shared constants for audiobook services."""

# Qwen3-TTS Instruct Flash relies on model-level instructions rather than a
# dedicated instruct speaker list, so this remains empty for now.
INSTRUCT_SPEAKER_IDS: set[str] = set()

QWEN3_TTS_INSTRUCT_SUPPORTED_VOICES = frozenset(
    {
        "Arthur",
        "Bella",
        "Bellona",
        "Bunny",
        "Chelsie",
        "Cherry",
        "Eldric Sage",
        "Elias",
        "Ethan",
        "Kai",
        "Maia",
        "Mia",
        "Mochi",
        "Momo",
        "Moon",
        "Neil",
        "Nini",
        "Nofish",
        "Pip",
        "Seren",
        "Serena",
        "Stella",
        "Vincent",
        "Vivian",
    }
)

# Flash-only Qwen voices are remapped to the closest instruct-flash voice so
# old projects and cached selections keep working after the model upgrade.
QWEN_FLASH_ONLY_TO_INSTRUCT = {
    "Aiden": "Ethan",
    "Alek": "Elias",
    "Andre": "Neil",
    "Bodega": "Ethan",
    "Dolce": "Vincent",
    "Dylan": "Ethan",
    "Emilien": "Ethan",
    "Eric": "Nofish",
    "Jada": "Mia",
    "Jennifer": "Bellona",
    "Katerina": "Vivian",
    "Kiki": "Nini",
    "Lenn": "Elias",
    "Li": "Vincent",
    "Marcus": "Vincent",
    "Ono Anna": "Nini",
    "Peter": "Vincent",
    "Radio Gol": "Ethan",
    "Rocky": "Kai",
    "Roy": "Vincent",
    "Ryan": "Neil",
    "Sohee": "Serena",
    "Sonrisa": "Stella",
    "Sunny": "Mia",
}

# Legacy CosyVoice speaker IDs -> Qwen3-TTS voices.
# Ensures old project configs continue working after the engine switch.
COSYVOICE_TO_QWEN = {
    # Male voices
    "longanyang": "Ethan",
    "longanyun_v3": "Vincent",
    "longanzhi_v3": "Ryan",
    "longyichen_v3": "Aiden",
    "longlaobo_v3": "Eldric Sage",
    "longhan_v3": "Vincent",
    "longyingxun_v3": "Kai",
    "longanlang_v3": "Li",
    "longhouge_v3": "Nofish",
    "longshange_v3": "Eric",
    "longjing": "Eldric Sage",
    "longshaohua": "Ethan",
    "longfei": "Aiden",
    # Female voices
    "longwanjun_v3": "Cherry",
    "longanhuan": "Bunny",
    "longanmin_v3": "Momo",
    "longanya_v3": "Katerina",
    "longanwen_v3": "Serena",
    "longlaoyi_v3": "Chelsie",
    "longanrou_v3": "Mochi",
    "longanqin_v3": "Mia",
    "longhuhu_v3": "Momo",
    "longcaitou": "Cherry",
    "longxiaochun": "Jennifer",
    "longxiaoxuan": "Bunny",
    "longwan": "Bella",
}


def normalize_speaker_id(speaker_id: str) -> str:
    """Map legacy CosyVoice and Flash-only Qwen voices to instruct-flash."""
    speaker_id = str(speaker_id).strip()
    if not speaker_id:
        return ""

    normalized = COSYVOICE_TO_QWEN.get(speaker_id, speaker_id)
    return QWEN_FLASH_ONLY_TO_INSTRUCT.get(normalized, normalized)
