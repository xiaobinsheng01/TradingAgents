"""Tests for symbol normalization and the no-data routing sentinel."""

import unittest

import pytest

from tradingagents.dataflows.symbol_utils import (
    NoMarketDataError,
    a_share_code,
    crypto_base,
    is_yahoo_safe,
    normalize_symbol,
    run_ticker_symbol,
)


@pytest.mark.unit
class TestNormalizeSymbol(unittest.TestCase):
    def test_plain_equities_unchanged(self):
        for sym in ("AAPL", "MSFT", "TSM", "BRK.B", "0700.HK", "^GSPC", "GC=F"):
            self.assertEqual(normalize_symbol(sym), sym)

    def test_shanghai_broker_suffix_maps_to_yahoo_ss(self):
        self.assertEqual(normalize_symbol("601061.SH"), "601061.SS")
        self.assertEqual(normalize_symbol("600519.SS"), "600519.SS")
        self.assertEqual(normalize_symbol("600519"), "600519.SS")
        self.assertEqual(normalize_symbol("000001.SZ"), "000001.SZ")

    def test_run_ticker_keeps_shanghai_broker_suffix(self):
        self.assertEqual(run_ticker_symbol("601061.SH"), "601061.SH")
        self.assertEqual(run_ticker_symbol("601061.ss"), "601061.SS")
        self.assertEqual(run_ticker_symbol("601061"), "601061.SS")
        self.assertEqual(run_ticker_symbol("000001.SZ"), "000001.SZ")
        self.assertEqual(run_ticker_symbol("BTCUSD"), "BTC-USD")

    def test_lowercases_are_upper(self):
        self.assertEqual(normalize_symbol("aapl"), "AAPL")
        self.assertEqual(normalize_symbol("  msft  "), "MSFT")

    def test_metal_aliases_map_to_futures(self):
        self.assertEqual(normalize_symbol("XAUUSD"), "GC=F")
        self.assertEqual(normalize_symbol("XAUUSD+"), "GC=F")   # broker CFD suffix
        self.assertEqual(normalize_symbol("xauusd+"), "GC=F")
        self.assertEqual(normalize_symbol("GOLD"), "GC=F")
        self.assertEqual(normalize_symbol("XAGUSD"), "SI=F")

    def test_energy_and_index_aliases(self):
        self.assertEqual(normalize_symbol("USOIL"), "CL=F")
        self.assertEqual(normalize_symbol("SPX500"), "^GSPC")
        self.assertEqual(normalize_symbol("NAS100"), "^NDX")
        self.assertEqual(normalize_symbol("US30"), "^DJI")

    def test_forex_pairs_get_x_suffix(self):
        self.assertEqual(normalize_symbol("EURUSD"), "EURUSD=X")
        self.assertEqual(normalize_symbol("GBPJPY"), "GBPJPY=X")
        self.assertEqual(normalize_symbol("eurusd"), "EURUSD=X")

    def test_crypto_pairs_get_dash_usd(self):
        self.assertEqual(normalize_symbol("BTCUSD"), "BTC-USD")
        self.assertEqual(normalize_symbol("ETHUSD"), "ETH-USD")

    def test_six_letter_non_currency_left_alone(self):
        # GOOGLE-style 6-letter tickers that aren't two currency codes
        # must not be mangled into a fake forex pair.
        self.assertEqual(normalize_symbol("ABCDEF"), "ABCDEF")

    def test_empty_input_passthrough(self):
        self.assertEqual(normalize_symbol(""), "")


@pytest.mark.unit
class TestNoMarketDataError(unittest.TestCase):
    def test_message_includes_resolution(self):
        err = NoMarketDataError("XAUUSD+", "GC=F", "no rows")
        self.assertIn("XAUUSD+", str(err))
        self.assertIn("GC=F", str(err))
        self.assertEqual(err.symbol, "XAUUSD+")
        self.assertEqual(err.canonical, "GC=F")

    def test_canonical_defaults_to_symbol(self):
        err = NoMarketDataError("FOOBAR")
        self.assertEqual(err.canonical, "FOOBAR")


@pytest.mark.unit
class TestIsYahooSafe(unittest.TestCase):
    def test_accepts_structural_chars(self):
        for sym in ("AAPL", "GC=F", "^GSPC", "BRK.B", "BTC-USD"):
            self.assertTrue(is_yahoo_safe(sym))

    def test_rejects_slash_and_space(self):
        for sym in ("a/b", "AA PL", ""):
            self.assertFalse(is_yahoo_safe(sym))


@pytest.mark.unit
class TestCryptoBase(unittest.TestCase):
    def test_resolves_known_crypto_forms(self):
        for raw in ("BTC-USD", "BTCUSD", "btc-usdt", "BTC-USDC", "BTCUSD+"):
            self.assertEqual(crypto_base(raw), "BTC")
        self.assertEqual(crypto_base("ETH-USD"), "ETH")
        self.assertEqual(crypto_base("sol-usd"), "SOL")

    def test_non_crypto_returns_none(self):
        # Plain equities, class shares, and real tickers that alias elsewhere
        # (GOLD -> gold future on the Yahoo path) must NOT read as crypto.
        for raw in ("AAPL", "BRK-B", "GOLD", "XYZ-USD", "EURUSD", "", None):
            self.assertIsNone(crypto_base(raw))

    def test_agrees_with_normalize_symbol(self):
        # crypto_base is the shared primitive behind the -USD normalization.
        self.assertEqual(normalize_symbol("BTCUSD"), "BTC-USD")
        self.assertEqual(crypto_base("BTCUSD"), "BTC")


@pytest.mark.unit
class TestAShareCode(unittest.TestCase):
    def test_yahoo_and_broker_suffixes(self):
        self.assertEqual(a_share_code("600519.SS"), "600519")
        self.assertEqual(a_share_code("600519.SH"), "600519")
        self.assertEqual(a_share_code("000001.SZ"), "000001")
        self.assertEqual(a_share_code("300750.SZ"), "300750")
        self.assertEqual(a_share_code("688111.SS"), "688111")
        self.assertEqual(a_share_code("430047.BJ"), "430047")

    def test_bare_six_digit_code(self):
        self.assertEqual(a_share_code("600519"), "600519")
        self.assertEqual(a_share_code("000001"), "000001")

    def test_non_a_share_returns_none(self):
        for raw in ("AAPL", "0700.HK", "7203.T", "BTC-USD", "900947", "", None):
            self.assertIsNone(a_share_code(raw))

    def test_prefixed_sina_tencent_symbol(self):
        from tradingagents.dataflows.symbol_utils import a_share_prefixed_symbol

        self.assertEqual(a_share_prefixed_symbol("601061"), "sh601061")
        self.assertEqual(a_share_prefixed_symbol("000001"), "sz000001")
        self.assertEqual(a_share_prefixed_symbol("300750"), "sz300750")
        self.assertEqual(a_share_prefixed_symbol("430047"), "bj430047")
        self.assertEqual(a_share_prefixed_symbol("920001"), "bj920001")

    def test_yahoo_skip_raises_for_a_share(self):
        from tradingagents.dataflows.symbol_utils import raise_if_a_share_yahoo

        with self.assertRaises(NoMarketDataError) as ctx:
            raise_if_a_share_yahoo("601061.SH", "news")
        self.assertIn("601061", str(ctx.exception))
        raise_if_a_share_yahoo("AAPL", "news")


@pytest.mark.unit
class TestAShareBoardRules(unittest.TestCase):
    def test_board_type_by_code(self):
        from tradingagents.dataflows.symbol_utils import a_share_board_type

        self.assertEqual(a_share_board_type("600519"), "main")
        self.assertEqual(a_share_board_type("300750"), "chinext")
        self.assertEqual(a_share_board_type("688111"), "star")
        self.assertEqual(a_share_board_type("430047"), "bse")
        self.assertEqual(a_share_board_type("600519", is_st=True), "st")

    def test_exchange_name_by_code(self):
        from tradingagents.dataflows.symbol_utils import a_share_exchange_name

        self.assertEqual(a_share_exchange_name("601061"), "SSE")
        self.assertEqual(a_share_exchange_name("000001"), "SZSE")
        self.assertEqual(a_share_exchange_name("430047"), "BSE")

    def test_limit_pct_chinext_reform_and_st(self):
        from tradingagents.dataflows.symbol_utils import a_share_limit_pct

        self.assertEqual(a_share_limit_pct("300750", "2020-08-23"), 10.0)
        self.assertEqual(a_share_limit_pct("300750", "2020-08-24"), 20.0)
        self.assertEqual(a_share_limit_pct("600519", "2026-01-10"), 10.0)
        self.assertEqual(a_share_limit_pct("688111", "2026-01-10"), 20.0)
        self.assertEqual(a_share_limit_pct("600519", "2026-01-10", is_st=True), 5.0)



if __name__ == "__main__":
    unittest.main()
