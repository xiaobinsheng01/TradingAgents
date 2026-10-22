# Web/CLI 跑图保留 A 股 `.SH` 后缀

- 日期：2026-09-20
- 状态：done
- 来源：bugfix
- 原链接：
- 关联模块：tradingagents/dataflows/symbol_utils.py, cli/utils.py, web/schemas.py
- 回写文档：docs/PROJECT.md, docs/ARCHITECTURE.md
- 替代关系：澄清 [20260916-ashare-docker-vendor-llm.md](20260916-ashare-docker-vendor-llm.md) 第 3 点；不改变 Yahoo 侧 `.SH` → `.SS`

## 背景

页面输入 `601061.SH` 后，User 提示词变成 `601061.SS`。`RunRequest` / `normalize_ticker_symbol` 整段委托 `normalize_symbol`，把券商上海后缀改成 Yahoo 写法，看起来像写死 `.SS`、没按页面搜索。

## 确认方案

1. 新增 `run_ticker_symbol`：用户写了 `.SH` / `.SZ` / `.BJ` / `.SS` 就原样（大写）进 `company_of_interest`。裸六位仍补 Yahoo 后缀。加密/外汇/金属别名仍走 `normalize_symbol`。
2. `normalize_symbol` 仍只服务 Yahoo 查询：上海 `.SH` → `.SS`。
3. A 股基本面工具继续跳过 Yahoo（与后缀无关）。三表本身后来接到 AKTools，见 [20260920-ashare-fundamentals.md](20260920-ashare-fundamentals.md)。

## 落地调用链

```
Web 标的 601061.SH
  → RunRequest → normalize_ticker_symbol → run_ticker_symbol
  → company_of_interest = 601061.SH
  → 工具内 Yahoo 路径仍 normalize_symbol → 601061.SS
```
