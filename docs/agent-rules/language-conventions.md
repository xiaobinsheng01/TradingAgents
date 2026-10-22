# 语言约定（Python）

基线以本仓库为准：`requires-python >= 3.10`，ruff 目标 `py310`。

## 风格

- 格式/lint：`ruff check`（`pyproject.toml`：E/W/F/I/B/UP/C4/SIM，忽略 E501）
- 公开函数写类型标注；优先 `list[str]`、`dict[str, T]`、`X | None`
- 路径用 `pathlib.Path`；需要拼 ticker 时先 `safe_ticker_component`
- 配置与用户输入在边界校验；非法值失败要响（参考 `_coerce`、`_coerce_max_retries`）
- 库代码用 `logging.getLogger(__name__)`；不要用 `print` 做诊断（CLI 用户输出除外）
- `__init__.py` 的有意再导出可保留（ruff `F401` 已按文件忽略）

## 错误

- 捕获最窄异常。供应商路径抛 `VendorError` 子类，不要丢空字符串。
- 失败先带标识打日志（ticker、method、vendor），再抛出或 `raise ... from e`
- 禁止裸 `except:` 和静默 `except Exception: pass`
- 身份解析等“失败则降级”必须有注释过的理由，并返回明确空值，不能假装成功拿到公司名

## 配置与密钥

- 新配置键加到 `DEFAULT_CONFIG`；需要环境覆盖则加 `_ENV_OVERRIDES` 一行
- 新 LLM 供应商的密钥名加到 `PROVIDER_API_KEY_ENV`
- 不硬编码 API key；`.env` 由 `tradingagents/__init__.py` 以 `override=False` 加载

## 导入

- 代理与 graph 从 `tradingagents.agents.utils.agent_utils` 取工具，不直接抄 vendor 模块
- LLM 只经 `create_llm_client`；factory 保持懒导入
- 不要引入第二套依赖管理器；最小依赖，优先标准库

## 兼容

- 新代码不要用 `create_social_media_analyst`
- 分析师 wire key `social` 不要改名（旧配置依赖它）
- 需要 3.10 可运行的写法（不要无故使用仅 3.11+ 的语法，除非同时提高 requires-python）
