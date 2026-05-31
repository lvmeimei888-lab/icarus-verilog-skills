#!/usr/bin/env python3
"""Triage functional sim failures: TB vs RTL blame hints.

Conservative: no reference model -> no RTL/TB blame via spec; wiring checks only.
X/z and numeric values are judged at check() sample moment (FAIL line), not if they
ever appeared elsewhere in the run. VCD is used only when aligned to that sample.
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import vcd_peek as vp  # noqa: E402


FAIL_SIMPLE_RE = re.compile(
    r"FAIL\s+@\s+(\d+)\s*:\s*a=\s*(\d+)\s+b=\s*(\d+)\s+sum=\s*(\S+)\s+carry=\s*(\S+)\s+"
    r"expected\s+sum=\s*(\S+)\s+carry=\s*(\S+)",
    re.IGNORECASE,
)

FAIL_FADD_RE = re.compile(
    r"FAIL\s+@\s+(\d+)\s*:\s*a=\s*(\d+)\s+b=\s*(\d+)\s+cin=\s*(\d+)\s+sum=\s*(\S+)\s+(?:carry|cout)=\s*(\S+)\s+"
    r"expected\s+sum=\s*(\S+)\s+(?:carry|cout)=\s*(\S+)",
    re.IGNORECASE,
)


@dataclass
class FailCase:
    time_raw: int
    a: int
    b: int
    cin: int | None
    sum_obs: str
    carry_obs: str
    sum_exp: str
    carry_exp: str


def read_log_text(path: Path) -> str:
    raw = path.read_bytes()
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16", errors="replace")
    return raw.decode("utf-8", errors="replace")


def parse_fail_lines(text: str) -> list[FailCase]:
    cases: list[FailCase] = []
    for line in text.splitlines():
        m = FAIL_FADD_RE.search(line)
        if m:
            cases.append(
                FailCase(
                    int(m.group(1)),
                    int(m.group(2)),
                    int(m.group(3)),
                    int(m.group(4)),
                    m.group(5),
                    m.group(6),
                    m.group(7),
                    m.group(8),
                )
            )
            continue
        m = FAIL_SIMPLE_RE.search(line)
        if m:
            cases.append(
                FailCase(
                    int(m.group(1)),
                    int(m.group(2)),
                    int(m.group(3)),
                    None,
                    m.group(4),
                    m.group(5),
                    m.group(6),
                    m.group(7),
                )
            )
    return cases


def parse_int_val(s: str) -> int | None:
    s = s.strip().lower()
    if s in {"x", "z"}:
        return None
    try:
        return int(s)
    except ValueError:
        return None


def spec_adder(a: int, b: int, width: int = 8) -> tuple[int, int]:
    total = a + b
    mask = (1 << width) - 1
    return total & mask, 1 if total > mask else 0


def spec_fadd(a: int, b: int, cin: int, width: int = 8) -> tuple[int, int]:
    total = a + b + cin
    mask = (1 << width) - 1
    return total & mask, 1 if total > mask else 0


def resolve_spec_model(model: str, cases: list[FailCase]) -> tuple[str | None, bool, str]:
    """Return (model_name, spec_applicable, reason)."""
    if model == "none":
        return None, False, "explicit --model none"
    if model == "adder":
        return "adder", True, "explicit --model adder"
    if model == "fadd":
        return "fadd", True, "explicit --model fadd"
    # auto: require evidence, do not guess
    if any(c.cin is not None for c in cases):
        return "fadd", True, "auto: cin present in FAIL line"
    return None, False, "auto: no adder/fadd evidence; use --model adder|fadd or --model none"


def compute_spec(
    spec_model: str | None,
    case: FailCase,
    width: int,
) -> tuple[int | None, int | None]:
    if not spec_model:
        return None, None
    cin = case.cin or 0
    if spec_model == "fadd":
        return spec_fadd(case.a, case.b, cin, width)
    return spec_adder(case.a, case.b, width)


def is_xz(val: str) -> bool:
    return val.strip().lower() in {"x", "z"}


def blame_case(
    case: FailCase,
    vcd_path: Path,
    width: int,
    uut_prefix: str,
    spec_model: str | None,
    spec_applicable: bool,
    spec_reason: str,
) -> dict:
    _, _, name_meta, scale_ns, snapshots = vp.load_vcd(vcd_path)
    time_ns = vp.fail_time_raw_to_ns(case.time_raw, scale_ns)

    sum_roles = vp.find_scoped_signals(name_meta, "sum", uut_prefix)
    carry_leaf = "cout" if any(k.endswith(".cout") for k in name_meta) else "carry"
    carry_roles = vp.find_scoped_signals(name_meta, carry_leaf, uut_prefix)

    # FAIL line = check() sample moment (authoritative for DUT vs check)
    tb_sum_v = case.sum_obs
    uut_sum_v = case.sum_obs
    tb_carry_v = case.carry_obs
    uut_carry_v = case.carry_obs
    vcd_aligned = False
    sample_ns = time_ns

    sample_raw = vp.find_check_sample_raw(
        snapshots, case.time_raw, case.a, case.b, case.cin
    )
    if sample_raw is not None:
        sample_ns = vp.fail_time_raw_to_ns(sample_raw, scale_ns)
        vcd_aligned = True
        if "tb" in sum_roles:
            try:
                tb_sum_v = vp.values_at_time_ns(vcd_path, [sum_roles["tb"]], sample_ns)[sum_roles["tb"]]
            except KeyError:
                pass
        if "uut" in sum_roles:
            try:
                uut_sum_v = vp.values_at_time_ns(vcd_path, [sum_roles["uut"]], sample_ns)[sum_roles["uut"]]
            except KeyError:
                pass
        if "tb" in carry_roles:
            try:
                tb_carry_v = vp.values_at_time_ns(vcd_path, [carry_roles["tb"]], sample_ns)[carry_roles["tb"]]
            except KeyError:
                pass
        if "uut" in carry_roles:
            try:
                uut_carry_v = vp.values_at_time_ns(vcd_path, [carry_roles["uut"]], sample_ns)[carry_roles["uut"]]
            except KeyError:
                pass

    spec_sum, spec_carry = compute_spec(spec_model, case, width)
    check_sum = parse_int_val(case.sum_exp)
    check_carry = parse_int_val(case.carry_exp)
    dut_sum = parse_int_val(case.sum_obs)
    dut_carry = parse_int_val(case.carry_obs)

    reasons: list[str] = [f"spec_model: {spec_model or 'none'} ({spec_reason})"]
    blame = "inconclusive"

    if not vcd_aligned:
        reasons.append(
            "VCD not aligned to check sample (FAIL line authoritative; not scanning whole run for X)"
        )

    # Wiring checks at check sample only (requires aligned VCD snapshot)
    if vcd_aligned and is_xz(tb_sum_v) and not is_xz(uut_sum_v):
        blame = "tb"
        reasons.append(f"at check sample: TB sum={tb_sum_v} but UUT sum={uut_sum_v} (likely port wiring)")
    elif (
        vcd_aligned
        and uut_sum_v != tb_sum_v
        and not is_xz(uut_sum_v)
        and not is_xz(tb_sum_v)
    ):
        blame = "tb"
        reasons.append(f"at check sample: TB sum={tb_sum_v} != UUT sum={uut_sum_v} (hierarchy mismatch)")
    elif is_xz(case.sum_obs) or is_xz(case.carry_obs):
        reasons.append("x/z at check() sample moment (FAIL line); manual review required")
    elif not spec_applicable:
        reasons.append("no applicable reference model; cannot blame RTL/TB via spec")
    elif dut_sum is None or check_sum is None or spec_sum is None:
        reasons.append("x/z or missing numeric values at check sample; manual review required")
    else:
        vals = {dut_sum, check_sum, spec_sum}
        if len(vals) == 3:
            blame = "inconclusive"
            reasons.append(f"conflicting evidence: dut={dut_sum} check={check_sum} spec={spec_sum}")
        elif spec_sum == check_sum and dut_sum != spec_sum:
            blame = "rtl"
            reasons.append(f"spec/check agree sum={spec_sum} but DUT sum={dut_sum}")
        elif dut_sum == spec_sum and check_sum != spec_sum:
            blame = "tb"
            reasons.append(f"DUT matches spec sum={spec_sum} but check() expected sum={check_sum}")
        elif (
            dut_carry is not None
            and check_carry is not None
            and spec_carry is not None
            and len({dut_carry, check_carry, spec_carry}) == 3
        ):
            blame = "inconclusive"
            reasons.append(
                f"conflicting carry evidence: dut={dut_carry} check={check_carry} spec={spec_carry}"
            )
        elif (
            dut_carry is not None
            and check_carry is not None
            and spec_carry is not None
            and spec_carry == check_carry
            and dut_carry != spec_carry
        ):
            blame = "rtl"
            reasons.append(f"spec/check agree carry={spec_carry} but DUT carry={dut_carry}")
        elif dut_carry == spec_carry and check_carry is not None and check_carry != spec_carry:
            blame = "tb"
            reasons.append(f"DUT matches spec carry={spec_carry} but check() expected carry={check_carry}")
        else:
            reasons.append("could not confidently separate TB vs RTL; review FAIL line and VCD")

    return {
        "time_ns": time_ns,
        "sample_ns": sample_ns,
        "vcd_aligned": vcd_aligned,
        "inputs": {"a": case.a, "b": case.b, "cin": case.cin},
        "observed_tb": {"sum": tb_sum_v, "carry": tb_carry_v},
        "observed_uut": {"sum": uut_sum_v, "carry": uut_carry_v},
        "check_expected": {"sum": case.sum_exp, "carry": case.carry_exp},
        "spec_expected": {"sum": spec_sum, "carry": spec_carry},
        "spec_applicable": spec_applicable,
        "blame": blame,
        "reasons": reasons,
    }


def parse_vcd_from_log(text: str) -> str | None:
    for line in text.splitlines():
        if line.startswith("VCD:"):
            path = line.split(":", 1)[1].strip()
            if path:
                return path
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="TB vs RTL blame triage for failed simulations.")
    parser.add_argument("--vcd", default="", help="Path to VCD file (optional if --log has VCD: line)")
    parser.add_argument("--log", default="", help="Sim stdout text file (or use --stdin)")
    parser.add_argument("--stdin", action="store_true", help="Read sim stdout from stdin")
    parser.add_argument("--width", type=int, default=8, help="Bus width for spec recompute")
    parser.add_argument("--uut-prefix", default="uut", help="DUT instance name in VCD hierarchy")
    parser.add_argument(
        "--model",
        choices=("auto", "none", "adder", "fadd"),
        default="auto",
        help="Reference model: auto (conservative), none, adder, or fadd",
    )
    args = parser.parse_args()

    if args.stdin:
        log_text = sys.stdin.read()
    elif args.log:
        log_text = read_log_text(Path(args.log))
    else:
        print("error: provide --log FILE or --stdin", file=sys.stderr)
        return 1

    vcd_path_str = args.vcd or parse_vcd_from_log(log_text) or ""
    if not vcd_path_str:
        print("error: VCD path required (--vcd or VCD: line in log)", file=sys.stderr)
        return 1
    vcd_path = Path(vcd_path_str)
    if not vcd_path.is_file():
        print(f"error: VCD not found: {vcd_path}", file=sys.stderr)
        return 1

    cases = parse_fail_lines(log_text)
    if not cases:
        print("error: no FAIL @ lines found in log", file=sys.stderr)
        return 1

    spec_model, spec_applicable, spec_reason = resolve_spec_model(args.model, cases)

    print("# Failure triage report")
    print(f"spec_applicable: {spec_applicable} ({spec_reason})")

    reports = []
    for i, case in enumerate(cases, 1):
        report = blame_case(
            case, vcd_path, args.width, args.uut_prefix, spec_model, spec_applicable, spec_reason
        )
        reports.append(report)
        print(f"\n## Failure {i} @ check {report['time_ns']:g}ns", end="")
        if report["vcd_aligned"]:
            print(f" (VCD sample {report['sample_ns']:g}ns)")
        else:
            print()
        print(f"inputs: a={report['inputs']['a']} b={report['inputs']['b']}", end="")
        if report["inputs"]["cin"] is not None:
            print(f" cin={report['inputs']['cin']}", end="")
        print()
        print(f"observed (FAIL line @ check): sum={case.sum_obs} carry={case.carry_obs}")
        if report["vcd_aligned"] and report["observed_tb"]["sum"] != case.sum_obs:
            print(f"observed_vcd_tb:  sum={report['observed_tb']['sum']} carry={report['observed_tb']['carry']}")
        if report["vcd_aligned"] and report["observed_uut"]["sum"] != case.sum_obs:
            print(f"observed_vcd_uut: sum={report['observed_uut']['sum']} carry={report['observed_uut']['carry']}")
        print(f"check_expect: sum={report['check_expected']['sum']} carry={report['check_expected']['carry']}")
        se = report["spec_expected"]
        print(f"spec_expect:  sum={se['sum']} carry={se['carry']}")
        print(f"BLAME: {report['blame'].upper()}")
        for r in report["reasons"]:
            print(f"  - {r}")

    first_blame = reports[0]["blame"]
    print(f"\n# Recommendation: patch {first_blame.upper()} first (one file per iteration)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
