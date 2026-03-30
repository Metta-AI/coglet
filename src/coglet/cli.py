"""coglet CLI — manage a persistent coglet runtime via FastAPI.

Commands:
    coglet runtime start [--port PORT] [--trace PATH]
        Start the runtime as a FastAPI server (with MCP endpoint)

    coglet runtime stop [--port PORT]
        Stop the runtime server

    coglet runtime status [--port PORT]
        Show runtime status and coglet tree

    coglet create PATH.cog [--port PORT]
        Spawn a coglet from a .cog directory, prints coglet_id

    coglet stop ID [--port PORT]
        Stop a specific coglet

    coglet observe ID CHANNEL [--follow] [--port PORT]
        Subscribe to a coglet's channel output via SSE

    coglet guide ID COMMAND [DATA] [--port PORT]
        Send a command to a coglet via @enact

    coglet run PATH.cog [--trace PATH]
        One-shot: start runtime, spawn coglet, wait for ctrl-c

MCP endpoint is served at /mcp — connect any MCP client to it.

A .cog directory contains:
    manifest.toml   — declares the coglet class and config
    *.py            — Python modules importable by the coglet
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import sys
import tomllib
from pathlib import Path
from typing import Any

from coglet.handle import CogBase, Command
from coglet.runtime import CogletRuntime
from coglet.trace import CogletTrace

DEFAULT_PORT = 4510


# ---------------------------------------------------------------------------
# Manifest helpers
# ---------------------------------------------------------------------------

def load_manifest(cog_dir: Path) -> dict[str, Any]:
    manifest_path = cog_dir / "manifest.toml"
    if not manifest_path.exists():
        sys.exit(f"error: {manifest_path} not found")
    with open(manifest_path, "rb") as f:
        manifest = tomllib.load(f)
    if "coglet" not in manifest or "class" not in manifest["coglet"]:
        sys.exit("error: manifest.toml must have [coglet] with 'class' key")
    return manifest


def resolve_class(dotted: str, cog_dir: Path) -> type:
    parts = dotted.rsplit(".", 1)
    if len(parts) != 2:
        sys.exit(f"error: class must be 'module.ClassName', got '{dotted}'")
    module_name, class_name = parts
    cog_str = str(cog_dir.resolve())
    if cog_str not in sys.path:
        sys.path.insert(0, cog_str)
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as e:
        sys.exit(f"error: cannot import module '{module_name}': {e}")
    cls = getattr(module, class_name, None)
    if cls is None:
        sys.exit(f"error: class '{class_name}' not found in '{module_name}'")
    return cls


def build_config(manifest: dict[str, Any], cls: type) -> CogBase:
    kwargs = dict(manifest["coglet"].get("kwargs", {}))
    config_section = manifest.get("config", {})
    return CogBase(
        cls=cls,
        kwargs=kwargs,
        restart=config_section.get("restart", "never"),
        max_restarts=config_section.get("max_restarts", 3),
        backoff_s=config_section.get("backoff_s", 1.0),
    )


def load_cogbase(cog_dir: Path) -> CogBase:
    manifest = load_manifest(cog_dir)
    cls = resolve_class(manifest["coglet"]["class"], cog_dir)
    return build_config(manifest, cls)


# ---------------------------------------------------------------------------
# Serialization helper
# ---------------------------------------------------------------------------

def _serialize(obj: Any) -> Any:
    if isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_serialize(v) for v in obj]
    return str(obj)


# ---------------------------------------------------------------------------
# FastAPI runtime server
# ---------------------------------------------------------------------------

def create_app(trace_path: str | None = None):
    """Create the FastAPI app with all runtime endpoints + MCP."""
    import signal

    from fastapi import FastAPI, HTTPException
    from fastapi.responses import StreamingResponse
    from fastapi_mcp import FastApiMCP

    app = FastAPI(title="coglet-runtime", description="Coglet runtime API")

    trace = CogletTrace(trace_path) if trace_path else None
    runtime = CogletRuntime(trace=trace)
    registry: dict[str, tuple[Any, str, str]] = {}  # id -> (handle, cog_dir, class_name)
    next_id = [0]

    def alloc_id() -> str:
        cid = str(next_id[0])
        next_id[0] += 1
        return cid

    # --- POST /create ---
    @app.post("/create", operation_id="create_coglet")
    async def create_coglet(cog_dir: str):
        """Spawn a coglet from a .cog directory. Returns the coglet_id."""
        path = Path(cog_dir)
        if not path.is_dir():
            raise HTTPException(404, f"'{cog_dir}' is not a directory")
        base = load_cogbase(path)
        handle = await runtime.spawn(base)
        cid = alloc_id()
        class_name = type(handle.coglet).__name__
        registry[cid] = (handle, str(path), class_name)
        return {"id": cid, "class": class_name}

    # --- POST /stop/{coglet_id} ---
    @app.post("/stop/{coglet_id}", operation_id="stop_coglet")
    async def stop_coglet(coglet_id: str):
        """Stop a running coglet by id."""
        entry = registry.get(coglet_id)
        if not entry:
            raise HTTPException(404, f"no coglet with id '{coglet_id}'")
        handle, _, class_name = entry
        await runtime._stop_coglet(handle.coglet)
        del registry[coglet_id]
        return {"msg": f"stopped {class_name} (id={coglet_id})"}

    # --- POST /guide/{coglet_id} ---
    @app.post("/guide/{coglet_id}", operation_id="guide_coglet")
    async def guide_coglet(coglet_id: str, command: str, data: Any = None):
        """Send a command to a coglet's @enact handlers."""
        entry = registry.get(coglet_id)
        if not entry:
            raise HTTPException(404, f"no coglet with id '{coglet_id}'")
        handle = entry[0]
        await handle.guide(Command(type=command, data=data))
        return {"msg": f"sent '{command}' to {coglet_id}"}

    # --- GET /observe/{coglet_id}/{channel} ---
    @app.get("/observe/{coglet_id}/{channel}", operation_id="observe_coglet")
    async def observe_coglet(coglet_id: str, channel: str):
        """Subscribe to a coglet's channel output (SSE stream)."""
        entry = registry.get(coglet_id)
        if not entry:
            raise HTTPException(404, f"no coglet with id '{coglet_id}'")
        handle = entry[0]
        sub = handle.coglet._bus.subscribe(channel)

        async def event_stream():
            try:
                async for event_data in sub:
                    payload = json.dumps(_serialize(event_data))
                    yield f"data: {payload}\n\n"
            except (asyncio.CancelledError, GeneratorExit):
                pass

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    # --- GET /status ---
    @app.get("/status", operation_id="runtime_status")
    async def status():
        """Show runtime status: tree visualization and coglet list."""
        coglets = []
        for cid, (handle, cog_dir, class_name) in registry.items():
            coglets.append({
                "id": cid,
                "class": class_name,
                "cog_dir": cog_dir,
                "children": len(handle.coglet._children),
            })
        return {"tree": runtime.tree(), "coglets": coglets}

    # --- POST /shutdown ---
    @app.post("/shutdown", operation_id="shutdown_runtime")
    async def shutdown():
        """Shut down the runtime and exit."""
        async def _shutdown():
            await asyncio.sleep(0.5)
            await runtime.shutdown()
            import os
            os.kill(os.getpid(), signal.SIGTERM)
        asyncio.create_task(_shutdown())
        return {"msg": "shutting down"}

    # --- GET /tree ---
    @app.get("/tree", operation_id="runtime_tree")
    async def tree():
        """Return ASCII tree visualization of the coglet hierarchy."""
        return {"tree": runtime.tree()}

    # --- MCP endpoint ---
    mcp = FastApiMCP(app, name="coglet-runtime", description="Coglet runtime MCP server")
    mcp.mount_http()

    return app


def start_server(port: int, trace_path: str | None = None) -> None:
    """Start the FastAPI server with uvicorn."""
    import uvicorn
    app = create_app(trace_path=trace_path)
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


# ---------------------------------------------------------------------------
# Client helpers — HTTP calls to the runtime API
# ---------------------------------------------------------------------------

def _base_url(port: int) -> str:
    return f"http://127.0.0.1:{port}"


def _post(port: int, path: str, **params) -> dict:
    import urllib.request
    url = f"{_base_url(port)}{path}"
    if params:
        url += "?" + "&".join(f"{k}={v}" for k, v in params.items() if v is not None)
    req = urllib.request.Request(url, method="POST", data=b"")
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.URLError as e:
        sys.exit(f"error: cannot connect to runtime on port {port}: {e}")


def _get(port: int, path: str) -> dict:
    import urllib.request
    url = f"{_base_url(port)}{path}"
    try:
        with urllib.request.urlopen(url) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.URLError as e:
        sys.exit(f"error: cannot connect to runtime on port {port}: {e}")


def _observe_sse(port: int, coglet_id: str, channel: str, follow: bool) -> None:
    """Stream SSE events from /observe endpoint."""
    import urllib.request
    url = f"{_base_url(port)}/observe/{coglet_id}/{channel}"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req) as resp:
            for raw_line in resp:
                line = raw_line.decode().strip()
                if line.startswith("data: "):
                    payload = line[6:]
                    print(payload)
                    if not follow:
                        return
    except KeyboardInterrupt:
        pass
    except urllib.error.URLError as e:
        sys.exit(f"error: cannot connect to runtime on port {port}: {e}")


# ---------------------------------------------------------------------------
# One-shot run (no daemon)
# ---------------------------------------------------------------------------

async def run_oneshot(cog_dir: Path, trace_path: str | None = None) -> None:
    import signal as sig
    base = load_cogbase(cog_dir)
    trace = CogletTrace(trace_path) if trace_path else None
    runtime = CogletRuntime(trace=trace)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for s in (sig.SIGINT, sig.SIGTERM):
        loop.add_signal_handler(s, stop.set)

    await runtime.run(base)
    print(runtime.tree())
    await stop.wait()

    print("\nshutting down...")
    await runtime.shutdown()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    # Shared args across all subcommands
    port_args = argparse.ArgumentParser(add_help=False)
    port_args.add_argument("--port", type=int, default=DEFAULT_PORT,
                           help=f"runtime API port (default: {DEFAULT_PORT})")

    parser = argparse.ArgumentParser(
        prog="coglet",
        description="Manage coglet runtimes and coglets.",
    )
    sub = parser.add_subparsers(dest="command")

    # --- coglet runtime start|stop|status ---
    rt = sub.add_parser("runtime", help="manage the runtime daemon")
    rt_sub = rt.add_subparsers(dest="action")
    rt_start = rt_sub.add_parser("start", parents=[port_args], help="start the runtime server")
    rt_start.add_argument("--trace", type=str, default=None, help="trace output path")
    rt_sub.add_parser("stop", parents=[port_args], help="stop the runtime server")
    rt_sub.add_parser("status", parents=[port_args], help="show runtime status and tree")

    # --- coglet create PATH.cog ---
    cr = sub.add_parser("create", parents=[port_args], help="spawn a coglet from a .cog directory")
    cr.add_argument("cog_dir", type=Path, help="path to .cog directory")

    # --- coglet stop ID ---
    st = sub.add_parser("stop", parents=[port_args], help="stop a coglet by id")
    st.add_argument("id", type=str, help="coglet id")

    # --- coglet observe ID CHANNEL ---
    ob = sub.add_parser("observe", parents=[port_args], help="observe a coglet's channel")
    ob.add_argument("id", type=str, help="coglet id")
    ob.add_argument("channel", type=str, help="channel name")
    ob.add_argument("--follow", action="store_true", help="keep streaming")

    # --- coglet guide ID COMMAND [DATA] ---
    gu = sub.add_parser("guide", parents=[port_args], help="send a command to a coglet")
    gu.add_argument("id", type=str, help="coglet id")
    gu.add_argument("cmd_type", metavar="command", type=str, help="command type")
    gu.add_argument("data", nargs="?", default=None, help="command data (JSON string)")

    # --- coglet run PATH.cog ---
    rn = sub.add_parser("run", help="one-shot: start runtime, spawn, wait for ctrl-c")
    rn.add_argument("cog_dir", type=Path, help="path to .cog directory")
    rn.add_argument("--trace", type=str, default=None, help="trace output path")

    args = parser.parse_args()
    port = args.port

    if args.command == "runtime":
        if args.action == "start":
            start_server(port, trace_path=args.trace)
        elif args.action == "stop":
            resp = _post(port, "/shutdown")
            print(resp.get("msg", resp))
        elif args.action == "status":
            resp = _get(port, "/status")
            print(resp["tree"])
            if resp["coglets"]:
                print()
                for c in resp["coglets"]:
                    print(f"  id={c['id']}  class={c['class']}  children={c['children']}  cog_dir={c['cog_dir']}")
            else:
                print("\nno coglets running.")
        else:
            parser.parse_args(["runtime", "--help"])

    elif args.command == "create":
        if not args.cog_dir.is_dir():
            sys.exit(f"error: '{args.cog_dir}' is not a directory")
        resp = _post(port, "/create", cog_dir=str(args.cog_dir.resolve()))
        print(resp["id"])

    elif args.command == "stop":
        resp = _post(port, f"/stop/{args.id}")
        print(resp.get("msg", resp))

    elif args.command == "observe":
        _observe_sse(port, args.id, args.channel, args.follow)

    elif args.command == "guide":
        data_val = None
        if args.data:
            try:
                data_val = json.loads(args.data)
            except json.JSONDecodeError:
                data_val = args.data
        # Build query params
        params = {"command": args.cmd_type}
        if data_val is not None:
            params["data"] = json.dumps(data_val) if not isinstance(data_val, str) else data_val
        resp = _post(port, f"/guide/{args.id}", **params)
        print(resp.get("msg", resp))

    elif args.command == "run":
        if not args.cog_dir.is_dir():
            sys.exit(f"error: '{args.cog_dir}' is not a directory")
        asyncio.run(run_oneshot(args.cog_dir, trace_path=args.trace))

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
