# Tech Library

确认技术方案的索引。开发前先扫本页；命中主题再读正文。

规则正文不放这里。易变事实以代码和 [PROJECT.md](../PROJECT.md) 为准。

## 何时必须沉淀

凡有**确认**方案且已落地或明确取消，无论来源都要归档：

- Plan 模式产出并落地的方案
- 外部技术方案链接
- Agent 讨论后确认的方案
- 实现过程中的方案改判
- 重要 Bug 根因与修复策略
- API / MQ / 数据模型破坏性变更（本仓库若引入这类层，先归档）
- 有结论的 POC 或放弃调研
- 重大依赖或子模块升级

## 可豁免

- 纯 typo、格式
- 无行为变化的内部重构
- 无结论排障
- 未确认中间稿

## 文件约定

- 路径：`docs/tech-library/YYYYMMDD-<slug>.md`
- 状态：`done` | `superseded` | `cancelled`
- 来源：`plan` | `external-link` | `agent-discussion` | `bugfix` | `breaking-change` | `dependency` | `other`
- 被替代方案把状态改为 `superseded`，并写明替代文件
- 外部方案必须填「原链接」
- Plan 流程图写入方案正文，或按落地调用链补绘到 [ARCHITECTURE.md](../ARCHITECTURE.md)

## 文首字段模板

```markdown
# 标题

- 日期：YYYY-MM-DD
- 状态：done
- 来源：plan
- 原链接：
- 关联模块：
- 回写文档：docs/PROJECT.md, docs/ARCHITECTURE.md
- 替代关系：无
```

## 索引

| 日期 | 文件 | 状态 | 来源 | 主题 |
| --- | --- | --- | --- | --- |
| 2026-10-21 | [20261021-playbook-t1-accuracy-tightening.md](20261021-playbook-t1-accuracy-tightening.md) | done | agent-discussion | T+1 playbook 与趋势预测规则收紧 |
| 2026-10-21 | [20261021-trend-regime-accuracy.md](20261021-trend-regime-accuracy.md) | done | agent-discussion | 趋势 regime 收紧；swing trend_bias 锁定 PM 评级 |
| 2026-10-21 | [20261021-ashare-tomorrow-rise-no-chinext.md](20261021-ashare-tomorrow-rise-no-chinext.md) | done | agent-discussion | 明日上涨 T+1 BUY 扫描，排除创业板 |
| 2026-10-20 | [20261020-ashare-terminal-ui.md](20261020-ashare-terminal-ui.md) | done | agent-discussion | 操作台日K与涨跌幅改成 A 股红涨绿跌 |
| 2026-10-14 | [20261014-guba-posts-without-xueqiu.md](20261014-guba-posts-without-xueqiu.md) | done | bugfix | 雪球 cookie 未设时用东财股吧帖子做多空计数 |
| 2026-10-12 | [20261012-screen-table-above-chart.md](20261012-screen-table-above-chart.md) | done | bugfix | 东财现货被掐断后新浪涨幅表仍在；表格改到日K上面 |
| 2026-10-12 | [20261012-gov-finance-news.md](20261012-gov-finance-news.md) | done | agent-discussion | 新闻联播改直读 CNTV；补央行、财政部、发改委、统计局 |
| 2026-10-12 | [20261012-aktools-signature-500.md](20261012-aktools-signature-500.md) | done | bugfix | AKTools 把错误参数收成 500；股吧旧名 404；按现行 AKShare 签名调用 |
| 2026-09-23 | [20260923-state-media-news.md](20260923-state-media-news.md) | done | agent-discussion | 国内宏观补人民日报、新华社财经、中国经济网、中新网财经、央视新闻、中国政府网 |
| 2026-09-23 | [20260923-ashare-screen-tencent-spot.md](20260923-ashare-screen-tencent-spot.md) | done | bugfix | 筛选新浪现货也 500 时改腾讯现货；龙虎不再传 date |
| 2026-09-22 | [20260922-ashare-screen-spot-fallback.md](20260922-ashare-screen-spot-fallback.md) | done | bugfix | 筛选东财现货/行业板 500 时改新浪现货与同花顺行业 |
| 2026-09-22 | [20260922-ashare-board-screen.md](20260922-ashare-board-screen.md) | done | agent-discussion | 操作台沪深主板涨幅/涨速/领涨筛选；点一行再进全图 |
| 2026-09-22 | [20260922-ths-futu-wires.md](20260922-ths-futu-wires.md) | done | agent-discussion | 国内快讯补同花顺、富途；个股路径按代码过滤，缺接口跳过 |
| 2026-09-22 | [20260922-ashare-t1-playbook.md](20260922-ashare-t1-playbook.md) | done | agent-discussion | A 股 T+1 打法立场写进短线 tape；最终评级对齐 t1_bias，不下单 |
| 2026-09-21 | [20260921-web-swing-tape-keyerror.md](20260921-web-swing-tape-keyerror.md) | done | bugfix | Web 预取 swing_tape 后 live 标题 KeyError；缺接口跳过、增减持不传 .SH |
| 2026-09-21 | [20260921-ashare-chanlun.md](20260921-ashare-chanlun.md) | done | agent-discussion | 价量 Tape 挂缠论分型/笔/段/中枢；250 日历日 as-of，不新开 HTTP |
| 2026-09-21 | [20260921-ashare-swing-tape.md](20260921-ashare-swing-tape.md) | done | agent-discussion | 近半个月/近半年价量 + 机构出手 + 窗口新闻 tape；Web 价量页仍走跑图（含 News Analyst） |
| 2026-09-21 | [20260921-web-ui-options-502.md](20260921-web-ui-options-502.md) | done | bugfix | web-ui 静态 `proxy_pass` 在 recreate web-api 后 502，表单下拉全空 |
| 2026-09-20 | [20260920-ashare-buy-sell-flow.md](20260920-ashare-buy-sell-flow.md) | done | agent-discussion | A 股增减持/龙虎买卖/大宗走 `get_insider_transactions`；bind 对齐 |
| 2026-09-20 | [20260920-ticker-scoped-nodes.md](20260920-ticker-scoped-nodes.md) | done | agent-discussion | 千股千评/代码简称表按当前票过滤；辩论不再把 news 当 world affairs |
| 2026-09-20 | [20260920-google-global-news.md](20260920-google-global-news.md) | done | agent-discussion | `get_global_news` 海外源走 Serper Google Search，site: 补 X/YouTube/Meta |
| 2026-09-20 | [20260920-ticker-news-relevance.md](20260920-ticker-news-relevance.md) | done | bugfix | `get_news` 丢掉东财相关推荐里的无关资讯 |
| 2026-09-20 | [20260920-latest-run-lookup.md](20260920-latest-run-lookup.md) | done | agent-discussion | Web 查最近一次报告树；不引入 ORM |
| 2026-09-20 | [20260920-ashare-fundamentals.md](20260920-ashare-fundamentals.md) | done | bugfix | A 股三表走 AKTools 东财/新浪；默认 `akshare,yfinance` |
| 2026-09-20 | [20260920-preserve-ashare-sh-suffix.md](20260920-preserve-ashare-sh-suffix.md) | done | bugfix | Web/CLI 跑图保留用户输入的 `.SH`，Yahoo 查询才改 `.SS` |
| 2026-09-18 | [20260918-exposure-sector-coverage.md](20260918-exposure-sector-coverage.md) | done | agent-discussion | 静态暴露覆盖锂镍钢农化酒银等，铜只是一例 |
| 2026-09-18 | [20260918-intl-commodity.md](20260918-intl-commodity.md) | done | agent-discussion | tape 外盘商品：LME/COMEX 铜等，挂静态暴露 |
| 2026-09-18 | [20260918-t1-hit-rate-ingest.md](20260918-t1-hit-rate-ingest.md) | done | agent-discussion | score 以 T+1 为主；live 空仓库 ingest；雪球 token；商品/行业符号回退 |
| 2026-09-18 | [20260918-ashare-industry-commodity.md](20260918-ashare-industry-commodity.md) | done | agent-discussion | A 股静态行业指数与商品合约暴露，挂 tape |
| 2026-09-16 | [20260916-ashare-tape-fallbacks-score.md](20260916-ashare-tape-fallbacks-score.md) | done | agent-discussion | tape 东财 RST 回退；A 股结算走 AKTools；memory 命中率 |
| 2026-09-16 | [20260916-ashare-identity-snapshot.md](20260916-ashare-identity-snapshot.md) | done | agent-discussion | A 股身份卡；校验快照与 get_stock_data 同源 |
| 2026-09-16 | [20260916-ashare-tencent-hist-fallback.md](20260916-ashare-tencent-hist-fallback.md) | done | bugfix | 东财日线 RST 走腾讯/新浪；A 股不再打 Yahoo |
| 2026-09-16 | [20260916-ashare-docker-vendor-llm.md](20260916-ashare-docker-vendor-llm.md) | done | bugfix | A 股日线先 AKTools；容器不用 127.0.0.1；Web 保留豆包快照 ID |
| 2026-09-15 | [20260915-local-web-console.md](20260915-local-web-console.md) | done | plan | 本机 loopback Web 操作台；compose 拆 web-ui/web-api，同一 Dockerfile |
| 2026-09-15 | [20260915-aktools-akshare-upgrade.md](20260915-aktools-akshare-upgrade.md) | done | bugfix | 冻结 aktools:1.8.95 拒 000001；sidecar 构建 akshare>=1.16 |
| 2026-09-15 | [20260915-aktools-homepage-pypi.md](20260915-aktools-homepage-pypi.md) | done | bugfix | AKTools 首页刮 PyPI 500；sidecar sitecustomize 绕开 |
| 2026-09-15 | [20260915-akshare-aktools-http.md](20260915-akshare-aktools-http.md) | done | agent-discussion | 本地 Docker AKTools HTTP，而不是 Jupyter |
| 2026-09-14 | [20260914-live-predict-no-orders.md](20260914-live-predict-no-orders.md) | done | agent-discussion | 按需实时预测、永不下单 |
| 2026-09-14 | [20260914-doubao-volcengine-ark.md](20260914-doubao-volcengine-ark.md) | done | agent-discussion | 豆包 / 火山方舟一等 LLM 供应商 |
| 2026-09-14 | [20260914-ashare-short-horizon-tape.md](20260914-ashare-short-horizon-tape.md) | done | agent-discussion | A 股次日/5–20 日短线 tape |
| 2026-09-14 | [20260914-ashare-news-warehouse.md](20260914-ashare-news-warehouse.md) | done | agent-discussion | A 股资讯 JSONL 仓库、电报短 TTL、雪球 cookie |
| 2026-09-14 | [20260914-ashare-data-foundation.md](20260914-ashare-data-foundation.md) | done | agent-discussion | A 股资讯去重缓存与情绪源 |
| 2026-09-14 | [20260914-ashare-news-aggregation.md](20260914-ashare-news-aggregation.md) | done | plan | A 股多渠道新闻与海外源聚合 |
| 2026-09-05 | [20260905-dev-closed-loop.md](20260905-dev-closed-loop.md) | done | plan | 跨工具开发自闭环 |
| 2026-08-31 | [20260831-lookahead-point-in-time.md](20260831-lookahead-point-in-time.md) | done | bugfix | 前瞻泄漏与点-in-time 记忆 |
| 2026-06-22 | [20260622-vendor-routing-contract.md](20260622-vendor-routing-contract.md) | done | breaking-change | 已配置供应商链即解析链 |
