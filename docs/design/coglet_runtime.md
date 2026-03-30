# CogletRuntime — Design & API Spec

*A daemon process that manages coglet supervision trees via REST API and MCP.*

## Overview

CogletRuntime is a persistent process that:
1. Spawns coglets from CogBase bundles (.cog directories)
2. Manages their lifecycle (start, stop, restart with backoff)
3. Exposes channel subscriptions (observe) and control commands (guide)
4. Injects capabilities (runtime reference) into spawned coglets
5. Serves a REST API + MCP endpoint for external control

Eventually, CogOS will be the runtime host. For now, CogletRuntime is a standalone FastAPI daemon.

## Architecture

```
                    ┌─────────────────────────────────────────┐
                    │            CogletRuntime                 │
                    │                                         │
 CLI / MCP Client   │  ┌──────────┐   ┌───────────────────┐  │
 ─── HTTP/MCP ────>│  │ FastAPI  │──>│ Runtime Engine     │  │
                    │  │ + MCP    │   │                   │  │
                    │  └──────────┘   │  spawn(CogBase)   │  │
                    │                 │  shutdown()        │  │
                    │                 │  tree()            │  │
                    │                 │  handle_child_error│  │
                    │                 └──────┬────────────┘  │
                    │                        │               │
                    │   ┌────────────────────┼─────────┐     │
                    │   │ Coglet Tree        │         │     │
                    │   │   RootCoglet ──> Child ──> Leaf    │
                    │   │     │               │         │    │
                    │   │   channels       channels     │    │
                    │   └──────────────────────────────┘     │
                    └─────────────────────────────────────────┘
```

## CogBase — The Spawn Primitive

A CogBase is a bundle of assets that produces a Coglet:

```python
@dataclass
class CogBase:
    cls: Type              # Coglet class to instantiate
    kwargs: dict[str, Any] # Constructor arguments
    restart: str           # "never" | "on_error" | "always"
    max_restarts: int      # Max restart attempts (default 3)
    backoff_s: float       # Initial backoff delay (doubles each attempt)
```

On disk, a CogBase is a `.cog` directory:

```
app.cog/
├── manifest.toml      # Declares cls, kwargs, restart policy
└── *.py               # Python modules (added to sys.path at spawn)
```

## Runtime Engine

### Lifecycle

```
runtime.spawn(base, parent=None) -> CogletHandle
    1. Instantiate: base.cls(**base.kwargs)
    2. Inject runtime: coglet._runtime = self
    3. Install tracing (if enabled)
    4. Call on_start() (if LifeLet)
    5. Start tickers (if TickLet)
    6. Return CogletHandle

runtime.shutdown()
    1. Stop all coglets in reverse spawn order (LIFO)
    2. For each: stop tickers, call on_stop()
    3. Close trace file
```

### Capability Injection

When a coglet is spawned, the runtime injects itself as `coglet._runtime`. This enables:

```python
# Inside any Coglet:
handle = await self.create(CogBase(...))  # delegates to self._runtime.spawn()
```

The runtime is the **only** capability injected. All other capabilities (memory, LLM, etc.) are passed as constructor kwargs via the CogBase.

### Supervision

On child error, the runtime:
1. Asks the parent: `parent.on_child_error(handle, error) -> "restart"|"stop"|"escalate"`
2. If restart: exponential backoff (`backoff_s * 2^attempt`), up to `max_restarts`
3. The CogletHandle is preserved — it transparently points to the new instance
4. If stop: calls `_stop_coglet()` (tickers + on_stop)
5. If escalate: re-raises the error

## REST API

Default port: `4510`. Override with `--port`.

### POST /create

Spawn a coglet from a .cog directory.

**Query params:** `cog_dir` (absolute path to .cog directory)

**Response:**
```json
{"id": "0", "class": "MyCoglet"}
```

### POST /stop/{coglet_id}

Stop a specific coglet and remove it from the registry.

**Response:**
```json
{"msg": "stopped MyCoglet (id=0)"}
```

### POST /guide/{coglet_id}

Send a control-plane command to a coglet's `@enact` handlers.

**Query params:** `command` (string), `data` (optional JSON)

**Response:**
```json
{"msg": "sent 'reload' to 0"}
```

### GET /observe/{coglet_id}/{channel}

Subscribe to a coglet's channel output as Server-Sent Events (SSE).

Each event:
```
data: {"key": "value"}
```

The stream stays open until the client disconnects.

### GET /status

Return the full runtime state.

**Response:**
```json
{
  "tree": "CogletRuntime\n└── MyCoglet [LifeLet]\n    └── Child [TickLet]",
  "coglets": [
    {"id": "0", "class": "MyCoglet", "cog_dir": "/path/to/app.cog", "children": 1}
  ]
}
```

### GET /tree

Return just the ASCII tree visualization.

**Response:**
```json
{"tree": "CogletRuntime\n└── ..."}
```

### POST /shutdown

Gracefully shut down the entire runtime.

**Response:**
```json
{"msg": "shutting down"}
```

## MCP Endpoint

All REST endpoints are automatically exposed as MCP tools via `fastapi-mcp` at `/mcp`. Any MCP client (Claude Code, etc.) can connect and use the runtime as a tool server:

- `create_coglet` — spawn from .cog dir
- `stop_coglet` — stop by id
- `guide_coglet` — send command
- `observe_coglet` — subscribe to channel (SSE)
- `runtime_status` — get status
- `runtime_tree` — get tree
- `shutdown_runtime` — shutdown

## CLI

The `coglet` CLI is a thin client over the REST API:

```bash
# Start the daemon
coglet runtime start [--port 4510] [--trace events.jsonl]

# Spawn a coglet
coglet create path/to/app.cog    # prints coglet_id

# Interact
coglet guide 0 reload '{"key": "val"}'
coglet observe 0 results --follow

# Manage
coglet runtime status
coglet stop 0
coglet runtime stop

# One-shot mode (no daemon, original behavior)
coglet run path/to/app.cog
```

## Channel Mappings

Channels are per-coglet async pub/sub queues. The runtime does not own channels — each Coglet has its own `ChannelBus`. The runtime exposes them externally via `/observe`.

Key properties:
- Subscribers must exist before transmit (no replay)
- Each subscriber gets an independent queue (no message loss from slow consumers)
- Channels are created on demand
- The `/observe` SSE endpoint creates a subscription for the lifetime of the HTTP connection

## Future: CogOS Integration

CogOS will eventually replace the standalone daemon:
- CogOS manages processes, networking, and resource allocation
- CogletRuntime becomes a library embedded in CogOS
- The REST/MCP API remains the same — only the host changes
- .cog directories become deployable units in CogOS

The current standalone daemon is a stepping stone. The API contract is stable.
