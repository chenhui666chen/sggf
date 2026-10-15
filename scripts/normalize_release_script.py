from pathlib import Path

data = Path("scripts/video_gateway_release.ps1").read_bytes()
print(data.count(b"\n"), data[:100])
