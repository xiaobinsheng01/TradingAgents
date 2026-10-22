# 消息队列层（当前不存在）

评估结果：仓库里**没有** MQ producer/consumer、没有 Celery/RQ/Kafka/Rabbit 任务循环。`redis` 在依赖里，但不是消息总线实现。

checkpoint SQLite 与 memory log **不是** 队列。

## 默认行为

- 不要新增 `consumers/`、`workers/`、监听循环来“对齐其它项目的 mq-consumer 规则”
- 不要把 LangGraph 节点伪装成 MQ handler

## 若未来确实需要

1. 先写确认方案（来源、负载、失败重试、与 `propagate` 生命周期的关系）
2. 归档到 Tech Library
3. 回写 PROJECT / ARCHITECTURE
4. 再实现，并补集成测试

在此之前，本规则的作用是阻止误加该层。
