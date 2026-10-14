#!/usr/bin/env bash
# run_codex.sh <model> <回数> — Codex 用。利用枠に当たったらその回を退避して止まる（空の答えを不合格として数えない）
set -uo pipefail
M="$1"; N="$2"; HERE="$(cd "$(dirname "$0")" && pwd)"
export TMPDIR="${TMPDIR:-/tmp}"
for T in "$HERE"/frozen/*/; do
  T="${T%/}"; name="$(basename "$T")"
  for i in $(seq 1 "$N"); do
    R="$HERE/runs/$name/$M-$i"; [ -s "$R/grade.json" ] && continue
    mkdir -p "$R"
    python3 "$HERE/bench.py" solve-prompt "$T" > "$R/prompt.md"
    python3 "$HERE/bench.py" call "$M" "$R/prompt.md" "$R" > "$R/call.json" 2> "$R/call.err" || true
    if python3 -c "import json,sys;m=json.load(open('$R/meta.json'));sys.exit(0 if m.get('limit') else 1)"; then
      mkdir -p "$HERE/_failed/codex-limit"; mv "$R" "$HERE/_failed/codex-limit/$name-$M-$i-$(date +%H%M%S)"
      echo "$(date +%H:%M:%S) 利用枠で停止: $name $M-$i"; exit 2
    fi
    python3 "$HERE/bench.py" grade "$T" "$R/answer.md" > "$R/grade.json" 2>> "$R/call.err" || echo '{"run":0,"passed":0,"status":"grade-error"}' > "$R/grade.json"
    echo "$(date +%H:%M:%S) $name $M-$i $(python3 -c "import json;g=json.load(open('$R/grade.json'));print(g.get('passed'),'/',g.get('run'),g.get('status'))")"
  done
done
echo "$(date +%H:%M:%S) $M 完了"
