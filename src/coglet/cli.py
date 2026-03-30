"""coglet CLI — manage a persistent coglet runtime via FastAPI.

Commands:
    coglet runtime start [--port PORT] [--trace PATH]
    coglet runtime stop
    coglet runtime status

    coglet create PATH.cog                    -> counter-a3f1
    coglet stop ID
    coglet transmit ID:CHANNEL DATA           push data onto a channel
    coglet observe ID:CHANNEL [--follow]      subscribe to channel output
    coglet enact ID COMMAND [DATA]            send @enact command

    coglet link ID                            list channels for a coglet
    coglet link SRC:CH DEST:CH                wire channels
    coglet unlink SRC:CH DEST:CH
    coglet links

    coglet run PATH.cog [--trace PATH]        one-shot (no daemon)

IDs are "classname-xxxx" (e.g. counter-a3f1).
Channel refs use "id:channel" syntax (e.g. counter-a3f1:count).
MCP endpoint at /mcp.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib
import json
import sys
import time
import tomllib
from pathlib import Path
from typing import Any

from coglet.handle import CogBase, Command
from coglet.runtime import CogletRuntime
from coglet.trace import CogletTrace

DEFAULT_PORT = 4510


# ---------------------------------------------------------------------------
# ID generation
# ---------------------------------------------------------------------------

def _make_id(class_name: str) -> str:
    """Generate a human-readable id: lowered-classname-4hexchars."""
    # Strip common suffixes for brevity
    name = class_name
    for suffix in ("Coglet", "Cog"):
        if name.endswith(suffix) and len(name) > len(suffix):
            name = name[: -len(suffix)]
    name = name.lower()
    # 4 hex chars from hash of name + time for uniqueness
    h = hashlib.sha256(f"{class_name}{time.time_ns()}".encode()).hexdigest()[:4]
    return f"{name}-{h}"


# ---------------------------------------------------------------------------
# Channel ref parsing: "coglet_id:channel_name"
# ---------------------------------------------------------------------------

def _parse_channel_ref(ref: str) -> tuple[str, str]:
    """Parse 'id:channel' into (id, channel). Exits on bad format."""
    if ":" not in ref:
        sys.exit(f"error: expected 'id:channel', got '{ref}'")
    parts = ref.split(":", 1)
    return parts[0], parts[1]


def _parse_data(raw: str | None) -> Any:
    """Parse CLI data argument as JSON, fall back to string."""
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


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
    # id -> (handle, cog_dir, class_name)
    registry: dict[str, tuple[Any, str, str]] = {}
    # (src_id, src_ch, dest_id, dest_ch, task)
    links: list[tuple[str, str, str, str, asyncio.Task]] = []

    def _lookup(coglet_id: str):
        entry = registry.get(coglet_id)
        if not entry:
            raise HTTPException(404, f"no coglet with id '{coglet_id}'")
        return entry

    def _channels_for(coglet_id: str) -> list[str]:
        """Return list of active channel names for a coglet."""
        handle = _lookup(coglet_id)[0]
        # Channels that have been transmitted on
        bus_channels = list(handle.coglet._bus._subscribers.keys())
        # Channels from @listen handlers
        listen_channels = list(handle.coglet._listen_handlers.keys())
        return sorted(set(bus_channels + listen_channels))

    @app.post("/create", operation_id="create_coglet")
    async def create_coglet(cog_dir: str):
        """Spawn a coglet from a .cog directory. Returns the coglet_id."""
        path = Path(cog_dir)
        if not path.is_dir():
            raise HTTPException(404, f"'{cog_dir}' is not a directory")
        base = load_cogbase(path)
        handle = await runtime.spawn(base)
        class_name = type(handle.coglet).__name__
        cid = _make_id(class_name)
        registry[cid] = (handle, str(path), class_name)
        return {"id": cid, "class": class_name}

    @app.post("/stop/{coglet_id}", operation_id="stop_coglet")
    async def stop_coglet(coglet_id: str):
        """Stop a running coglet by id."""
        handle, _, class_name = _lookup(coglet_id)
        remaining = []
        for src, src_ch, dest, dest_ch, task in links:
            if src == coglet_id or dest == coglet_id:
                task.cancel()
            else:
                remaining.append((src, src_ch, dest, dest_ch, task))
        links.clear()
        links.extend(remaining)
        await runtime._stop_coglet(handle.coglet)
        del registry[coglet_id]
        return {"msg": f"stopped {class_name} (id={coglet_id})"}

    @app.post("/enact/{coglet_id}", operation_id="enact_coglet")
    async def enact_coglet(coglet_id: str, command: str, data: Any = None):
        """Send a command to a coglet's @enact handlers."""
        handle = _lookup(coglet_id)[0]
        await handle.guide(Command(type=command, data=data))
        return {"msg": f"sent '{command}' to {coglet_id}"}

    @app.post("/transmit/{coglet_id}/{channel}", operation_id="transmit_coglet")
    async def transmit_coglet(coglet_id: str, channel: str, data: Any = None):
        """Push data into a coglet's channel.

        Dispatches to the coglet's @listen handler for the channel
        (as if it received data from an external source), and also
        pushes to the channel bus (so links and observers see it).
        """
        handle = _lookup(coglet_id)[0]
        await handle.coglet._dispatch_listen(channel, data)
        await handle.coglet.transmit(channel, data)
        return {"msg": f"transmitted on {coglet_id}:{channel}"}

    @app.get("/channels/{coglet_id}", operation_id="list_channels")
    async def list_channels(coglet_id: str):
        """List all channels (transmit + @listen) for a coglet."""
        handle, _, class_name = _lookup(coglet_id)
        transmit_chs = list(handle.coglet._bus._subscribers.keys())
        listen_chs = list(handle.coglet._listen_handlers.keys())
        return {
            "id": coglet_id,
            "class": class_name,
            "transmit": sorted(transmit_chs),
            "listen": sorted(listen_chs),
        }

    @app.get("/observe/{coglet_id}/{channel}", operation_id="observe_coglet")
    async def observe_coglet(coglet_id: str, channel: str):
        """Subscribe to a coglet's channel output (SSE stream)."""
        handle = _lookup(coglet_id)[0]
        sub = handle.coglet._bus.subscribe(channel)

        async def event_stream():
            try:
                async for event_data in sub:
                    payload = json.dumps(_serialize(event_data))
                    yield f"data: {payload}\n\n"
            except (asyncio.CancelledError, GeneratorExit):
                pass

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @app.post("/link", operation_id="link_channels")
    async def link_channels(
        src_id: str, src_channel: str, dest_id: str, dest_channel: str
    ):
        """Wire src's transmit channel to dest's @listen channel.

        Every time src transmits on src_channel, the data is dispatched
        to dest's @listen(dest_channel) handler.
        """
        src_handle = _lookup(src_id)[0]
        _lookup(dest_id)  # validate dest exists
        dest_handle = registry[dest_id][0]
        sub = src_handle.coglet._bus.subscribe(src_channel)

        async def _pipe():
            try:
                async for data in sub:
                    await dest_handle.coglet._dispatch_listen(dest_channel, data)
            except asyncio.CancelledError:
                pass

        task = asyncio.create_task(_pipe())
        links.append((src_id, src_channel, dest_id, dest_channel, task))
        return {
            "msg": f"{src_id}:{src_channel} -> {dest_id}:{dest_channel}",
        }

    @app.delete("/link", operation_id="unlink_channels")
    async def unlink_channels(
        src_id: str, src_channel: str, dest_id: str, dest_channel: str
    ):
        """Remove a channel link."""
        remaining = []
        found = False
        for s, sc, d, dc, task in links:
            if s == src_id and sc == src_channel and d == dest_id and dc == dest_channel:
                task.cancel()
                found = True
            else:
                remaining.append((s, sc, d, dc, task))
        links.clear()
        links.extend(remaining)
        if not found:
            raise HTTPException(404, "link not found")
        return {"msg": f"unlinked {src_id}:{src_channel} -> {dest_id}:{dest_channel}"}

    @app.get("/links", operation_id="list_links")
    async def list_links():
        """List all active channel links."""
        return {
            "links": [
                {"src": s, "src_channel": sc, "dest": d, "dest_channel": dc}
                for s, sc, d, dc, _ in links
            ]
        }

    def _id_map() -> dict[int, str]:
        return {id(handle.coglet): cid for cid, (handle, _, _) in registry.items()}

    @app.get("/status", operation_id="runtime_status")
    async def status():
        """Show runtime status: tree, coglet list, and links."""
        coglets = []
        for cid, (handle, cog_dir, class_name) in registry.items():
            coglets.append({
                "id": cid,
                "class": class_name,
                "cog_dir": cog_dir,
                "children": len(handle.coglet._children),
                "channels": _channels_for(cid),
            })
        return {
            "tree": runtime.tree(id_map=_id_map()),
            "coglets": coglets,
            "links": [
                {"src": s, "src_channel": sc, "dest": d, "dest_channel": dc}
                for s, sc, d, dc, _ in links
            ],
        }

    @app.get("/stats/{coglet_id}", operation_id="channel_stats")
    async def channel_stats(coglet_id: str, channel: str | None = None):
        """Get message count stats (1s/5s/60s/1h/24h) and recent history."""
        handle = _lookup(coglet_id)[0]
        bus = handle.coglet._bus
        if channel:
            return {
                "channel": channel,
                "counts": bus.stats.counts(channel),
                "history": [_serialize(m) for m in bus.stats.history(channel, 10)],
            }
        return {"channels": bus.stats.all_counts()}

    @app.get("/history/{coglet_id}/{channel}", operation_id="channel_history")
    async def channel_history(coglet_id: str, channel: str, n: int = 10):
        """Get last N messages from a channel."""
        handle = _lookup(coglet_id)[0]
        msgs = handle.coglet._bus.stats.history(channel, n)
        return {"channel": channel, "messages": [_serialize(m) for m in msgs]}

    @app.get("/tree", operation_id="runtime_tree")
    async def tree():
        return {"tree": runtime.tree(id_map=_id_map())}

    @app.post("/shutdown", operation_id="shutdown_runtime")
    async def shutdown():
        async def _shutdown():
            await asyncio.sleep(0.5)
            for _, _, _, _, task in links:
                task.cancel()
            await runtime.shutdown()
            import os
            os.kill(os.getpid(), signal.SIGTERM)
        asyncio.create_task(_shutdown())
        return {"msg": "shutting down"}

    mcp = FastApiMCP(app, name="coglet-runtime", description="Coglet runtime MCP server")
    mcp.mount_http()

    return app


def start_server(port: int, trace_path: str | None = None, foreground: bool = False) -> None:
    if foreground:
        import uvicorn
        app = create_app(trace_path=trace_path)
        uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
        return

    import subprocess, sys, time
    cmd = [sys.executable, "-m", "coglet.cli", "runtime", "start", "--foreground",
           "--port", str(port)]
    if trace_path:
        cmd += ["--trace", trace_path]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            start_new_session=True)
    # Wait briefly and check the process is alive and port is responding
    time.sleep(0.5)
    if proc.poll() is not None:
        print(f"error: runtime exited immediately (code {proc.returncode})")
        sys.exit(1)
    try:
        _get(port, "/status")
        print(f"coglet runtime started (pid={proc.pid}, port={port})")
    except Exception:
        print(f"coglet runtime started (pid={proc.pid}, port={port}) [not yet responding]")


# ---------------------------------------------------------------------------
# Client helpers
# ---------------------------------------------------------------------------

def _base_url(port: int) -> str:
    return f"http://127.0.0.1:{port}"


def _post(port: int, path: str, **params) -> dict:
    import urllib.request
    import urllib.parse
    url = f"{_base_url(port)}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(
            {k: v for k, v in params.items() if v is not None})
    req = urllib.request.Request(url, method="POST", data=b"")
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = json.loads(e.read().decode())
        sys.exit(f"error: {body.get('detail', body)}")
    except urllib.error.URLError as e:
        sys.exit(f"error: cannot connect to runtime on port {port}: {e}")


def _delete(port: int, path: str, **params) -> dict:
    import urllib.request
    import urllib.parse
    url = f"{_base_url(port)}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(
            {k: v for k, v in params.items() if v is not None})
    req = urllib.request.Request(url, method="DELETE")
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = json.loads(e.read().decode())
        sys.exit(f"error: {body.get('detail', body)}")
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
    import urllib.request
    url = f"{_base_url(port)}/observe/{coglet_id}/{channel}"
    try:
        with urllib.request.urlopen(url) as resp:
            for raw_line in resp:
                line = raw_line.decode().strip()
                if line.startswith("data: "):
                    print(line[6:])
                    if not follow:
                        return
    except KeyboardInterrupt:
        pass
    except urllib.error.URLError as e:
        sys.exit(f"error: cannot connect to runtime on port {port}: {e}")


# ---------------------------------------------------------------------------
# One-shot run
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
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    port_args = argparse.ArgumentParser(add_help=False)
    port_args.add_argument("--port", type=int, default=DEFAULT_PORT,
                           help=f"runtime API port (default: {DEFAULT_PORT})")

    parser = argparse.ArgumentParser(prog="coglet", description="Manage coglet runtimes.")
    sub = parser.add_subparsers(dest="command")

    # runtime start|stop|status
    rt = sub.add_parser("runtime", help="manage the runtime daemon")
    rt_sub = rt.add_subparsers(dest="action")
    rt_start = rt_sub.add_parser("start", parents=[port_args])
    rt_start.add_argument("--trace", type=str, default=None)
    rt_start.add_argument("--foreground", action="store_true",
                          help="run in foreground (default: daemon mode)")
    rt_sub.add_parser("stop", parents=[port_args])
    rt_sub.add_parser("status", parents=[port_args])

    # create
    cr = sub.add_parser("create", parents=[port_args])
    cr.add_argument("cog_dir", type=Path)

    # stop
    st = sub.add_parser("stop", parents=[port_args])
    st.add_argument("id", type=str)

    # transmit cog:channel DATA
    tr = sub.add_parser("transmit", parents=[port_args],
                        help="push data onto a coglet's channel")
    tr.add_argument("target", type=str, help="id:channel")
    tr.add_argument("data", nargs="?", default=None, help="data (JSON or string)")

    # observe cog:channel
    ob = sub.add_parser("observe", parents=[port_args],
                        help="subscribe to a coglet's channel output")
    ob.add_argument("target", type=str, help="id:channel")
    ob.add_argument("--follow", action="store_true")

    # enact cog command [DATA]
    en = sub.add_parser("enact", parents=[port_args],
                        help="send a command to a coglet's @enact handlers")
    en.add_argument("id", type=str, help="coglet id")
    en.add_argument("cmd_type", metavar="command", type=str)
    en.add_argument("data", nargs="?", default=None, help="data (JSON or string)")

    # link src_id:channel dest_id:channel
    ln = sub.add_parser("link", parents=[port_args],
                        help="wire src:channel -> dest:channel")
    ln.add_argument("src", type=str, help="source (id:channel)")
    ln.add_argument("dest", type=str, nargs="?", default=None,
                    help="destination (id:channel). Omit to list channels.")

    # unlink
    ul = sub.add_parser("unlink", parents=[port_args])
    ul.add_argument("src", type=str, help="source (id:channel)")
    ul.add_argument("dest", type=str, help="destination (id:channel)")

    # links
    sub.add_parser("links", parents=[port_args], help="list active links")

    # shell
    sub.add_parser("shell", parents=[port_args],
                   help="interactive shell with tab-completion")

    # run (one-shot)
    rn = sub.add_parser("run")
    rn.add_argument("cog_dir", type=Path)
    rn.add_argument("--trace", type=str, default=None)

    args = parser.parse_args()
    port = getattr(args, "port", DEFAULT_PORT)

    if args.command == "runtime":
        if args.action == "start":
            start_server(port, trace_path=args.trace, foreground=args.foreground)
        elif args.action == "stop":
            print(_post(port, "/shutdown").get("msg"))
        elif args.action == "status":
            resp = _get(port, "/status")
            print(resp["tree"])
            if resp["coglets"]:
                print()
                for c in resp["coglets"]:
                    chs = ", ".join(c.get("channels", []))
                    print(f"  {c['id']}  {c['class']}  children={c['children']}  channels=[{chs}]")
            if resp.get("links"):
                print()
                for lk in resp["links"]:
                    print(f"  {lk['src']}:{lk['src_channel']} -> {lk['dest']}:{lk['dest_channel']}")
            if not resp["coglets"]:
                print("\nno coglets running.")

    elif args.command == "create":
        if not args.cog_dir.is_dir():
            sys.exit(f"error: '{args.cog_dir}' is not a directory")
        resp = _post(port, "/create", cog_dir=str(args.cog_dir.resolve()))
        print(resp["id"])

    elif args.command == "stop":
        print(_post(port, f"/stop/{args.id}").get("msg"))

    elif args.command == "transmit":
        cid, ch = _parse_channel_ref(args.target)
        data_val = _parse_data(args.data)
        params = {}
        if data_val is not None:
            params["data"] = json.dumps(data_val) if not isinstance(data_val, str) else data_val
        print(_post(port, f"/transmit/{cid}/{ch}", **params).get("msg"))

    elif args.command == "observe":
        cid, ch = _parse_channel_ref(args.target)
        _observe_sse(port, cid, ch, args.follow)

    elif args.command == "enact":
        data_val = _parse_data(args.data)
        params = {"command": args.cmd_type}
        if data_val is not None:
            params["data"] = json.dumps(data_val) if not isinstance(data_val, str) else data_val
        print(_post(port, f"/enact/{args.id}", **params).get("msg"))

    elif args.command == "link":
        if args.dest is None:
            # No dest — list channels for the coglet
            coglet_id = args.src
            resp = _get(port, f"/channels/{coglet_id}")
            print(f"{resp['id']} ({resp['class']})")
            if resp["transmit"]:
                print(f"  transmit: {', '.join(resp['transmit'])}")
            if resp["listen"]:
                print(f"  listen:   {', '.join(resp['listen'])}")
            if not resp["transmit"] and not resp["listen"]:
                print("  (no channels)")
        else:
            src_id, src_ch = _parse_channel_ref(args.src)
            dest_id, dest_ch = _parse_channel_ref(args.dest)
            resp = _post(port, "/link",
                         src_id=src_id, src_channel=src_ch,
                         dest_id=dest_id, dest_channel=dest_ch)
            print(resp.get("msg"))

    elif args.command == "unlink":
        src_id, src_ch = _parse_channel_ref(args.src)
        dest_id, dest_ch = _parse_channel_ref(args.dest)
        resp = _delete(port, "/link",
                       src_id=src_id, src_channel=src_ch,
                       dest_id=dest_id, dest_channel=dest_ch)
        print(resp.get("msg"))

    elif args.command == "links":
        resp = _get(port, "/links")
        for lk in resp["links"]:
            print(f"  {lk['src']}:{lk['src_channel']} -> {lk['dest']}:{lk['dest_channel']}")
        if not resp["links"]:
            print("no links.")

    elif args.command == "shell":
        from coglet.shell import run_shell
        run_shell(port)

    elif args.command == "run":
        if not args.cog_dir.is_dir():
            sys.exit(f"error: '{args.cog_dir}' is not a directory")
        asyncio.run(run_oneshot(args.cog_dir, trace_path=args.trace))

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
