# AKTools 冻结镜像拒收六位 A 股代码

- 日期：2026-09-15
- 状态：done
- 来源：bugfix
- 原链接：https://aktools.akfamily.xyz/aktools/
- 关联模块：docker/aktools.Dockerfile, docker-compose.yml
- 回写文档：docs/PROJECT.md, docs/ARCHITECTURE.md, docs/tech-library/20260915-akshare-aktools-http.md
- 替代关系：落地 [20260915-akshare-aktools-http.md](20260915-akshare-aktools-http.md) 里「升级 akshare>=1.16」；不改 `route_to_vendor`

## 结论

官方 `akfamily/aktools:1.8.95` 内嵌 **akshare 1.8.94**。`GET /api/public/<接口>?symbol=000001` 返回：

`请输入正确的参数错误 '000001'，请升级 AKShare 到最新版本`

这不是 ticker 写错。容器内现场 `pip install` 每次约 10+ 分钟，不能绑在 `compose up`。

## 确认方案

compose `akshare` profile 构建 [`docker/aktools.Dockerfile`](../../docker/aktools.Dockerfile)：`python:3.12-slim` + `akshare>=1.16` + `aktools>=0.0.89`（阿里云 PyPI），并钉住 `fastapi<0.116` / `starlette<1`（aktools 首页模板 API），首页 sitecustomize 一并打进镜像。首次 `--build` 慢，之后启动不再 pip。
