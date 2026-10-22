# web-ui `/api/options` 502 导致操作台下拉为空

- 日期：2026-09-21
- 状态：done
- 来源：bugfix
- 原链接：
- 关联模块：web/nginx.conf.template, web/static/app.js, docker-compose.yml, tests/test_web_console.py
- 回写文档：docs/PROJECT.md, docs/ARCHITECTURE.md, README.md
- 替代关系：补充 [20260915-local-web-console.md](20260915-local-web-console.md)

## 结论

本机操作台语言、分析师、研究深度、LLM 供应商、Quick/Deep 模型都来自 `GET /api/options`。选项清单在 `web-api` 上始终存在；页面空白是 `web-ui` nginx 把 `/api` 打到 **recreate 之前的 `web-api` 容器 IP**，返回 502。`boot()` 原先没有处理失败，select 保持空。

## 根因

nginx 静态 `proxy_pass http://web-api:8000` 在进程启动时解析 Docker DNS。`--force-recreate web-api` 换 IP 后，未 recreate 的 `web-ui` 仍打旧地址。

## 落地

- `web/nginx.conf.template`：`resolver 127.0.0.11` + `set $tradingagents_web_api ${WEB_API_UPSTREAM}` + `proxy_pass http://$tradingagents_web_api`，每次请求再解析
- `web/static/app.js`：`boot()` 在 `/api/options` 非 2xx 时把错误写到 `#form-error`
- 应急：`docker compose --profile web restart web-ui`（不要只 recreate `web-api` 后不碰 UI）

禁止：把选项硬编码进 `index.html`；不要为了填下拉而把 API key 或模型长名单写进静态页。
