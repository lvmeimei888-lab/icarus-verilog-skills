# Icarus Verilog Examples

## Example 1: run_flow (PASS)

```bash
bash skills/icarus-verilog/scripts/run_flow.sh \
  verilog/adder.v verilog/adder_tb.v verilog/build "" adder_tb \
  "a,b,sum,carry" "10,30"
```

Expected: `SIMULATION OK`, vcd_peek, `VCD:` line in output.

## Example 2: RTL bug (Acceptance F) → BLAME RTL

Change RTL: `assign {carry, sum} = a + b + 1;`

```bash
bash skills/icarus-verilog/scripts/sim.sh \
  verilog/adder.v verilog/adder_tb.v verilog/build "" adder_tb 2>&1 | tee verilog/build/sim.log

python skills/icarus-verilog/scripts/fail_triage.py \
  --log verilog/build/sim.log --model adder
```

Expected:

```
spec_applicable: True
BLAME: RTL
  - spec/check agree sum=30 but DUT sum=31
```

## Example 3: TB wrong expected (Acceptance G) → BLAME TB

RTL correct. In `adder_tb.v`, change one check call only:

```verilog
a = 8'd10; b = 8'd20; #10; check(8'd31, 1'b0);  // wrong: should be 30
```

```bash
bash skills/icarus-verilog/scripts/sim.sh \
  verilog/adder.v verilog/adder_tb.v verilog/build "" adder_tb 2>&1 | tee verilog/build/sim_tb_bug.log

python skills/icarus-verilog/scripts/fail_triage.py \
  --log verilog/build/sim_tb_bug.log --model adder
```

Expected:

```
BLAME: TB
  - DUT matches spec sum=30 but check() expected sum=31
```

**Must not** output `BLAME: RTL`.

## Example 4: Unknown design (Acceptance H) → INCONCLUSIVE

Sim log has FAIL lines but design is not adder/fadd (no `cin` in FAIL line):

```bash
python skills/icarus-verilog/scripts/fail_triage.py \
  --vcd build/Prob025_reduction.vcd --log build/sim.log --model auto
```

Expected:

```
spec_applicable: False (auto: no adder/fadd evidence...)
BLAME: INCONCLUSIVE
  - no applicable reference model; cannot blame RTL/TB via spec
```

## Example 5: TopModule_tb collision — use OutName

```bash
# Problem 027 — module inside file is TopModule_tb
bash skills/icarus-verilog/scripts/sim.sh \
  rtl/prob027.v tb/prob027_tb.v build TopModule_tb Prob027_fadd_tb

# Problem 025 — same module name, different artifact
bash skills/icarus-verilog/scripts/sim.sh \
  rtl/prob025.v tb/prob025_tb.v build TopModule_tb Prob025_tb
```

Each produces unique `.vvp`; VCD from `$dumpfile` in each TB.

## Example 6: Same module, explicit fadd

FAIL line includes cin:

```text
FAIL @ 10000: a=1 b=2 cin=1 sum=4 cout=0 expected sum=4 cout=0
```

`--model auto` selects fadd when `cin` is present.

## Example 7: X at check sample vs transient X

TB pattern (see `verilog/adder_tb.v`):

```verilog
a = 8'd10; b = 8'd20; #10; check(8'd30, 1'b0);  // settle, then sample
```

- If `sum` is X **only before** `#10` but stable at `check()` → **PASS** (not a FAIL).
- If `sum` is X **at** `check()` → FAIL line shows `sum=x`; triage → **INCONCLUSIVE** (manual review).
- `fail_triage` uses FAIL `@time` + matching `a,b`; does not fail because X appeared at t=0.
