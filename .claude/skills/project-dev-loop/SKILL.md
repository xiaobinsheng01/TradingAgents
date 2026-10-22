---
name: project-dev-loop
description: >-
  Runs the TradingAgents repository development closed loop: scan Tech Library,
  read PROJECT, load canonical rules, reuse existing code, implement with tests,
  sync docs, and archive confirmed schemes. Use when implementing features,
  fixing bugs, refactoring, changing graph/agents/dataflows/llm_clients/CLI, or
  when the user mentions 开发闭环, project-dev-loop, Tech Library, or
  PROJECT/ARCHITECTURE updates.
---

# project-dev-loop

Cross-tool development loop for this repository. Load facts from docs and code. Do not copy module lists, routes, or model IDs into this skill.

Document priority: **code > docs/PROJECT.md > docs/ARCHITECTURE.md > topic docs / Tech Library**.

Canonical rules live only in `docs/agent-rules/`. Tool adapters must not duplicate them.

## Progress checklist

Copy and track:

```
- [ ] 0. Scan Tech Library
- [ ] 1. Read PROJECT.md
- [ ] 2. Load matching canonical rules
- [ ] 3. Explore reuse
- [ ] 4. Confirm the scheme when the task is complex
- [ ] 5. Implement on existing layers
- [ ] 6. Add and run tests
- [ ] 7. Write back project facts
- [ ] 8. Archive Tech Library when triggered
- [ ] 9. Final close-out check
```

## 0. Scan Tech Library

Read `docs/tech-library/README.md`. If the topic matches an entry, read that file.

## 1. Read PROJECT.md

Read `docs/PROJECT.md` before designing. Use `docs/ARCHITECTURE.md` when topology, state, or extension points matter.

## 2. Load matching canonical rules

Always load:

- `docs/agent-rules/project-context.md`
- `docs/agent-rules/docs-maintenance.md`

Then load every match:

| Area | Canonical rule |
| --- | --- |
| Python | `docs/agent-rules/language-conventions.md` |
| dataflows, vendor tools | `docs/agent-rules/api-layer.md` |
| graph, agents, CLI | `docs/agent-rules/service-layer.md` |
| AgentState, schemas, llm_clients | `docs/agent-rules/model-layer.md` |
| tests | `docs/agent-rules/testing.md` |
| Any request to add a queue/worker/consumer | `docs/agent-rules/mq-consumer.md` |

When Python changes, load the language baseline **and** the matching layer rule.

## 3. Explore reuse

Search the repo for the same job. Prefer existing helpers listed in PROJECT.md over new abstractions.

## 4. Confirm the scheme

For multi-file, architectural, or breaking work: state the approach against current code, then implement. Do not import another project's API/Service/MQ/ORM layout.

## 5. Implement

Follow the layers that already exist. Keep diffs focused. Do not commit `.env`, secrets, virtualenvs, or generated caches.

## 6. Test

Add or update tests for behavior changes. Run the commands in PROJECT.md that match the change type (at least the focused pytest file and `ruff check` on touched Python).

## 7. Write back docs

If directory layout, call chains, config, reuse lists, or extension points changed, update PROJECT.md and/or ARCHITECTURE.md. Refresh "最后更新日期".

## 8. Archive Tech Library

Archive when a scheme is confirmed and landed or explicitly cancelled (plan, external link, agent discussion, bug root cause, breaking change, concluded POC, major dependency bump).

Skip typo/format-only work, behavior-free refactors, inconclusive debugging, and unconfirmed drafts.

File: `docs/tech-library/YYYYMMDD-<slug>.md` with the header fields in the Tech Library README. Update the index. Put Plan flow diagrams in the scheme file, or redraw the landed call chain in ARCHITECTURE.md.

## 9. Close-out

Do not claim done if any of these is missing:

- behavior change without tests
- stale PROJECT / ARCHITECTURE facts
- a scheme that should have been archived

Report: files touched, reuse choices, commands run, doc/tech-library status, leftover risks.

This loop is a soft team contract (docs, skills, rules, review). Do not add GitHub hard gates in this skill's scope.
