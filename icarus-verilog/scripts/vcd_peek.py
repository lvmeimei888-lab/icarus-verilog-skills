#!/usr/bin/env python3
"""Summarize VCD waveforms for agent-readable CLI output.

Parses standard VCD files (Icarus Verilog compatible). No third-party deps.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


def parse_timescale(header_lines: list[str]) -> tuple[float, str]:
    """Return (multiplier_to_ns, unit_suffix) from $timescale."""
    joined = " ".join(line.strip() for line in header_lines)
    m = re.search(r"\$timescale\s+(\d+)\s*(s|ms|us|ns|ps|fs)\s+\$end", joined)
    if m:
        value, unit = int(m.group(1)), m.group(2)
        to_ns = {
            "s": value * 1e9,
            "ms": value * 1e6,
            "us": value * 1e3,
            "ns": float(value),
            "ps": value / 1e3,
            "fs": value / 1e6,
        }[unit]
        return to_ns, unit
    return 1.0, "ns"


def parse_definitions(text: str) -> tuple[dict[str, str], dict[str, tuple[str, int]], float, str]:
    """Parse VCD header: id->names, name->(id,width), timescale."""
    header_end = text.index("$enddefinitions")
    header = text[:header_end]
    header_lines = header.splitlines()

    scale_ns, scale_unit = parse_timescale(header_lines)

    id_to_names: dict[str, list[str]] = {}
    name_meta: dict[str, tuple[str, int]] = {}
    scope_stack: list[str] = []

    for line in header_lines:
        line = line.strip()
        if line.startswith("$scope"):
            m = re.match(r"\$scope module (\S+) \$end", line)
            if m:
                scope_stack.append(m.group(1))
        elif line.startswith("$upscope"):
            if scope_stack:
                scope_stack.pop()
        elif line.startswith("$var"):
            # $var wire 8 ! sum [7:0] $end  OR  $var wire 1 " carry $end
            m = re.match(
                r"\$var\s+\w+\s+(\d+)\s+(\S+)\s+(\S+)(?:\s+\[[^\]]+\])?\s+\$end",
                line,
            )
            if not m:
                continue
            width = int(m.group(1))
            vid = m.group(2)
            name = m.group(3)
            scoped = ".".join(scope_stack + [name]) if scope_stack else name
            id_to_names.setdefault(vid, []).append(scoped)
            name_meta[name] = (vid, width)
            name_meta[scoped] = (vid, width)

    flat_id_to_name: dict[str, str] = {}
    for vid, names in id_to_names.items():
        flat_id_to_name[vid] = names[-1]

    return flat_id_to_name, name_meta, scale_ns, scale_unit


def parse_value_token(token: str, width: int) -> int:
    token = token.strip()
    if token.startswith("b"):
        bits = token[1:]
        if not bits:
            return 0
        lower = bits.lower()
        if "x" in lower:
            return -1
        if "z" in lower:
            return -2
        return int(bits, 2)
    if token in {"0", "1", "x", "X", "z", "Z"}:
        if token.lower() == "x":
            return -1
        if token.lower() == "z":
            return -2
        return int(token)
    return int(token)


def resolve_signal(name: str, name_meta: dict[str, tuple[str, int]]) -> tuple[str, int]:
    if name in name_meta:
        return name_meta[name]
    matches = [k for k in name_meta if k.endswith("." + name) or k == name]
    if len(matches) == 1:
        return name_meta[matches[0]]
    if len(matches) > 1:
        short = [m for m in matches if m.split(".")[-1] == name]
        if len(short) == 1:
            return name_meta[short[0]]
        raise KeyError(f"Ambiguous signal '{name}': {matches}")
    raise KeyError(f"Signal not found: {name}")


def format_value(val: int, width: int) -> str:
    if val == -1:
        return "x"
    if val == -2:
        return "z"
    if width == 1:
        return str(val)
    return str(val)


def apply_value_line(
    line: str,
    values: dict[str, int],
    id_to_name: dict[str, str],
) -> None:
    if line.startswith("b"):
        parts = line.split(maxsplit=1)
        if len(parts) < 2:
            return
        val = parse_value_token(parts[0], len(parts[0]) - 1)
        vid = parts[1]
    elif line and line[0] in "01xXzZ":
        val = parse_value_token(line[0], 1)
        vid = line[1:]
    else:
        return

    name = id_to_name.get(vid)
    if not name:
        return
    short = name.split(".")[-1]
    values[short] = val
    values[name] = val


def parse_changes(
    text: str,
    id_to_name: dict[str, str],
    name_meta: dict[str, tuple[str, int]],
    scale_ns: float,
) -> list[tuple[int, dict[str, int]]]:
    """Return list of (time_raw, {signal: value}) after each timestamp block."""
    del name_meta, scale_ns  # kept for API stability
    body = text[text.index("$enddefinitions") :]
    lines = body.splitlines()

    current_time = 0
    values: dict[str, int] = {}
    snapshots: list[tuple[int, dict[str, int]]] = []

    def record() -> None:
        snapshots.append((current_time, dict(values)))

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        if line.startswith("#"):
            current_time = int(line[1:])
            i += 1
            while i < len(lines):
                vline = lines[i].strip()
                if not vline or vline.startswith("#"):
                    break
                if vline.startswith("$"):
                    i += 1
                    continue
                apply_value_line(vline, values, id_to_name)
                i += 1
            record()
            continue
        if line.startswith("$"):
            i += 1
            continue
        apply_value_line(line, values, id_to_name)
        i += 1

    if not snapshots:
        record()
    return snapshots


def raw_to_display_time(raw: int, scale_ns: float) -> float:
    return raw * scale_ns


def raw_to_unit_time(raw: int, scale_ns: float) -> tuple[float, str]:
    ns = raw * scale_ns
    if ns >= 1e9:
        return ns / 1e9, "s"
    if ns >= 1e6:
        return ns / 1e6, "ms"
    if ns >= 1e3:
        return ns / 1e3, "us"
    if ns >= 1:
        return ns, "ns"
    return ns * 1e3, "ps"


def load_vcd(path: str | Path) -> tuple[str, dict[str, str], dict[str, tuple[str, int]], float, list[tuple[int, dict[str, int]]]]:
    """Load VCD and return (text, id_to_name, name_meta, scale_ns, snapshots)."""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    id_to_name, name_meta, scale_ns, _ = parse_definitions(text)
    snapshots = parse_changes(text, id_to_name, name_meta, scale_ns)
    return text, id_to_name, name_meta, scale_ns, snapshots


def fail_time_raw_to_ns(time_raw: int, scale_ns: float) -> float:
    """Convert FAIL @ $time (same units as VCD timestamps) to nanoseconds."""
    return time_raw * scale_ns


def find_check_sample_raw(
    snapshots: list[tuple[int, dict[str, int]]],
    fail_time_raw: int,
    a: int,
    b: int,
    cin: int | None = None,
) -> int | None:
    """Latest VCD timestamp at or before fail_time_raw where inputs match check() inputs.

    Skips misaligned snapshots (e.g. end-of-timestep after the next stimulus assignment).
    """
    best: int | None = None
    for snap_raw, vals in snapshots:
        if snap_raw > fail_time_raw:
            break
        if vals.get("a") != a or vals.get("b") != b:
            continue
        if cin is not None and vals.get("cin") != cin:
            continue
        best = snap_raw
    return best


def values_at_time_ns(
    vcd_path: str | Path,
    signals: list[str],
    time_ns: float,
) -> dict[str, str]:
    """Return formatted signal values at or before time_ns (point sample, not whole run)."""
    _, id_to_name, name_meta, scale_ns, snapshots = load_vcd(vcd_path)
    if not snapshots:
        raise ValueError("no waveform data in VCD")

    resolved: dict[str, tuple[str, int]] = {}
    for sig in signals:
        resolved[sig] = resolve_signal(sig, name_meta)

    target_raw = time_ns / scale_ns if scale_ns else time_ns
    best = snapshots[0]
    for snap in snapshots:
        if snap[0] <= target_raw:
            best = snap
        else:
            break

    _, vals = best
    out: dict[str, str] = {}
    for sig in signals:
        vid, width = resolved[sig]
        v = vals.get(sig)
        if v is None:
            scoped = id_to_name.get(vid, "")
            v = vals.get(scoped, 0)
        out[sig] = format_value(v, width)
    return out


def find_scoped_signals(name_meta: dict[str, tuple[str, int]], leaf: str, uut_prefix: str = "uut") -> dict[str, str]:
    """Return tb/uut scoped hierarchical names for a leaf signal."""
    result: dict[str, str] = {}
    for key in name_meta:
        if key.split(".")[-1] != leaf:
            continue
        parts = key.split(".")
        if uut_prefix in parts and parts.index(uut_prefix) == len(parts) - 2:
            result["uut"] = key
        elif uut_prefix not in parts:
            result.setdefault("tb", key)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize VCD signal values for agents.")
    parser.add_argument("--vcd", required=True, help="Path to VCD file")
    parser.add_argument("--signals", required=True, help="Comma-separated signal names")
    parser.add_argument("--times", default="", help="Comma-separated sample times in nanoseconds")
    parser.add_argument("--from", dest="time_from", type=float, default=None, help="Range start")
    parser.add_argument("--to", dest="time_to", type=float, default=None, help="Range end")
    args = parser.parse_args()

    vcd_path = Path(args.vcd)
    if not vcd_path.is_file():
        print(f"error: VCD file not found: {vcd_path}", file=sys.stderr)
        return 1

    text = vcd_path.read_text(encoding="utf-8", errors="replace")
    id_to_name, name_meta, scale_ns, _ = parse_definitions(text)

    signal_names = [s.strip() for s in args.signals.split(",") if s.strip()]
    resolved: dict[str, tuple[str, int]] = {}
    for sig in signal_names:
        try:
            resolved[sig] = resolve_signal(sig, name_meta)
        except KeyError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

    snapshots = parse_changes(text, id_to_name, name_meta, scale_ns)
    if not snapshots:
        print("error: no waveform data in VCD", file=sys.stderr)
        return 1

    sample_times: list[float] | None = None
    if args.times.strip():
        sample_times = [float(t.strip()) for t in args.times.split(",") if t.strip()]

    if sample_times is not None:
        for t in sample_times:
            target_raw = t / scale_ns if scale_ns else t
            best = snapshots[0]
            for snap in snapshots:
                if snap[0] <= target_raw:
                    best = snap
                else:
                    break
            _, vals = best
            t_val, t_unit = raw_to_unit_time(best[0], scale_ns)
            row: dict[str, str] = {}
            for sig in signal_names:
                vid, width = resolved[sig]
                v = vals.get(sig, vals.get(id_to_name.get(vid, ""), 0))
                row[sig] = format_value(v, width)
            parts = [f"t={t_val:g}{t_unit}"] + [f"{k}={v}" for k, v in row.items()]
            print("  ".join(parts))
        return 0

    printed = 0
    for raw, vals in snapshots:
        t_val, t_unit = raw_to_unit_time(raw, scale_ns)
        if args.time_from is not None and t_val < args.time_from:
            continue
        if args.time_to is not None and t_val > args.time_to:
            continue
        row_parts = [f"t={t_val:g}{t_unit}"]
        for sig in signal_names:
            vid, width = resolved[sig]
            v = vals.get(sig, vals.get(id_to_name.get(vid, ""), 0))
            row_parts.append(f"{sig}={format_value(v, width)}")
        print("  ".join(row_parts))
        printed += 1

    if printed == 0:
        print("error: no samples in requested time range", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
