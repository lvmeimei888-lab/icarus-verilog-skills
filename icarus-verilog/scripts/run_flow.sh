#!/usr/bin/env bash
# run_flow.sh — sim + optional vcd_peek + fail_triage on functional FAIL
# Usage: run_flow.sh RTL TB WORKDIR [TOP_MODULE] [OUT_NAME] [VCD_SIGNALS] [VCD_TIMES] [MODEL]
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RTL="${1:?RTL required}"
TB="${2:?TB required}"
WORKDIR="${3:-verilog/build}"
TOP_MODULE="${4:-}"
OUT_NAME="${5:-}"
SIGNALS="${6:-}"
TIMES="${7:-}"
MODEL="${8:-auto}"

LOG="$(mktemp)"
trap 'rm -f "$LOG"' EXIT

sim_args=("$RTL" "$TB" "$WORKDIR")
[[ -n "$TOP_MODULE" ]] && sim_args+=("$TOP_MODULE")
[[ -n "$OUT_NAME" ]] && sim_args+=("$OUT_NAME")

bash "$SCRIPT_DIR/sim.sh" "${sim_args[@]}" >"$LOG" 2>&1
SIM_EXIT=$?
cat "$LOG"

VCD=""
while IFS= read -r line; do
  if [[ "$line" == VCD:* ]]; then
    VCD="${line#VCD:}"
    VCD="${VCD#"${VCD%%[![:space:]]*}"}"
  fi
done < "$LOG"

if [[ -n "$SIGNALS" && -n "$VCD" && -f "$VCD" ]]; then
  PEEK_ARGS=(--vcd "$VCD" --signals "$SIGNALS")
  [[ -n "$TIMES" ]] && PEEK_ARGS+=(--times "$TIMES")
  python "$SCRIPT_DIR/vcd_peek.py" "${PEEK_ARGS[@]}"
fi

if [[ $SIM_EXIT -eq 1 && -n "$VCD" && -f "$VCD" ]]; then
  echo "==> fail_triage"
  python "$SCRIPT_DIR/fail_triage.py" --vcd "$VCD" --log "$LOG" --model "$MODEL" || true
fi

exit "$SIM_EXIT"
