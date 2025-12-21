#!/usr/bin/env bash
set -euo pipefail

INPUT=${INPUT:-input.mp4}
OUTPUT=${OUTPUT:-output_slow.mp4}
DURATION=${DURATION:-3}
OUT_ST=${OUT_ST:-2.5}

ffmpeg -y -i "$INPUT" \
  -vf "fade=t=in:st=0:d=0.5,fade=t=out:st=${OUT_ST}:d=0.5" \
  -af "afade=t=in:st=0:d=0.5,afade=t=out:st=${OUT_ST}:d=0.5" \
  -t "$DURATION" "$OUTPUT"
