---
name: icarus-verilog
description: >-
  Compile and simulate Verilog with Icarus Verilog (iverilog/vvp), parse testbench
  verdict strings, summarize VCD waveforms, triage TB vs RTL failures conservatively,
  and debug RTL. Use when working with .v/.sv files, iverilog, vvp, testbench, VCD,
  Verilog simulation, RTL debug, or blame assignment between testbench and design code.
---

# Icarus Verilog HDL Workflow

End-to-end: **compile → simulate → verdict → VCD peek → (on FAIL) triage → patch one side**.

## Mandatory tool discipline

- **bash** → `run_flow.sh` or `sim.sh` (not bare `iverilog/vvp`)
- **PowerShell** → `run_flow.ps1` or `sim.ps1`
- Use **`-OutName`** for unique `.vvp` artifacts; **`-Top`** only for `iverilog -s` module name
- After sim → **must** run `vcd_peek.py` when inspecting signals
- On functional FAIL → **must** run `fail_triage.py` **before** patching
- Patch **one file per iteration**; state `BLAME:` evidence first

## Quick start

```bash
bash skills/icarus-verilog/scripts/run_flow.sh \
  verilog/adder.v verilog/adder_tb.v verilog/build "" adder_tb \
  "a,b,sum,carry" "10,30" auto

powershell -File skills/icarus-verilog/scripts/run_flow.ps1 \
  -Rtl verilog/adder.v -Testbench verilog/adder_tb.v -WorkDir verilog/build \
  -OutName adder_tb -Signals "a,b,sum,carry" -Times "10,30"
```

### Same module name, different problems

When TB module is always `TopModule_tb` but files differ:

```bash
bash skills/icarus-verilog/scripts/sim.sh rtl.v prob027_tb.v build TopModule_tb Prob027_fadd_tb
# → build/Prob027_fadd_tb.vvp  (Top via -s, artifact via OutName)
```

## Simulation verdict (three states)

| Output | exit |
|--------|------|
| `SIMULATION OK` | 0 |
| `SIMULATION FAILED (functional)` | 1 |
| `SIMULATION INCONCLUSIVE (no verdict)` | 2 |

## TB vs RTL blame (conservative)

`fail_triage.py` **does not guess** reference models:

| `--model` | Behavior |
|-----------|----------|
| `auto` | Use adder/fadd **only with evidence** (e.g. `cin` in FAIL line); else INCONCLUSIVE |
| `adder` / `fadd` | Explicit reference model (user responsibility) |
| `none` | Wiring checks only; no spec-based RTL/TB blame |

**RTL blame requires:** `spec_applicable` AND spec == check ≠ DUT (all three agree on expected, DUT differs).

**Never blame RTL** when spec model is unknown or spec/check/DUT triangle conflicts.

## X/Z and sample timing

- **Verdict** (`sim.sh`): only TB `check()` at its call moment; does **not** scan VCD for X elsewhere.
- **TB pattern**: `stimulus → #delay → check()` so outputs settle before `!==` compare.
- **Triage**: FAIL line (`$time`, observed sum/carry) is **authoritative** for functional blame.
- **VCD**: point sample aligned to check inputs (`a`,`b` match FAIL line); not whole-run X scan.
- If VCD timestamp is post-assignment misaligned → skip VCD wiring hints; use FAIL line only.

```bash
python skills/icarus-verilog/scripts/fail_triage.py \
  --log sim.log --model auto
# VCD path read from "VCD: ..." line in log if --vcd omitted
```

## Acceptance G / H

| ID | Test | Expected |
|----|------|----------|
| **G** | TB wrong `check()` expected, RTL correct | `BLAME: TB` |
| **H** | Non-adder design with `--model auto` | `BLAME: INCONCLUSIVE`, no spec guess |

See [examples.md](examples.md).

## Exit conditions

- Max **5** compile-fix, **3** sim-fix rounds per blame target
- Same blame fails twice → switch hypothesis (RTL ↔ TB)
- Do not patch on INCONCLUSIVE verdict or inconclusive triage

## Additional resources

- [reference.md](reference.md)
- [examples.md](examples.md)
