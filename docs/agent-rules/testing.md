# 测试约定

框架：pytest。配置在 `pyproject.toml`：`testpaths = ["tests"]`，`addopts = -ra --strict-markers`。标记：`unit` / `integration` / `smoke`。

## 现有夹具（不要拆掉）

`tests/conftest.py`：

- 自动给供应商 API key 填 placeholder，避免 CI 因缺 key 挂起
- 每个测试重置 `dataflows.config._config` 为深拷贝的 `DEFAULT_CONFIG`（`set_config` 会 merge，会泄漏）
- `mock_llm_client` 补丁 `create_llm_client`

新测试若改全局配置，依赖上述隔离，不要自己留残键。

## 怎么写

- 文件：`tests/test_<area>.py`；函数：`test_<behavior>_<condition>`
- 断言用朴素 `assert`；能用 fixture / `tmp_path` 就不要手写临时目录清理
- 只 mock 外部 I/O（HTTP、yfinance、LLM SDK）。不要 mock 被测模块的内部私有函数，除非现有测试已有该模式
- 修 bug 先补一条改前会失败的回归
- 图形状 / path_map / 分析师 key 的改动要对齐 `test_analyst_execution.py`、`test_risk_router_path_map.py`、`test_checkpoint_*`

## 要跑的命令

```bash
pytest -q
# 或聚焦
pytest tests/test_vendor_routing.py -q
ruff check .
```

需要外网或真密钥的路径保持 mock。不要把真实 `.env` 拷进测试。

## 不要做的

- 为了绿而删断言或把测试改成测 mock 本身
- 新增依赖真实付费 API 且默认会在 CI 跑的用例
- 声称完成却未跑与改动类型对应的测试
