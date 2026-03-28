# Coglet Improvements

Architectural improvements informed by comparative analysis with similar systems
(Erlang/OTP, holonic systems, subsumption architecture, CLARION, HRL Options Framework).

See also: [coglet.md](coglet.md) for core architecture.

## 1. SuppressLet Mixin

**Inspired by:** Brooks' subsumption architecture (suppress/inhibit mechanism)

A COG can suppress specific channels or commands on a LET without replacing its logic.
The LET keeps running but its outputs are gated. Cheaper than stop/restart, preserves
internal state.

```python
await self.guide(handle, Command("suppress", {"channels": ["actions"]}))
# LET keeps computing, but action outputs are silenced
await self.guide(handle, Command("unsuppress", {"channels": ["actions"]}))
```

Meta-commands (`suppress`/`unsuppress`) always pass through the gate.

## 2. Coglet Tree Visualization

**Inspired by:** LangGraph/LangSmith observability

`CogletRuntime.tree()` returns an ASCII visualization of the live supervision tree
with mixin annotations and channel stats.

```
CogletRuntime
└── PlayerCoglet [GitLet, LifeLet]
    ├── PolicyCoglet#0 [CodeLet, LifeLet, TickLet]
    │   channels: obs(2 subs), actions(1 subs), log(1 subs)
    └── PolicyCoglet#1 [CodeLet, LifeLet, TickLet]
        channels: obs(2 subs), actions(1 subs)
```

## 3. Channel Trace / Replay

**Inspired by:** LangSmith tracing, Ray lineage reconstruction

Optional tracing that logs every `transmit()` and `guide()` with timestamps to a
jsonl file. Each line: `{timestamp, coglet, op, channel_or_command, data}`.
Enables post-mortem debugging of async event flows.

## 4. Ticker Error Handling

**Inspired by:** Erlang/OTP "let it crash" + supervision

Currently `TickLet._time_ticker` has no error handling — if a ticker raises, the
asyncio task dies silently. Add try/except with an overridable `on_ticker_error()`
hook. Default: log and continue.

## 5. Restart Policy

**Inspired by:** OTP supervision strategies (one-for-one with backoff)

Add `restart`, `max_restarts`, `backoff_s` fields to `CogletConfig`. Runtime wraps
child lifecycle with supervision: on error, optionally restart with exponential
backoff up to max_restarts.

## 6. `on_child_error` Hook

**Inspired by:** OTP supervisor callbacks

Parent COG gets a hook when a child coglet errors. Returns `"restart"`, `"stop"`,
or `"escalate"`. Default: stop. This is the one-for-one strategy — no AllForOne
unless someone needs it.

## 7. LazyCogletHandle (Virtual Actors)

**Inspired by:** Orleans virtual actors, Proto.Actor grains

`create()` with `lazy=True` returns a handle that instantiates on first `guide()`
or `observe()`. Deactivates after `idle_timeout_s`. Useful for MulLet with large N.

---

## Priority

| # | Improvement | Effort | Status |
|---|------------|--------|--------|
| 1 | SuppressLet | Small | TODO |
| 2 | Tree visualization | Small | TODO |
| 3 | Channel tracing | Medium | TODO |
| 4 | Ticker error handling | Small | TODO |
| 5 | Restart policy | Medium | TODO |
| 6 | on_child_error hook | Small | TODO |
| 7 | LazyCogletHandle | Medium | Deferred |
