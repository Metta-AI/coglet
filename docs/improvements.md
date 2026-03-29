# Coglet Improvements

Architectural improvements informed by comparative analysis with similar systems
(Erlang/OTP, holonic systems, subsumption architecture, CLARION, HRL Options Framework).

See also: [coglet.md](coglet.md) for core architecture.

## 1. SuppressLet Mixin

**Inspired by:** Brooks' subsumption architecture (suppress/inhibit mechanism)

**Status: Implemented** — `src/coglet/suppresslet.py`

A COG can suppress specific channels or commands on a LET without replacing its logic.
The LET keeps running but its outputs are gated. Cheaper than stop/restart, preserves
internal state.

```python
await self.guide(handle, Command("suppress", {"channels": ["actions"]}))
# LET keeps computing, but action outputs are silenced
await self.guide(handle, Command("unsuppress", {"channels": ["actions"]}))
```

Meta-commands (`suppress`/`unsuppress`) always pass through the gate. SuppressLet
must appear before Coglet in the MRO to intercept `transmit()` and `_dispatch_enact()`.

## 2. Coglet Tree Visualization

**Inspired by:** LangGraph/LangSmith observability

**Status: Implemented** — `CogletRuntime.tree()` in `src/coglet/runtime.py`

Returns an ASCII visualization of the live supervision tree with mixin annotations,
channel subscriber counts, and suppression state.

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

**Status: Implemented** — `src/coglet/trace.py`, integrated into `CogletRuntime`

Optional tracing that logs every `transmit()` and `guide()` with timestamps to a
jsonl file. Each line: `{t, coglet, op, target, data}`.

```python
trace = CogletTrace("trace.jsonl")
rt = CogletRuntime(trace=trace)
# ... run coglets ...
# trace.jsonl contains all transmit/enact events with timestamps

entries = CogletTrace.load("trace.jsonl")  # replay/inspect
```

The runtime wraps each coglet's `transmit()` and `_dispatch_enact()` transparently
when a trace is active. No code changes needed in coglet implementations.

## 4. Ticker Error Handling

**Inspired by:** Erlang/OTP "let it crash" + supervision

**Status: Implemented** — `TickLet.on_ticker_error()` in `src/coglet/ticklet.py`

Previously, if a `@every` ticker raised an exception, the asyncio task died silently.
Now exceptions are caught and routed to `on_ticker_error(method_name, error)`.

Default behavior: log via LogLet if the coglet mixes it in, otherwise ignore and
continue. Override `on_ticker_error()` to customize (e.g., count failures, escalate).

`asyncio.CancelledError` is re-raised to allow clean shutdown.

## 5. Restart Policy

**Inspired by:** OTP supervision strategies (one-for-one with backoff)

**Status: Implemented** — `CogletConfig` fields + `CogletRuntime` restart logic

`CogletConfig` now accepts:
- `restart: str` — `"never"` (default), `"on_error"`, or `"always"`
- `max_restarts: int` — maximum restart attempts (default 3)
- `backoff_s: float` — base backoff delay in seconds (default 1.0), doubles each attempt

The runtime's `handle_child_error()` consults the parent's `on_child_error()` hook,
then applies the restart policy with exponential backoff. The `CogletHandle` is
preserved across restarts — it points to the new coglet instance transparently.

## 6. `on_child_error` Hook

**Inspired by:** OTP supervisor callbacks

**Status: Implemented** — `Coglet.on_child_error()` in `src/coglet/coglet.py`

Parent COG gets a hook when a child coglet errors. Returns one of:
- `"restart"` — restart the child (respects CogletConfig limits)
- `"stop"` — stop the child (default)
- `"escalate"` — re-raise the error in this coglet

This is the one-for-one strategy. AllForOne not implemented (Akka's experience
shows it's rarely needed).

## 7. LazyCogletHandle (Virtual Actors)

**Inspired by:** Orleans virtual actors, Proto.Actor grains

**Status: Deferred**

`create()` with `lazy=True` would return a handle that instantiates on first `guide()`
or `observe()`. Deactivates after `idle_timeout_s`. Useful for MulLet with large N.

---

## Status

| # | Improvement | Files | Status |
|---|------------|-------|--------|
| 1 | SuppressLet | `suppresslet.py` | Done |
| 2 | Tree visualization | `runtime.py` | Done |
| 3 | Channel tracing | `trace.py`, `runtime.py` | Done |
| 4 | Ticker error handling | `ticklet.py` | Done |
| 5 | Restart policy | `handle.py`, `runtime.py` | Done |
| 6 | on_child_error hook | `coglet.py`, `runtime.py` | Done |
| 7 | LazyCogletHandle | — | Deferred |
