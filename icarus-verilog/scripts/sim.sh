#!/usr/bin/env bash
# sim.sh — compile and simulate Verilog with Icarus Verilog
# Usage: sim.sh RTL TB WORKDIR [TOP_MODULE] [OUT_NAME]
#   TOP_MODULE  — optional iverilog -s (module name only)
#   OUT_NAME      — .vvp base name (default: TB filename without .v)
set -uo pipefail

RTL="${1:?RTL file required}"
TB="${2:?Testbench file required}"
WORKDIR="${3:-verilog/build}"
TOP_MODULE="${4:-}"
OUT_NAME="${5:-}"

mkdir -p "$WORKDIR"

tb_base="$(basename "$TB" .v)"
if [[ -z "$OUT_NAME" ]]; then
  OUT_NAME="$tb_base"
fi

VVP_OUT="$WORKDIR/$OUT_NAME.vvp"
VVP_LEAF="$(basename "$VVP_OUT")"

compile_cmd=(iverilog -g2012 -Wall -o "$VVP_OUT")
if [[ -n "$TOP_MODULE" ]]; then
  compile_cmd+=(-s "$TOP_MODULE")
fi
compile_cmd+=("$RTL" "$TB")

echo "==> compile: ${compile_cmd[*]}"
echo "    OutName: ${OUT_NAME}.vvp${TOP_MODULE:+  Top(-s): $TOP_MODULE}"
if ! "${compile_cmd[@]}"; then
  echo "COMPILE FAILED (exit $?)"
  exit "$?"
fi

echo "==> simulate: vvp $VVP_OUT"
set +e
SIM_OUT="$(cd "$WORKDIR" && vvp "$VVP_LEAF" 2>&1)"
SIM_EXIT=$?
set -e
printf '%s\n' "$SIM_OUT"

VCD=""
if [[ "$SIM_OUT" =~ VCD\ info:\ dumpfile[[:space:]]+([^[:space:]]+)[[:space:]]+opened ]]; then
  rel="${BASH_REMATCH[1]}"
  if [[ "$rel" = /* ]]; then
    VCD="$rel"
  else
    VCD="$WORKDIR/$rel"
  fi
fi

if [[ -n "$VCD" && -f "$VCD" ]]; then
  echo "VCD: $VCD"
else
  echo "WARN: could not parse VCD path from stdout" >&2
fi

if [[ $SIM_EXIT -ne 0 ]]; then
  echo "SIMULATION FAILED (runtime exit $SIM_EXIT)"
  exit "$SIM_EXIT"
fi

if echo "$SIM_OUT" | grep -q "ALL TESTS PASSED" && ! echo "$SIM_OUT" | grep -q "FAILED:"; then
  echo "SIMULATION OK"
  exit 0
fi

if echo "$SIM_OUT" | grep -q "FAILED:"; then
  echo "SIMULATION FAILED (functional)"
  exit 1
fi

echo "SIMULATION INCONCLUSIVE (no verdict)"
echo "Hint: add check task and print ALL TESTS PASSED / FAILED: N errors for auto judgment."
echo "      Or review stdout and vcd_peek output manually."
exit 2
