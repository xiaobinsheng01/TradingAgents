# AKTools 首页刮 PyPI 导致 Docker 500

- 日期：2026-09-15
- 状态：done
- 来源：bugfix
- 原链接：https://github.com/akfamily/aktools/issues/179
- 关联模块：docker/aktools.Dockerfile, docker-compose.yml
- 回写文档：docs/PROJECT.md, docs/ARCHITECTURE.md, docs/tech-library/20260915-akshare-aktools-http.md
- 替代关系：补充 [20260915-akshare-aktools-http.md](20260915-akshare-aktools-http.md)，不改 `route_to_vendor`

## 结论

`akfamily/aktools:1.8.95` 里的旧 `aktools` 在首页 `GET /` 调用 `get_latest_version("akshare")`，用 BeautifulSoup 解析 `pypi.org` HTML。页面结构变了或容器访问不了 PyPI 时，`soup.find(...)` 为 `None`，随后 `.text.strip()` 炸成 500。TradingAgents 只打 `/api/public/<接口>`，不受首页影响。

## 确认方案

`docker/aktools.Dockerfile` 把 `sitecustomize` 放进 `PYTHONPATH=/opt/aktools-patch`，把 `aktools.utils.get_latest_version` 替换为返回 `"offline"`。健康检查用 `/docs`，不用 `/`。
