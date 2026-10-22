# Web 预取 swing_tape 后 KeyError 中止跑图

- 日期：2026-09-21
- 状态：done
- 来源：bugfix
- 原链接：
- 关联模块：cli/run_engine.py, tradingagents/dataflows/akshare_news.py, tradingagents/dataflows/akshare_flow.py, tradingagents/dataflows/akshare_fundamentals.py, tradingagents/dataflows/akshare_market.py
- 回写文档：docs/PROJECT.md, docs/ARCHITECTURE.md
- 替代关系：补充 [20260921-ashare-swing-tape.md](20260921-ashare-swing-tape.md)

## 结论

Web 操作台跑图在价量 Tape 预取成功后崩溃，不是因为东财 RST。`MessageBuffer.REPORT_SECTIONS` 已有 `swing_tape`，但 live 标题表漏了这一节，`update_report_section` 触发 `KeyError`。日志里的 AKTools 404/500 是通道降级，不应中止全链路。

## 根因

1. `run_graph_with_events` 预取后调用 `buffer.update_report_section("swing_tape", ...)`。`_update_current_report` 用另一份 `section_titles` 取标题，没有 `swing_tape`。
2. `AktoolsHttpClient.__getattr__` 对任意接口名都返回可调用对象。sidecar 没有 `stock_zh_a_alerts_cls` 时 HTTP 404「未找到该接口」，原先打 warning 后空列表；同一跑图 ticker + global 会打两次。
3. `_code_kwargs` 末项把 `601061.SH` 传给东财 `stock_changes_em`，接口拒参（仍标成 `stock_ggcg_em failed`）。
4. `stock_individual_info_em` / `stock_info_a_code_name` / `stock_zh_a_hist` / `index_zh_a_hist` / 巨潮 500 仍是东财 RST；日线已有腾讯/新浪回退。

## 落地

- live 标题登记 `swing_tape`，未知节用 `.get`；终稿拼接也带价量 Tape
- 404「未找到该接口」视为 sidecar 缺接口：跳过该通道，不再换 kwargs 空打；财联社快讯仍走 `stock_info_global_cls`
- 增减持 kwargs 只保留六位代码与 `sh`/`sz` 前缀
- 东财 RST 500 继续降级，禁止编造价格或新闻

Docker `web-api` 的入口读 `/opt/venv/.../site-packages`，改代码后需 overlay 或 `--build --force-recreate`。
