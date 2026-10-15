from pathlib import Path

path = Path("scripts/video_gateway_release.ps1")
text = path.read_text(encoding="utf-8")
start = text.index("function Invoke-Remote")
end = text.index("function Require-LocalImage")
replacement = """function Invoke-Remote([string]$Command) {
    $singleQuote = [string][char]39
    $quoted = $Command.Replace($singleQuote, $singleQuote + '\"' + $singleQuote + '\"' + $singleQuote)
    ssh -o BatchMode=yes -o ConnectTimeout=8 $target \"bash -lc '$quoted'\"
    if ($LASTEXITCODE -ne 0) { throw \"Remote command failed with exit code $LASTEXITCODE\" }
}
"""
path.write_text(text[:start] + replacement + text[end:], encoding="utf-8", newline="\n")
