#!/usr/bin/env bash
# review.sh <reviewer> — 作り手が自分以外の課題を点検させる（reviewer: claude | sol | argon）
# 出力: bench/reviews/<課題>/<reviewer>/answer.md
set -uo pipefail
RV="$1"; HERE="$(cd "$(dirname "$0")" && pwd)"
export TMPDIR="${TMPDIR:-/tmp}"
vendor() { case "$1" in claude) echo claude ;; sol|astra) echo codex ;; argon) echo argon ;; esac; }
for T in "$HERE"/tasks/*/; do
  T="${T%/}"; name="$(basename "$T")"; author="${name%%-*}"
  [ "$(vendor "$author")" = "$(vendor "$RV")" ] && continue
  [ -s "$T/meta.json" ] || continue
  O="$HERE/reviews/$name/$RV"; [ -s "$O/answer.md" ] && continue
  mkdir -p "$O"
  {
    cat "$HERE/REVIEW.md"
    for f in $(cd "$T" && find prompt.md given ref tests -type f 2>/dev/null | sort); do
      echo "=== FILE: $f ==="; cat "$T/$f"; echo
    done
    echo "=== END ==="
  } > "$O/prompt.md"
  python3 "$HERE/bench.py" call "$RV" "$O/prompt.md" "$O" > "$O/call.json" 2> "$O/call.err"
  echo "$(date +%H:%M:%S) $name <- $RV $(python3 -c "
import json,re
s=open('$O/answer.md').read(); m=re.search(r'\{.*\}', s, re.S)
try:
  d=json.loads(m.group(0)); iss=d.get('issues',[]); print(len(iss),'件', [i.get('severity') for i in iss])
except Exception as e: print('読めず', e)")"
done
