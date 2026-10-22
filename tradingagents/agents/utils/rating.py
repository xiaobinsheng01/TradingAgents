"""Shared 5-tier rating vocabulary and a deterministic heuristic parser.

The same five-tier scale (Buy, Overweight, Hold, Underweight, Sell) is used by:
- The Research Manager (investment plan recommendation)
- The Portfolio Manager (final position decision)
- The signal processor (rating extracted for downstream consumers)
- The memory log (rating tag stored alongside each decision entry)

Centralising it here avoids drift between those call sites.

``extract_rating`` returns ``None`` when no rating can be found, so the graph can
surface an explicit ``REVIEW`` signal instead of a fabricated ``Hold`` (#1170).
``parse_rating`` keeps the legacy silent-default behaviour for callers (e.g. the
memory log) that need a rating string regardless.
"""

from __future__ import annotations

import re
import unicodedata

# Canonical, ordered 5-tier scale (most bullish to most bearish).
RATINGS_5_TIER: tuple[str, ...] = (
    "Buy", "Overweight", "Hold", "Underweight", "Sell",
)

# Signal emitted when the model's decision has no recognizable rating. It is not
# a tradeable position: it flags output that needs a human/re-run rather than
# silently degrading to Hold. Callers that map the signal onto the 5-tier enum
# (e.g. ``PortfolioRating(signal)``) should guard with ``is_review`` first.
RATING_REVIEW = "REVIEW"

_RATING_SET = {r.lower() for r in RATINGS_5_TIER}

# Matches "Rating: X" / "rating - X" / "Rating: **X**" — tolerates markdown
# bold wrappers and either a colon or hyphen separator.
_RATING_LABEL_RE = re.compile(r"rating.*?[:\-][\s*]*(\w+)", re.IGNORECASE)

# Standalone 5-tier word anywhere (word boundaries so "Buyer"/"Holding" don't match).
_RATING_WORD_RE = re.compile(
    r"\b(" + "|".join(RATINGS_5_TIER) + r")\b", re.IGNORECASE
)


def extract_rating(text: str) -> str | None:
    """Extract a 5-tier rating from prose, or ``None`` if none is present.

    Two-pass strategy on the NFKC-normalized text (so fullwidth punctuation like
    ``Rating：Overweight`` is matched the same as ASCII):
    1. An explicit "Rating: X" label (tolerant of markdown bold).
    2. The first standalone 5-tier rating word found anywhere.
    """
    if not text:
        return None
    norm = unicodedata.normalize("NFKC", text)

    for line in norm.splitlines():
        m = _RATING_LABEL_RE.search(line)
        if m and m.group(1).lower() in _RATING_SET:
            return m.group(1).capitalize()

    m = _RATING_WORD_RE.search(norm)
    if m:
        return m.group(1).capitalize()

    return None


def parse_rating(text: str, default: str = "Hold") -> str:
    """Extract a 5-tier rating, falling back to ``default`` when none is found.

    Legacy convenience wrapper: it always returns a rating string, so an
    unparseable decision silently becomes ``default`` (``Hold``). Callers that
    must distinguish "no rating" from a real Hold should use
    :func:`extract_rating` (or the graph's REVIEW-surfacing signal) instead.
    """
    rating = extract_rating(text)
    return rating if rating is not None else default


def is_review(signal: str) -> bool:
    """Whether a signal is the non-tradeable REVIEW sentinel (#1170)."""
    return signal == RATING_REVIEW


# A-share short-horizon tape writes this line. Downstream ratings must copy it
# so a later debate cannot turn a declined directional call into Buy/Sell.
# Overweight and Underweight count as directional hits; they are not allowed
# substitutes for this bias.
T1_BIAS_INSTRUCTION = (
    "If the market report contains `t1_bias: BUY`, `HOLD`, or `SELL`, that line "
    "is the next-session (T+1) research rating. Match it with Buy, Hold, or Sell, "
    "not Overweight or Underweight. It is not a broker order and not a 10-minute "
    "scalp. A 5–20 day comment may differ but must not replace that rating. "
    "When `trend_bias: SELL` appears (swing tape), the final labeled rating must "
    "not be more bullish than Hold; combine with `t1_bias` so a swing SELL blocks Buy. "
    "`Playbook stance` and `Market mood` already merged stock rules with全市场 "
    "breadth/regime; `material_stock_news: true` means个股 warehouse 利多/利空优先."
)

_T1_BIAS_RE = re.compile(r"t1_bias:\s*(BUY|HOLD|SELL)", re.IGNORECASE)
_TREND_BIAS_RE = re.compile(r"trend_bias:\s*(BUY|HOLD|SELL)", re.IGNORECASE)
_T1_RATING = {"BUY": "Buy", "HOLD": "Hold", "SELL": "Sell"}
_BIAS_ORDER = {"SELL": 0, "HOLD": 1, "BUY": 2}


def t1_bias_from_text(text: str | None) -> str | None:
    """Last ``t1_bias`` in ``text``, so an appended tape block wins over prose."""
    matches = _T1_BIAS_RE.findall(text or "")
    if not matches:
        return None
    return matches[-1].upper()


def trend_bias_from_text(text: str | None) -> str | None:
    """Last ``trend_bias`` in ``text`` (swing tape research stance)."""
    matches = _TREND_BIAS_RE.findall(text or "")
    if not matches:
        return None
    return matches[-1].upper()


def combine_deterministic_bias(
    t1_bias: str | None,
    trend_bias: str | None,
) -> str | None:
    """Merge T+1 playbook with swing trend; ``trend_bias: SELL`` caps bullish T+1."""
    if t1_bias is None and trend_bias is None:
        return None
    if trend_bias == "SELL" and t1_bias is not None:
        return min(t1_bias.upper(), "SELL", key=lambda item: _BIAS_ORDER[item])
    if t1_bias is not None:
        return t1_bias.upper()
    return trend_bias.upper() if trend_bias else None


def deterministic_bias_from_text(text: str | None) -> str | None:
    """Combined BUY/HOLD/SELL from ``t1_bias`` and ``trend_bias`` lines."""
    return combine_deterministic_bias(
        t1_bias_from_text(text),
        trend_bias_from_text(text),
    )


def enforce_t1_bias(text: str, market_report: str | None) -> str:
    """Rewrite a rendered decision so its rating label matches deterministic bias.

    Uses ``t1_bias`` when present; ``trend_bias: SELL`` prevents a Buy label when
    T+1 was BUY. No-op when the market report has no bias lines (non-A-share).
    The labeled rating is what memory and the signal parser store.
    """
    bias = deterministic_bias_from_text(market_report)
    if bias is None:
        return text or ""
    mapped = _T1_RATING[bias]
    body = text or ""
    body, n_rating = re.subn(r"(\*\*Rating\*\*:\s*)([A-Za-z]+)", rf"\g<1>{mapped}", body, count=1)
    body, n_rec = re.subn(
        r"(\*\*Recommendation\*\*:\s*)([A-Za-z]+)", rf"\g<1>{mapped}", body, count=1
    )
    body, n_action = re.subn(r"(\*\*Action\*\*:\s*)([A-Za-z]+)", rf"\g<1>{mapped}", body, count=1)
    body, n_final = re.subn(
        r"(FINAL TRANSACTION PROPOSAL:\s*\*\*)(BUY|HOLD|SELL)(\*\*)",
        lambda match: f"{match.group(1)}{bias}{match.group(3)}",
        body,
        count=1,
        flags=re.IGNORECASE,
    )
    if n_rating + n_rec + n_action + n_final == 0:
        body = f"**Rating**: {mapped}\n\n{body}"
    return body
