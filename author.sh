#!/usr/bin/env bash
# author.sh <model> — AUTHORING.md の依頼で、4分類の課題を1題ずつ作らせ、取り込んで検証する
# 出力: bench/tasks/<model>-<分類>/（課題一式）と bench/authoring/<model>-<分類>/（生の答え・時間）
set -uo pipefail
M="$1"; HERE="$(cd "$(dirname "$0")" && pwd)"
export TMPDIR="${TMPDIR:-/tmp}"
for C in spec bugfix feature multifile; do
  A="$HERE/authoring/$M-$C"; T="$HERE/tasks/$M-$C"; mkdir -p "$A"
  [ -s "$T/meta.json" ] && { echo "skip $M-$C（作成済み）"; continue; }
  sed "s/{CATEGORY}/$C/g" "$HERE/AUTHORING.md" > "$A/prompt.md"
  python3 "$HERE/bench.py" call "$M" "$A/prompt.md" "$A" > "$A/call.json" 2> "$A/call.err"
  mkdir -p "$T"
  python3 "$HERE/bench.py" parse "$A/answer.md" "$T" > "$A/parse.json" 2>> "$A/call.err"
  python3 "$HERE/bench.py" validate "$T" > "$A/validate.json" 2>> "$A/call.err"
  echo "$M-$C $(cat "$A/call.json" | head -c 300) | $(cat "$A/validate.json" | python3 -c 'import json,sys
try:
 d=json.load(sys.stdin);print("ref",d["ref"]["passed"],"/",d["ref"]["run"],"given",d["given"]["passed"],"/",d["given"]["run"],"lines",d["ref_lines"],"ok",d["ok"])
except Exception as e: print("検証できず",e)')"
done
