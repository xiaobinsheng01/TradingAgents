"""Same-day Shanghai/Shenzhen main-board screen for the local console.

Scans the public gainers list, speed list, and industry-board leaders, then
attaches the existing T+1 playbook and disclosed buy/sell labels. ChiNext,
STAR, and Beijing listings are dropped before ranking. This is a research
snapshot for the loopback UI, not a broker order and not a quote API.
Historical dates are refused so today's board cannot be labeled as the past.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from .akshare_flow import _change_side, _row_code, _row_date, _to_float, _yyyymmdd
from .akshare_market import (
    _LIMIT_EPS,
    _cached,
    _fetch_daily,
    _fetch_dt_pool,
    _fetch_index_daily,
    _fetch_prev_zt,
    _fetch_zt_pool,
    _index_ret,
    _is_st_name,
    _last_amount,
    _mean_float,
    _row_ohlc,
    _to_date,
    _try_ak_records,
)
from .akshare_news import _field, _load_akshare
from .ashare_playbook import (
    WATCH_ZONE_LOW,
    build_playbook_stance,
    combine_market_amount,
    resolve_regime,
)
from .config import get_config
from .news_store import GLOBAL_KEY
from .symbol_utils import a_share_board_type, a_share_code, a_share_limit_pct

logger = logging.getLogger(__name__)

GAIN_LIMIT = 20
SPEED_LIMIT = 15
ROW_CAP = 30
INSIDER_LOOKBACK_DAYS = 30
BAR_LOOKBACK_DAYS = 120
BAR_LIMIT = 60
# Full-market 增减持 regularly exceeds the shared 30s cap and holds the page.
SCREEN_INSIDER_TIMEOUT = 8

_SHAPE_ZH = {
    "turnover_board": "换手板",
    "one_word": "一字板",
    "t_board": "T字板",
    "failed_board": "炸板",
    "none": "未封板",
}
_REGIME_ZH = {
    "high": "高容错",
    "neutral": "中性",
    "low": "低容错",
    "unknown": "容错未知",
}
_SOURCE_ZH = {"gain": "涨幅", "speed": "涨速", "leader": "领涨"}


class ScreenNotLiveError(ValueError):
    """The public gainers and speed boards are a same-day print only."""


def _utc_today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _coerce_day(as_of: str | None) -> str:
    if as_of is None or not str(as_of).strip():
        return _utc_today()
    text = str(as_of).strip()
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError as e:
        raise ValueError("as_of must be YYYY-MM-DD") from e
    return text


def _require_today(day: str) -> None:
    if day != _utc_today():
        raise ScreenNotLiveError(
            "涨幅榜和涨速榜只在当天可用。历史日期不能把此刻的榜单当成当天行情。"
        )


def bars_from_daily(rows: list[dict], as_of: str) -> list[dict[str, Any]]:
    """Unique ascending daily bars on or before ``as_of``. Last ``BAR_LIMIT`` kept."""
    by_date: dict[str, dict[str, Any]] = {}
    for row in rows:
        item = _row_ohlc(row)
        date = item.get("date")
        if not date or date > as_of:
            continue
        open_, high, low, close = item.get("open"), item.get("high"), item.get("low"), item.get("close")
        if None in (open_, high, low, close):
            continue
        by_date[date] = {
            "time": date,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": item.get("volume"),
        }
    ordered = [by_date[key] for key in sorted(by_date)]
    return ordered[-BAR_LIMIT:]


def screen_price_bars(ticker: str, as_of: str | None = None) -> dict[str, Any]:
    """Recent daily OHLC for one A-share name (ChiNext excluded). Research chart, not an order."""
    day = _coerce_day(as_of)
    if day > _utc_today():
        raise ValueError("as_of cannot be in the future")
    code = a_share_code(ticker or "")
    if code is None:
        raise ValueError("ticker must be a China A-share code")
    if a_share_board_type(code) == "chinext":
        raise ValueError("创业板不进日K")
    ak = _load_akshare()
    start = (datetime.strptime(day, "%Y-%m-%d") - timedelta(days=BAR_LOOKBACK_DAYS)).strftime(
        "%Y-%m-%d"
    )
    try:
        rows = _fetch_daily(ak, code, start, day, "")
    except TimeoutError as e:
        logger.warning("A-share screen bars timed out for %s: %s", code, e)
        rows = []
    return {
        "ticker": screen_ticker(code),
        "as_of": day,
        "bars": bars_from_daily(rows, day),
        "note": "日K用于观察价量，不是委托。",
    }


def _ttl_seconds() -> int:
    ttl = get_config().get("news_telegraph_ttl_seconds", 120)
    try:
        return int(ttl) if ttl is not None else 120
    except (TypeError, ValueError):
        return 120


def screen_ticker(code: str) -> str:
    """Broker suffix kept for the existing run form (``.SH`` / ``.SZ``)."""
    if code[0] in "03":
        return f"{code}.SZ"
    return f"{code}.SH"


def _is_main_board(code: str, name: str) -> bool:
    return a_share_board_type(code, is_st=_is_st_name(name)) == "main"


def _is_no_chinext(code: str, name: str) -> bool:
    if _is_st_name(name):
        return False
    return a_share_board_type(code, is_st=False) != "chinext"


def _universe_eligible(universe: str, code: str, name: str) -> bool:
    if universe == "main":
        return _is_main_board(code, name)
    if universe == "no_chinext":
        return _is_no_chinext(code, name)
    raise ValueError(f"unknown screen universe: {universe}")


def _spot_code(raw: str) -> str | None:
    """Six-digit code from a bare cell or a Sina ``sh`` / ``sz`` / ``bj`` symbol."""
    text = str(raw or "").strip()
    lowered = text.lower()
    for prefix in ("sh", "sz", "bj"):
        if not lowered.startswith(prefix):
            continue
        rest = lowered[len(prefix) :]
        if len(rest) == 6 and rest.isdigit():
            text = rest
            break
    return a_share_code(text)


def _pct(row: dict) -> float | None:
    return _to_float(_field(row, ("涨跌幅", "pct_chg", "最新涨跌幅")))


def _speed(row: dict) -> float | None:
    return _to_float(_field(row, ("涨速", "speed")))


def _quote(row: dict, code: str, name: str) -> dict[str, Any]:
    high = _to_float(_field(row, ("最高", "high")))
    low = _to_float(_field(row, ("最低", "low")))
    preclose = _to_float(_field(row, ("昨收", "昨收价", "preclose")))
    amplitude = _to_float(_field(row, ("振幅", "amplitude")))
    if amplitude is None and high is not None and low is not None and preclose not in (None, 0):
        amplitude = (high - low) / preclose * 100.0
    return {
        "code": code,
        "name": name,
        "pct_chg": _pct(row),
        "speed": _speed(row),
        "pct_5m": _to_float(_field(row, ("5分钟涨跌", "五分钟涨跌"))),
        "turnover": _to_float(_field(row, ("换手率", "turnover"))),
        "volume_ratio": _to_float(_field(row, ("量比",))),
        "amount": _to_float(_field(row, ("成交额", "amount"))),
        "amplitude": amplitude,
        "float_mv": _to_float(_field(row, ("流通市值",))),
        "last": _to_float(_field(row, ("最新价", "最新", "close"))),
        "open": _to_float(_field(row, ("今开", "开盘", "open"))),
        "high": high,
        "low": low,
        "preclose": preclose,
    }


def _indexed_spot(rows: list[dict], *, universe: str = "main") -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for row in rows:
        code = _spot_code(_field(row, ("代码", "股票代码", "证券代码")) or "")
        if code is None:
            continue
        name = _field(row, ("名称", "股票名称", "证券简称")) or code
        if not _universe_eligible(universe, code, name):
            continue
        found[code] = _quote(row, code, name)
    return found


def _leader_identity(text: str) -> tuple[str | None, str]:
    """Return a six-digit code when the cell contains one, plus the leftover name."""
    digits = "".join(ch if ch.isdigit() else " " for ch in text).split()
    code = next((item for item in digits if len(item) == 6 and a_share_code(item)), None)
    name = text
    if code:
        name = text.replace(code, " ")
    name = " ".join(name.replace("（", " ").replace("）", " ").split())
    return code, name


def _match_leader(
    spot: dict[str, dict[str, Any]], cell: str, *, universe: str = "main"
) -> dict[str, Any] | None:
    """Use the named leader only when that listing passes the screen universe.

    A leader outside the universe is skipped. The next eligible name in the
    same sector is not promoted into the front row.
    """
    code, name = _leader_identity(cell)
    if code is not None:
        if not _universe_eligible(universe, code, name):
            return None
        return spot.get(code)
    if not name:
        return None
    matches = [row for row in spot.values() if row["name"] == name]
    if len(matches) != 1:
        return None
    return matches[0]


def select_candidates(
    spot_rows: list[dict],
    leader_rows: list[dict],
    *,
    universe: str = "main",
) -> list[dict[str, Any]]:
    """Eligible names in the watch zone, capped after the three lists merge."""
    spot = _indexed_spot(spot_rows, universe=universe)
    ranked = [row for row in spot.values() if (row.get("pct_chg") or -999) >= WATCH_ZONE_LOW]
    by_gain = sorted(ranked, key=lambda row: row["pct_chg"], reverse=True)[:GAIN_LIMIT]
    by_speed = sorted(
        [row for row in ranked if row.get("speed") is not None],
        key=lambda row: row["speed"],
        reverse=True,
    )[:SPEED_LIMIT]

    chosen: dict[str, dict[str, Any]] = {}

    def add(row: dict[str, Any], source: str, sector: str | None = None) -> None:
        item = chosen.get(row["code"])
        if item is None:
            item = {**row, "sources": [], "sector": None, "is_sector_leader": False}
            chosen[row["code"]] = item
        if source not in item["sources"]:
            item["sources"].append(source)
        if sector:
            item["sector"] = sector
            item["is_sector_leader"] = True

    for row in by_gain:
        add(row, "gain")
    for row in by_speed:
        add(row, "speed")
    for raw in leader_rows:
        cell = _field(raw, ("领涨股票", "领涨股"))
        if not cell:
            continue
        match = _match_leader(spot, cell, universe=universe)
        if match is None or (match.get("pct_chg") or -999) < WATCH_ZONE_LOW:
            continue
        sector = _field(raw, ("板块名称", "行业", "板块", "名称")) or None
        add(match, "leader", sector)

    ordered = sorted(chosen.values(), key=lambda row: row["pct_chg"], reverse=True)
    return ordered[:ROW_CAP]


def _pool_streak(zt_rows: list[dict], code: str) -> int:
    for row in zt_rows:
        if _row_code(row) != code:
            continue
        raw = _field(row, ("连板数", "连板", "几天几板", "封板天数"))
        digits = "".join(ch if ch.isdigit() else " " for ch in raw).split()
        if digits:
            return int(digits[-1])
        return 1
    return 0


def _quote_bar(quote: dict[str, Any], as_of: str) -> dict[str, Any]:
    code = quote["code"]
    limit = a_share_limit_pct(code, as_of, is_st=False)
    pre = quote.get("preclose")
    high = quote.get("high")
    pct = quote.get("pct_chg")
    limit_up = bool(pct is not None and pct >= limit - _LIMIT_EPS)
    touched = bool(
        limit_up
        or (
            high is not None
            and pre not in (None, 0)
            and high >= pre * (1 + (limit - _LIMIT_EPS) / 100.0)
        )
    )
    return {
        "date": as_of,
        "open": quote.get("open"),
        "high": high,
        "low": quote.get("low"),
        "close": quote.get("last"),
        "preclose": pre,
        "pct_chg": pct,
        "amplitude": quote.get("amplitude"),
        "limit_up": limit_up,
        "touched_limit_up": touched,
        "limit_pct": limit,
    }


def _stance_rows(quote: dict[str, Any], as_of: str, streak: int) -> list[dict[str, Any]]:
    bar = _quote_bar(quote, as_of)
    if bar["limit_up"] and streak < 1:
        streak = 1
    if not bar["limit_up"]:
        streak = 0
    pads = max(streak - 1, 0)
    rows: list[dict[str, Any]] = []
    for i in range(pads):
        rows.append({**bar, "date": f"1900-01-{i + 1:02d}", "limit_up": True, "touched_limit_up": True})
    rows.append(bar)
    return rows


def _signed(value: float | None, up: str, down: str) -> str:
    if value is None:
        return "不可用"
    if value > 0:
        return up
    if value < 0:
        return down
    return "持平"


def _stamp(row: dict) -> str | None:
    return _row_date(row) or _to_date(_field(row, ("信用交易日期",)))


def _latest_by_code(rows: list[dict], codes: set[str], as_of: str, start: str) -> dict[str, dict]:
    found: dict[str, dict] = {}
    for row in rows:
        code = _row_code(row)
        if code not in codes:
            continue
        stamp = _stamp(row)
        if stamp is None or not start <= stamp <= as_of:
            continue
        previous = found.get(code)
        if previous is None or stamp >= (_stamp(previous) or ""):
            found[code] = row
    return found


def _seat_side(row: dict | None) -> tuple[str, float | None, str, str]:
    if not row:
        return "不可用", None, "", ""
    buy = _to_float(_field(row, ("机构买入总额", "机构买入额", "买入额", "龙虎榜买入额")))
    sell = _to_float(_field(row, ("机构卖出总额", "机构卖出额", "卖出额", "龙虎榜卖出额")))
    net = _to_float(_field(row, ("机构买入净额", "龙虎榜净买额", "净额")))
    if net is None and (buy is not None or sell is not None):
        net = (buy or 0.0) - (sell or 0.0)
    side = _signed(net, "席位净买", "席位净卖")
    buyers = _field(row, ("买方机构数",))
    sellers = _field(row, ("卖方机构数",))
    top_buy = f"机构 {buyers} 家" if buyers else _field(row, ("买入营业部", "买一"))
    top_sell = f"机构 {sellers} 家" if sellers else _field(row, ("卖出营业部", "卖一"))
    return side, net, top_buy, top_sell


def _holder_flow(row: dict | None) -> str:
    if not row:
        return "不可用"
    side = _change_side(row)
    if side == "buy":
        return "增持"
    if side == "sell":
        return "减持"
    return "不可用"


def _margin_flows(row: dict | None) -> tuple[str, str]:
    if not row:
        return "不可用", "不可用"
    margin = _to_float(
        _field(row, ("融资余额差额", "融资净买入", "融资余额变化", "融资买入额"))
    )
    short = _to_float(_field(row, ("融券余量差额", "融券余量变化", "融券卖出量")))
    return _signed(margin, "融资增加", "融资偿还"), _signed(short, "融券增加", "融券下降")


def _summary(stance: dict[str, Any]) -> str:
    regime = _REGIME_ZH.get(str(stance.get("regime")), "容错未知")
    shape = _SHAPE_ZH.get(str(stance.get("board_shape")), "未封板")
    return f"{regime} · {shape} · {stance.get('t1_bias')}"


_NOTE = (
    "沪深主板当天研究快照。创业板、科创板、北交所不在表内。"
    "席位净买/净卖是龙虎买卖，不是融券做空；减持不是清盘。"
    "点一行进入全图分析，不会自动跑预测，也永不下单。"
    "榜单上的首板没有近端涨停史，所以保持观望；全图会用日线重算。"
)

_TOMORROW_RISE_NOTE = (
    "下一交易日偏多研究名单。扫描涨幅/涨速/领涨观察区，再用 T+1 打法筛出 BUY。"
    "创业板不参与；科创板与北交所在表内。席位净买/净卖是龙虎买卖，不是融券做空。"
    "研究评级，永不下单。"
)


# Tencent rank list: ``turnover`` is 万元, ``ltsz`` is 亿元. The table shows 元.
_TX_AMOUNT_TO_YUAN = 10_000.0
_TX_MV_TO_YUAN = 100_000_000.0


def _yuan(raw: Any, scale: float) -> float | None:
    value = _to_float(raw)
    if value is None:
        return None
    return value * scale


def _from_tencent_spot(rows: list[dict]) -> list[dict]:
    """Map ``stock_zh_a_spot_tx`` rank fields onto the East Money column names."""
    mapped: list[dict] = []
    for row in rows:
        if "code" not in row and "zdf" not in row:
            mapped.append(row)
            continue
        mapped.append(
            {
                "代码": row.get("code"),
                "名称": row.get("name"),
                "涨跌幅": row.get("zdf"),
                "涨速": row.get("speed"),
                "换手率": row.get("hsl"),
                "量比": row.get("lb"),
                "振幅": row.get("zf"),
                "最新价": row.get("zxj"),
                "成交额": _yuan(row.get("turnover"), _TX_AMOUNT_TO_YUAN),
                "流通市值": _yuan(row.get("ltsz"), _TX_MV_TO_YUAN),
            }
        )
    return mapped


def _snapshot_note(quote_source: str, *, universe: str) -> str:
    base = _TOMORROW_RISE_NOTE if universe == "no_chinext" else _NOTE
    front = "沪深主板" if universe == "main" else "非创业板"
    if quote_source == "sina":
        return (
            base
            + f"这次现货走新浪。涨速、换手和量比没有字段，这三列留空；涨幅榜仍列出{front}前排。"
        )
    if quote_source == "tencent":
        return (
            base
            + "这次现货走腾讯。涨速、换手和量比有字段；没有今开、最高、最低和昨收，振幅用腾讯振幅。"
        )
    if not quote_source:
        return base + f"沪深现货榜没有返回，表格不能列出{front}前排。"
    return base


def build_screen_snapshot(
    *,
    as_of: str,
    spot_rows: list[dict],
    leader_rows: list[dict],
    regime: dict[str, Any],
    zt_rows: list[dict],
    lhb_rows: list[dict],
    insider_rows: list[dict],
    margin_rows: list[dict],
    quote_source: str = "eastmoney",
    universe: str = "main",
    only_t1_bias: str | None = None,
) -> dict[str, Any]:
    """Join the board lists with playbook stance and disclosed-flow labels."""
    selected = select_candidates(spot_rows, leader_rows, universe=universe)
    codes = {row["code"] for row in selected}
    start = (
        datetime.strptime(as_of, "%Y-%m-%d") - timedelta(days=INSIDER_LOOKBACK_DAYS)
    ).strftime("%Y-%m-%d")
    lhb = _latest_by_code(lhb_rows, codes, as_of, as_of)
    insider = _latest_by_code(insider_rows, codes, as_of, start)
    margin = _latest_by_code(margin_rows, codes, as_of, start)
    rows: list[dict[str, Any]] = []
    for quote in selected:
        code = quote["code"]
        streak = _pool_streak(zt_rows, code)
        side, net, top_buy, top_sell = _seat_side(lhb.get(code))
        stance = build_playbook_stance(
            daily_rows=_stance_rows(quote, as_of, streak),
            as_of=as_of,
            market_amount_yuan=regime.get("market_amount_yuan"),
            prev_zt_premium=regime.get("prev_zt_premium"),
            limit_up_count=regime.get("limit_up_count"),
            limit_down_count=regime.get("limit_down_count"),
            bank_ret_1d=regime.get("bank_ret_1d"),
            hs300_ret_1d=regime.get("hs300_ret_1d"),
            announce_bad=False,
            is_st_or_loss=False,
            lift_ban_mv_5d=None,
            live_pct=quote.get("pct_chg"),
            lhb_net_buy=net,
        )
        margin_flow, short_flow = _margin_flows(margin.get(code))
        rows.append(
            {
                "ticker": screen_ticker(code),
                "code": code,
                "name": quote["name"],
                "sources": [_SOURCE_ZH.get(item, item) for item in quote["sources"]],
                "sector": quote.get("sector"),
                "is_sector_leader": bool(quote.get("is_sector_leader")),
                "pct_chg": quote.get("pct_chg"),
                "speed": quote.get("speed"),
                "pct_5m": quote.get("pct_5m"),
                "turnover": quote.get("turnover"),
                "volume_ratio": quote.get("volume_ratio"),
                "amount": quote.get("amount"),
                "amplitude": quote.get("amplitude"),
                "float_mv": quote.get("float_mv"),
                "board_shape": stance["board_shape"],
                "consecutive_limit_ups": stance["consecutive_limit_ups"],
                "summary": _summary(stance),
                "t1_bias": stance["t1_bias"],
                "t1_reason": stance["t1_reason"],
                "seat_side": side,
                "lhb_net_buy": net,
                "top_buy": top_buy,
                "top_sell": top_sell,
                "holder_flow": _holder_flow(insider.get(code)),
                "margin_flow": margin_flow,
                "short_flow": short_flow,
            }
        )
    if only_t1_bias is not None:
        rows = [row for row in rows if row.get("t1_bias") == only_t1_bias]
        rows.sort(
            key=lambda row: (
                float(row.get("lhb_net_buy") or 0.0),
                float(row.get("consecutive_limit_ups") or 0),
                float(row.get("pct_chg") or 0.0),
            ),
            reverse=True,
        )
    return {
        "as_of": as_of,
        "universe": universe,
        "regime": regime.get("regime"),
        "regime_label": _REGIME_ZH.get(str(regime.get("regime")), "容错未知"),
        "market_amount_yuan": regime.get("market_amount_yuan"),
        "prev_zt_premium": regime.get("prev_zt_premium"),
        "limit_up_count": regime.get("limit_up_count"),
        "limit_down_count": regime.get("limit_down_count"),
        "quote_source": quote_source,
        "note": _snapshot_note(quote_source, universe=universe),
        "rows": rows,
    }


def _load_regime(ak, as_of: str) -> tuple[dict[str, Any], list[dict]]:
    start = (datetime.strptime(as_of, "%Y-%m-%d") - timedelta(days=40)).strftime("%Y-%m-%d")
    sse = _cached(GLOBAL_KEY, as_of, "idx_sse", lambda: _fetch_index_daily(ak, as_of, start, "sh000001"))
    sza = _cached(GLOBAL_KEY, as_of, "idx_sza", lambda: _fetch_index_daily(ak, as_of, start, "sz399107"))
    bank = _cached(GLOBAL_KEY, as_of, "idx_bank", lambda: _fetch_index_daily(ak, as_of, start, "sz399986"))
    hs300 = _cached(GLOBAL_KEY, as_of, "idx_hs300", lambda: _fetch_index_daily(ak, as_of, start, "sh000300"))
    zt = _cached(GLOBAL_KEY, as_of, "zt_pool", lambda: _fetch_zt_pool(ak, as_of))
    dt = _cached(GLOBAL_KEY, as_of, "dt_pool", lambda: _fetch_dt_pool(ak, as_of))
    prev = _cached(GLOBAL_KEY, as_of, "prev_zt", lambda: _fetch_prev_zt(ak, as_of))
    amount = combine_market_amount(_last_amount(sse), _last_amount(sza))
    premium = _mean_float(prev, ("涨跌幅", "溢价", "昨收溢价"))
    regime = resolve_regime(
        market_amount_yuan=amount,
        prev_zt_premium=premium,
        limit_up_count=len(zt),
        limit_down_count=len(dt),
        bank_ret_1d=_index_ret(bank, as_of, 1),
        hs300_ret_1d=_index_ret(hs300, as_of, 1),
    )
    return (
        {
            "regime": regime,
            "market_amount_yuan": amount,
            "prev_zt_premium": premium,
            "limit_up_count": len(zt),
            "limit_down_count": len(dt),
            "bank_ret_1d": _index_ret(bank, as_of, 1),
            "hs300_ret_1d": _index_ret(hs300, as_of, 1),
        },
        zt,
    )


def _live_table(ak, as_of: str, channel: str, loader) -> list[dict]:
    ttl = _ttl_seconds()
    try:
        return _cached(GLOBAL_KEY, as_of, channel, loader, ttl_seconds=ttl)
    except TimeoutError as e:
        logger.warning("A-share screen %s timed out: %s", channel, e)
        return []


def _load_screen_market_bundle(as_of: str | None) -> dict[str, Any]:
    """Same-day spot, leaders, regime, and flow tables for board screens."""
    day = _coerce_day(as_of)
    _require_today(day)
    ak = _load_akshare()
    ymd = _yyyymmdd(day)
    spot = _live_table(
        ak,
        day,
        "screen_spot",
        lambda: _try_ak_records(ak, ("stock_zh_a_spot_em",), ({},)),
    )
    quote_source = "eastmoney" if spot else ""
    if not spot:
        logger.warning("A-share screen East Money spot empty; trying Sina stock_zh_a_spot")
        spot = _live_table(
            ak,
            day,
            "screen_spot_sina",
            lambda: _try_ak_records(ak, ("stock_zh_a_spot",), ({},)),
        )
        if spot:
            quote_source = "sina"
    if not spot:
        logger.warning(
            "A-share screen Sina spot empty; trying Tencent stock_zh_a_spot_tx"
        )
        spot = _from_tencent_spot(
            _live_table(
                ak,
                day,
                "screen_spot_tx",
                lambda: _try_ak_records(ak, ("stock_zh_a_spot_tx",), ({},)),
            )
        )
        if spot:
            quote_source = "tencent"
    leaders = _live_table(
        ak,
        day,
        "screen_industry",
        lambda: _try_ak_records(ak, ("stock_board_industry_name_em",), ({},)),
    )
    if not leaders:
        logger.warning(
            "A-share screen East Money industry boards empty; trying Tonghuashun summary"
        )
        leaders = _live_table(
            ak,
            day,
            "screen_industry_ths",
            lambda: _try_ak_records(ak, ("stock_board_industry_summary_ths",), ({},)),
        )
    regime, zt = _load_regime(ak, day)
    lhb = _live_table(
        ak,
        day,
        "screen_lhb_inst",
        lambda: _try_ak_records(
            ak,
            ("stock_lhb_jgmmtj_em", "stock_lhb_detail_em"),
            ({"start_date": ymd, "end_date": ymd},),
            allow_empty_call=False,
        ),
    )
    insider = _live_table(
        ak,
        day,
        "screen_insider",
        lambda: _try_ak_records(
            ak,
            ("stock_ggcg_em",),
            ({"symbol": "全部"},),
            allow_empty_call=False,
            timeout=SCREEN_INSIDER_TIMEOUT,
        ),
    )
    margin = _live_table(
        ak,
        day,
        "screen_margin_sse",
        lambda: _try_ak_records(
            ak,
            ("stock_margin_detail_sse",),
            ({"date": ymd},),
            allow_empty_call=False,
        ),
    )
    margin_sz = _live_table(
        ak,
        day,
        "screen_margin_szse",
        lambda: _try_ak_records(
            ak,
            ("stock_margin_detail_szse",),
            ({"date": ymd},),
            allow_empty_call=False,
        ),
    )
    return {
        "as_of": day,
        "spot_rows": spot,
        "leader_rows": leaders,
        "regime": regime,
        "zt_rows": zt,
        "lhb_rows": lhb,
        "insider_rows": insider,
        "margin_rows": [*margin, *margin_sz],
        "quote_source": quote_source,
    }


def screen_main_board(as_of: str | None = None) -> dict[str, Any]:
    """Today's main-board screen. Refuses any other date before touching vendors."""
    return build_screen_snapshot(**_load_screen_market_bundle(as_of))


def screen_tomorrow_rise(as_of: str | None = None) -> dict[str, Any]:
    """T+1 BUY names from today's watch zone, excluding ChiNext listings."""
    return build_screen_snapshot(
        **_load_screen_market_bundle(as_of),
        universe="no_chinext",
        only_t1_bias="BUY",
    )
