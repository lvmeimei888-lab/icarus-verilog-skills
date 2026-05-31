# Icarus Verilog Reference

## sim.sh / sim.ps1 parameters

| Param | Purpose |
|-------|---------|
| `RTL`, `TB`, `WorkDir` | Inputs |
| `TOP_MODULE` / `-Top` | Optional `iverilog -s` (module name only) |
| `OUT_NAME` / `-OutName` | `.vvp` base name; **default = TB filename** |

**Decoupling:** three TBs all `module TopModule_tb` → use same `-Top TopModule_tb` but different `-OutName Prob025_tb` etc.

## VCD path

Sim scripts parse stdout:

```text
VCD info: dumpfile adder.vcd opened for output.
...
VCD: D:\...\verilog\build\adder.vcd
```

`run_flow` and `fail_triage` read the `VCD:` line — **not** directory mtime.

## fail_triage models

| `--model` | spec_applicable | RTL blame via spec |
|-----------|-----------------|-------------------|
| `auto` | only with cin evidence or explicit pattern | conservative |
| `adder` | yes | if spec==check≠dut |
| `fadd` | yes | if spec==check≠dut |
| `none` | no | never (wiring only) |

Triangle conflict (dut ≠ check ≠ spec all different) → **INCONCLUSIVE**.

## X/Z and check sample moment

| Layer | X handling |
|-------|------------|
| TB `check()` | `!==` only at call; transient X elsewhere ignored |
| `sim.sh` verdict | No VCD scan; PASS if all checks pass |
| `vcd_peek.py` | Point sample at `--times` (not "ever had X") |
| `fail_triage.py` | FAIL line = check sample; VCD aligned by matching `a`,`b` at ≤ FAIL `@time` |

Misaligned VCD (same timestamp as next stimulus) → triage uses FAIL line only.

## TB vs RTL blame table

| Evidence | Blame |
|----------|-------|
| TB sum z/x at check sample, UUT valid | TB |
| TB net ≠ UUT at check sample | TB |
| spec==check≠dut (spec applicable) | RTL |
| dut==spec≠check | TB |
| no spec model / auto without evidence | INCONCLUSIVE |
| dut≠check≠spec | INCONCLUSIVE |

## Acceptance checklist

```
G. TB wrong expected → BLAME: TB (not RTL)
H. --model auto on non-adder FAIL → BLAME: INCONCLUSIVE
F. RTL +1 bug with --model adder → BLAME: RTL
```

## Script exit codes

| Code | Meaning |
|------|---------|
| 0 | SIMULATION OK |
| 1 | Functional FAIL |
| 2 | INCONCLUSIVE (no verdict) |

## Manual compile (debug only)

```bash
iverilog -g2012 -Wall -s TopModule_tb -o build/my_out.vvp rtl.v tb.v
```

Prefer `sim.sh` for verdict parsing and VCD line output.
