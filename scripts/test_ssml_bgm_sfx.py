import asyncio
import os
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _ensure_import_path() -> None:
    backend_dir = _repo_root() / "backend"
    sys.path.insert(0, str(backend_dir))


def _load_dotenv() -> None:
    env_path = _repo_root() / ".env"
    if not env_path.exists():
        return
    try:
        for raw_line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.lower().startswith("export "):
                line = line[7:].strip()
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
    except Exception:
        return


async def main() -> None:
    _ensure_import_path()
    _load_dotenv()
    from app.services.audiobook.tts_engine import TTSEngine

    bgm_url = os.getenv("SSML_BGM_URL", "http://nls.alicdn.com/bgm/2.wav").strip()
    sfx_url = os.getenv("SSML_SFX_URL", "http://nls.alicdn.com/bgm/1.wav").strip()

    ssml = (
        f'<speak bgm="{bgm_url}" backgroundMusicVolume="30" rate="1.0" pitch="1.0" volume="50">'
        f'Hello. <break time="400ms"/> This is a test with BGM and SFX. '
        f'<audio src="{sfx_url}"/> <break time="300ms"/> The voice should continue after the sound.'
        f"</speak>"
    )

    engine = TTSEngine(enable_cache=False, max_concurrent=1, model="cosyvoice-v3-plus", request_delay=0.0)
    voice_params = {
        "speaker": "longanyang",
        "volume": 50,
        "use_ssml": True,
    }

    audio_bytes = await engine.synthesize(ssml, voice_params)
    if not audio_bytes:
        raise RuntimeError("empty audio response")

    output_path = _repo_root() / "runs" / "ssml_bgm_sfx_test.mp3"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(audio_bytes)
    print(f"saved: {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
