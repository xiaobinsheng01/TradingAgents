"""缠论 structure from point-in-time OHLC. No vendor I/O.

Daily (or weekly) bars already fetched with ``date<=as-of`` are merged for
inclusion, then 分型 / 笔 / 线段 / 中枢. Missing structure is
``NO_DATA_AVAILABLE``; this module never invents prices or 买卖点.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

Direction = Literal["up", "down"]
FractalKind = Literal["top", "bottom"]

# Calendar span used when the swing window is too short for 笔/段.
CHANLUN_CALENDAR_DAYS = 250
_MIN_STROKE_GAP = 2


@dataclass(frozen=True)
class MergedBar:
    high: float
    low: float
    start_date: str
    end_date: str
    src_count: int


@dataclass(frozen=True)
class Fractal:
    kind: FractalKind
    index: int
    high: float
    low: float
    date: str


@dataclass(frozen=True)
class Stroke:
    direction: Direction
    start: Fractal
    end: Fractal
    high: float
    low: float
    confirmed: bool


@dataclass(frozen=True)
class Segment:
    direction: Direction
    start_date: str
    end_date: str
    high: float
    low: float
    stroke_count: int
    confirmed: bool


@dataclass(frozen=True)
class Hub:
    level: Literal["stroke", "segment"]
    zd: float
    zg: float
    start_date: str
    end_date: str


@dataclass(frozen=True)
class ChanlunSnapshot:
    merged_count: int
    fractals: tuple[Fractal, ...]
    strokes: tuple[Stroke, ...]
    segments: tuple[Segment, ...]
    hub: Hub | None
    position: str
    buy_sell: str | None
    last_close: float | None
    last_date: str | None


def _usable_bars(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        date = row.get("date")
        high = row.get("high")
        low = row.get("low")
        if not date or high is None or low is None:
            continue
        if high < low:
            continue
        out.append(row)
    out.sort(key=lambda item: item["date"])
    return out


def merge_inclusions(rows: list[dict[str, Any]]) -> list[MergedBar]:
    """K-line 包含关系. Direction comes from the last non-included pair."""
    bars = _usable_bars(rows)
    if not bars:
        return []
    merged: list[MergedBar] = [
        MergedBar(
            high=float(bars[0]["high"]),
            low=float(bars[0]["low"]),
            start_date=str(bars[0]["date"]),
            end_date=str(bars[0]["date"]),
            src_count=1,
        )
    ]
    direction: int = 0
    for raw in bars[1:]:
        last = merged[-1]
        high = float(raw["high"])
        low = float(raw["low"])
        date = str(raw["date"])
        contained = (high <= last.high and low >= last.low) or (
            high >= last.high and low <= last.low
        )
        if contained:
            if direction >= 0:
                new_high = max(high, last.high)
                new_low = max(low, last.low)
            else:
                new_high = min(high, last.high)
                new_low = min(low, last.low)
            merged[-1] = MergedBar(
                high=new_high,
                low=new_low,
                start_date=last.start_date,
                end_date=date,
                src_count=last.src_count + 1,
            )
            continue
        if high > last.high and low > last.low:
            direction = 1
        elif high < last.high and low < last.low:
            direction = -1
        merged.append(
            MergedBar(
                high=high,
                low=low,
                start_date=date,
                end_date=date,
                src_count=1,
            )
        )
    return merged


def find_fractals(merged: list[MergedBar]) -> list[Fractal]:
    """Confirmed 分型 only: the right wing must already be closed."""
    out: list[Fractal] = []
    if len(merged) < 3:
        return out
    for i in range(1, len(merged) - 1):
        left, mid, right = merged[i - 1], merged[i], merged[i + 1]
        is_top = mid.high > left.high and mid.high > right.high
        is_bottom = mid.low < left.low and mid.low < right.low
        if is_top == is_bottom:
            continue
        kind: FractalKind = "top" if is_top else "bottom"
        out.append(
            Fractal(
                kind=kind,
                index=i,
                high=mid.high,
                low=mid.low,
                date=mid.end_date if kind == "top" else mid.start_date,
            )
        )
    return out


def _more_extreme(current: Fractal, candidate: Fractal) -> Fractal:
    if current.kind != candidate.kind:
        return current
    if current.kind == "top":
        return candidate if candidate.high >= current.high else current
    return candidate if candidate.low <= current.low else current


def build_strokes(
    merged: list[MergedBar], fractals: list[Fractal]
) -> list[Stroke]:
    if not fractals:
        return []
    chosen: list[Fractal] = [fractals[0]]
    for frac in fractals[1:]:
        last = chosen[-1]
        if frac.kind == last.kind:
            chosen[-1] = _more_extreme(last, frac)
            continue
        if frac.index - last.index < _MIN_STROKE_GAP:
            continue
        chosen.append(frac)
    strokes: list[Stroke] = []
    for i in range(len(chosen) - 1):
        start, end = chosen[i], chosen[i + 1]
        if start.kind == end.kind:
            continue
        if start.kind == "bottom" and end.kind == "top":
            direction: Direction = "up"
        elif start.kind == "top" and end.kind == "bottom":
            direction = "down"
        else:
            continue
        strokes.append(
            Stroke(
                direction=direction,
                start=start,
                end=end,
                high=max(start.high, end.high),
                low=min(start.low, end.low),
                confirmed=True,
            )
        )
    if not chosen or not merged:
        return strokes
    last_frac = chosen[-1]
    last_bar = merged[-1]
    if last_bar.end_date == last_frac.date:
        return strokes
    if last_frac.kind == "bottom" and last_bar.high > last_frac.high:
        tentative = Fractal(
            kind="top",
            index=len(merged) - 1,
            high=last_bar.high,
            low=last_bar.low,
            date=last_bar.end_date,
        )
        strokes.append(
            Stroke(
                direction="up",
                start=last_frac,
                end=tentative,
                high=max(last_frac.high, tentative.high),
                low=min(last_frac.low, tentative.low),
                confirmed=False,
            )
        )
    elif last_frac.kind == "top" and last_bar.low < last_frac.low:
        tentative = Fractal(
            kind="bottom",
            index=len(merged) - 1,
            high=last_bar.high,
            low=last_bar.low,
            date=last_bar.end_date,
        )
        strokes.append(
            Stroke(
                direction="down",
                start=last_frac,
                end=tentative,
                high=max(last_frac.high, tentative.high),
                low=min(last_frac.low, tentative.low),
                confirmed=False,
            )
        )
    return strokes


def _feature_merge(strokes: list[Stroke]) -> list[Stroke]:
    """Inclusion merge on 特征序列 (reverse strokes treated as bars)."""
    if not strokes:
        return []
    merged = [strokes[0]]
    direction = 0
    for stroke in strokes[1:]:
        last = merged[-1]
        contained = (stroke.high <= last.high and stroke.low >= last.low) or (
            stroke.high >= last.high and stroke.low <= last.low
        )
        if contained:
            if direction >= 0:
                high = max(stroke.high, last.high)
                low = max(stroke.low, last.low)
            else:
                high = min(stroke.high, last.high)
                low = min(stroke.low, last.low)
            merged[-1] = Stroke(
                direction=last.direction,
                start=last.start,
                end=stroke.end,
                high=high,
                low=low,
                confirmed=last.confirmed and stroke.confirmed,
            )
            continue
        if stroke.high > last.high and stroke.low > last.low:
            direction = 1
        elif stroke.high < last.high and stroke.low < last.low:
            direction = -1
        merged.append(stroke)
    return merged


def build_segments(strokes: list[Stroke]) -> list[Segment]:
    confirmed = [item for item in strokes if item.confirmed]
    if len(confirmed) < 3:
        return []
    segments: list[Segment] = []
    start = 0
    while start <= len(confirmed) - 3:
        remaining = confirmed[start:]
        seg_dir = remaining[0].direction
        reverse = [item for item in remaining[1:] if item.direction != seg_dir]
        features = _feature_merge(reverse)
        end_idx: int | None = None
        if len(features) >= 3:
            for i in range(1, len(features) - 1):
                left, mid, right = features[i - 1], features[i], features[i + 1]
                if seg_dir == "up":
                    is_top = mid.high > left.high and mid.high > right.high
                    broken = is_top and right.low < mid.low
                else:
                    is_bottom = mid.low < left.low and mid.low < right.low
                    broken = is_bottom and right.high > mid.high
                if not broken:
                    continue
                # Segment ends at the extreme of the middle feature's start
                # (the 笔 that printed the 线段 high/low).
                for j, stroke in enumerate(remaining):
                    if stroke.end.date == mid.start.date or stroke.start.date == mid.start.date:
                        end_idx = j
                        break
                if end_idx is None:
                    end_idx = max(2, len(remaining) - 2)
                break
        if end_idx is None or end_idx < 2:
            piece = remaining
            segments.append(
                _segment_from_strokes(piece, confirmed=False)
            )
            break
        piece = remaining[: end_idx + 1]
        segments.append(_segment_from_strokes(piece, confirmed=True))
        start += max(end_idx, 1)
    return segments


def _segment_from_strokes(strokes: list[Stroke], *, confirmed: bool) -> Segment:
    highs = [item.high for item in strokes]
    lows = [item.low for item in strokes]
    return Segment(
        direction=strokes[0].direction,
        start_date=strokes[0].start.date,
        end_date=strokes[-1].end.date,
        high=max(highs),
        low=min(lows),
        stroke_count=len(strokes),
        confirmed=confirmed,
    )


def _hub_from_ranges(
    ranges: list[tuple[float, float, str, str]],
    level: Literal["stroke", "segment"],
) -> Hub | None:
    if len(ranges) < 3:
        return None
    last_three = ranges[-3:]
    zg = min(item[0] for item in last_three)
    zd = max(item[1] for item in last_three)
    if zg <= zd:
        return None
    return Hub(
        level=level,
        zd=round(zd, 4),
        zg=round(zg, 4),
        start_date=last_three[0][2],
        end_date=last_three[-1][3],
    )


def find_hub(strokes: list[Stroke], segments: list[Segment]) -> Hub | None:
    confirmed_segs = [item for item in segments if item.confirmed]
    hub = _hub_from_ranges(
        [(item.high, item.low, item.start_date, item.end_date) for item in confirmed_segs],
        "segment",
    )
    if hub is not None:
        return hub
    confirmed = [item for item in strokes if item.confirmed]
    return _hub_from_ranges(
        [
            (item.high, item.low, item.start.date, item.end.date)
            for item in confirmed
        ],
        "stroke",
    )


def _position(close: float | None, hub: Hub | None) -> str:
    if hub is None or close is None:
        return "no_hub"
    if close > hub.zg:
        return "above_hub"
    if close < hub.zd:
        return "below_hub"
    return "in_hub"


def _buy_sell(
    strokes: list[Stroke], hub: Hub | None, close: float | None, position: str
) -> str | None:
    """Only 三类 candidates: leave a hub then pull back without re-entering."""
    if hub is None or close is None or not strokes:
        return None
    last = strokes[-1]
    if position == "above_hub" and last.direction == "down" and close >= hub.zg:
        return "三类买点候选"
    if position == "below_hub" and last.direction == "up" and close <= hub.zd:
        return "三类卖点候选"
    return None


def analyze_chanlun(rows: list[dict[str, Any]]) -> ChanlunSnapshot:
    usable = _usable_bars(rows)
    last_close = None
    last_date = None
    if usable:
        last_close = usable[-1].get("close")
        last_date = str(usable[-1]["date"])
        if last_close is None:
            last_close = usable[-1].get("high")
    merged = merge_inclusions(usable)
    fractals = find_fractals(merged)
    strokes = build_strokes(merged, fractals)
    segments = build_segments(strokes)
    hub = find_hub(strokes, segments)
    position = _position(last_close, hub)
    return ChanlunSnapshot(
        merged_count=len(merged),
        fractals=tuple(fractals),
        strokes=tuple(strokes),
        segments=tuple(segments),
        hub=hub,
        position=position,
        buy_sell=_buy_sell(strokes, hub, last_close, position),
        last_close=None if last_close is None else round(float(last_close), 4),
        last_date=last_date,
    )


def aggregate_weekly(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """True weekly OHLC (not last daily print of the week)."""
    buckets: dict[str, list[dict[str, Any]]] = {}
    for row in _usable_bars(rows):
        week = datetime.strptime(str(row["date"]), "%Y-%m-%d").strftime("%G-W%V")
        buckets.setdefault(week, []).append(row)
    weekly: list[dict[str, Any]] = []
    for week in sorted(buckets):
        group = buckets[week]
        highs = [float(item["high"]) for item in group]
        lows = [float(item["low"]) for item in group]
        first, last = group[0], group[-1]
        weekly.append(
            {
                "date": last["date"],
                "open": first.get("open"),
                "high": max(highs),
                "low": min(lows),
                "close": last.get("close"),
            }
        )
    return weekly


def _stroke_line(stroke: Stroke) -> str:
    mark = "" if stroke.confirmed else " (延伸中)"
    return (
        f"{stroke.start.date} {stroke.direction} {stroke.start.kind} "
        f"{stroke.start.low if stroke.direction == 'up' else stroke.start.high} -> "
        f"{stroke.end.date} {stroke.end.kind} "
        f"{stroke.end.high if stroke.direction == 'up' else stroke.end.low}"
        f"{mark}"
    )


def render_chanlun_markdown(
    rows: list[dict[str, Any]],
    *,
    as_of: str,
    ticker: str,
    timeframe: str = "daily",
) -> str:
    """Markdown 缠论 block. Empty structure does not invent 笔/中枢/买卖点."""
    snapshot = analyze_chanlun(rows)
    title = f"缠论 ({timeframe}, as-of {as_of})"
    if snapshot.merged_count < 5 or not snapshot.strokes:
        return (
            f"## {title}\n\n"
            f"NO_DATA_AVAILABLE: not enough confirmed 分型/笔 for {ticker} "
            f"as-of {as_of} on {timeframe} bars. Do not invent 中枢 or 买卖点."
        )
    last_strokes = snapshot.strokes[-6:]
    last_segments = snapshot.segments[-4:]
    hub_lines: list[str]
    if snapshot.hub is None:
        hub_lines = [
            "hub: NO_DATA_AVAILABLE (no overlapping 三笔/三段 中枢). "
            "Do not invent ZD/ZG."
        ]
    else:
        hub = snapshot.hub
        hub_lines = [
            f"hub_level: {hub.level}",
            f"hub_zd: {hub.zd}",
            f"hub_zg: {hub.zg}",
            f"hub_span: {hub.start_date} to {hub.end_date}",
            f"position: {snapshot.position}",
        ]
    buy_sell = snapshot.buy_sell or "none"
    lines = [
        f"## {title}",
        "缠中说禅 structure from closed bars only. Research rating, not an order. "
        "Do not invent missing 分型, 笔, 线段, 中枢, or 买卖点.",
        f"- last_close: {snapshot.last_close}",
        f"- last_date: {snapshot.last_date}",
        f"- merged_bars: {snapshot.merged_count}",
        f"- fractals: {len(snapshot.fractals)}",
        f"- strokes: {len(snapshot.strokes)} "
        f"(confirmed {sum(1 for item in snapshot.strokes if item.confirmed)})",
        f"- segments: {len(snapshot.segments)} "
        f"(confirmed {sum(1 for item in snapshot.segments if item.confirmed)})",
        *[f"- {line}" for line in hub_lines],
        f"- buy_sell: {buy_sell}",
        "",
        "### Recent 笔",
    ]
    lines.extend(f"- {_stroke_line(item)}" for item in last_strokes)
    if last_segments:
        lines.extend(["", "### Recent 线段"])
        for seg in last_segments:
            mark = "" if seg.confirmed else " (未完成)"
            lines.append(
                f"- {seg.start_date} {seg.direction} {seg.low}->{seg.high} "
                f"{seg.end_date} ({seg.stroke_count} 笔){mark}"
            )
    return "\n".join(lines)
