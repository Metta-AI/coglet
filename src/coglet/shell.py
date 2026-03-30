"""coglet shell — interactive REPL for a running coglet runtime.

Usage:
    coglet shell [--port PORT]

Provides tab-completion for coglet IDs, channel names, and commands.
"""

from __future__ import annotations

import cmd
import json
import os
import readline
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


class CogletShell(cmd.Cmd):
    intro = "coglet shell. Type help or ? for commands.\n"
    prompt = "coglet> "

    def __init__(self, port: int):
        super().__init__()
        self.port = port
        self._cache_ids: list[str] = []
        self._cache_channels: dict[str, dict] = {}  # id -> {transmit, listen}
        self._observe_thread: threading.Thread | None = None
        # Remove ':' from readline delimiters so id:channel completes as one token
        delims = readline.get_completer_delims()
        readline.set_completer_delims(delims.replace(":", ""))

    # --- HTTP helpers ---

    def _url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def _get(self, path: str) -> dict | None:
        try:
            with urllib.request.urlopen(self._url(path)) as resp:
                return json.loads(resp.read().decode())
        except (urllib.error.URLError, urllib.error.HTTPError) as e:
            print(f"  error: {e}")
            return None

    def _post(self, path: str, **params) -> dict | None:
        url = self._url(path)
        if params:
            url += "?" + urllib.parse.urlencode(
                {k: v for k, v in params.items() if v is not None})
        req = urllib.request.Request(url, method="POST", data=b"")
        try:
            with urllib.request.urlopen(req) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            body = json.loads(e.read().decode())
            print(f"  error: {body.get('detail', body)}")
            return None
        except urllib.error.URLError as e:
            print(f"  error: {e}")
            return None

    def _delete(self, path: str, **params) -> dict | None:
        url = self._url(path)
        if params:
            url += "?" + urllib.parse.urlencode(
                {k: v for k, v in params.items() if v is not None})
        req = urllib.request.Request(url, method="DELETE")
        try:
            with urllib.request.urlopen(req) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            body = json.loads(e.read().decode())
            print(f"  error: {body.get('detail', body)}")
            return None
        except urllib.error.URLError as e:
            print(f"  error: {e}")
            return None

    # --- Cache refresh ---

    def _refresh_ids(self) -> list[str]:
        resp = self._get("/status")
        if resp:
            self._cache_ids = [c["id"] for c in resp.get("coglets", [])]
            self._cache_channels.clear()
        return self._cache_ids

    def _get_channels(self, cid: str) -> dict:
        if cid not in self._cache_channels:
            resp = self._get(f"/channels/{cid}")
            if resp:
                self._cache_channels[cid] = resp
        return self._cache_channels.get(cid, {})

    def _id_completions(self, text: str) -> list[str]:
        if not self._cache_ids:
            self._refresh_ids()
        return [i for i in self._cache_ids if i.startswith(text)]

    def _channel_ref_completions(self, text: str) -> list[str]:
        """Complete id:channel refs."""
        if not self._cache_ids:
            self._refresh_ids()
        if ":" in text:
            cid, partial = text.split(":", 1)
            ch = self._get_channels(cid)
            all_chs = sorted(set(ch.get("transmit", []) + ch.get("listen", [])))
            return [f"{cid}:{c}" for c in all_chs if c.startswith(partial)]
        else:
            # Complete the id part, append ":"
            return [f"{i}:" for i in self._cache_ids if i.startswith(text)]

    # --- Commands ---

    def do_status(self, _arg):
        """Show runtime status: tree, coglets, links."""
        resp = self._get("/status")
        if not resp:
            return
        print(resp["tree"])
        if resp["coglets"]:
            print()
            for c in resp["coglets"]:
                chs = ", ".join(c.get("channels", []))
                print(f"  {c['id']}  {c['class']}  children={c['children']}  [{chs}]")
        if resp.get("links"):
            print()
            for lk in resp["links"]:
                print(f"  {lk['src']}:{lk['src_channel']} -> {lk['dest']}:{lk['dest_channel']}")
        self._cache_ids = [c["id"] for c in resp.get("coglets", [])]

    def do_coglets(self, _arg):
        """List all coglets (short form of status)."""
        resp = self._get("/status")
        if not resp:
            return
        for c in resp.get("coglets", []):
            chs = ", ".join(c.get("channels", []))
            print(f"  {c['id']}  {c['class']}  [{chs}]")
        self._cache_ids = [c["id"] for c in resp.get("coglets", [])]

    def do_tree(self, _arg):
        """Show ASCII tree."""
        resp = self._get("/tree")
        if resp:
            print(resp["tree"])

    # --- Filesystem commands ---

    def do_ls(self, arg):
        """List files in current (or given) directory."""
        target = Path(arg).expanduser() if arg else Path.cwd()
        if not target.is_absolute():
            target = Path.cwd() / target
        try:
            entries = sorted(target.iterdir())
        except (OSError, PermissionError) as e:
            print(f"  error: {e}")
            return
        for entry in entries:
            suffix = "/" if entry.is_dir() else ""
            print(f"  {entry.name}{suffix}")

    def complete_ls(self, text, line, begidx, endidx):
        return self._path_completions(text)

    def do_cd(self, arg):
        """Change working directory."""
        target = Path(arg).expanduser() if arg else Path.home()
        if not target.is_absolute():
            target = Path.cwd() / target
        target = target.resolve()
        try:
            os.chdir(target)
            self.prompt = f"coglet {target.name}> "
        except (OSError, PermissionError) as e:
            print(f"  error: {e}")

    def complete_cd(self, text, line, begidx, endidx):
        return [p for p in self._path_completions(text) if p.endswith("/")]

    def do_pwd(self, _arg):
        """Print working directory."""
        print(f"  {Path.cwd()}")

    def _path_completions(self, text: str) -> list[str]:
        """Complete filesystem paths."""
        p = Path(text).expanduser() if text else Path(".")
        if text and not text.endswith("/"):
            parent = p.parent
            prefix = p.name
        else:
            parent = p
            prefix = ""
        if not parent.is_absolute():
            parent = Path.cwd() / parent
        try:
            entries = list(parent.iterdir())
        except (OSError, PermissionError):
            return []
        matches = []
        for entry in entries:
            if entry.name.startswith(prefix):
                rel = text[:text.rfind("/") + 1] if "/" in text else ""
                suffix = "/" if entry.is_dir() else " "
                matches.append(f"{rel}{entry.name}{suffix}")
        return matches

    def do_create(self, arg):
        """Create a coglet: create PATH.cog"""
        if not arg:
            print("  usage: create PATH.cog")
            return
        from pathlib import Path
        path = Path(arg).resolve()
        resp = self._post("/create", cog_dir=str(path))
        if resp:
            print(f"  {resp['id']}  ({resp['class']})")
            self._cache_ids.append(resp["id"])

    def do_stop(self, arg):
        """Stop a coglet: stop ID"""
        if not arg:
            print("  usage: stop ID")
            return
        resp = self._post(f"/stop/{arg}")
        if resp:
            print(f"  {resp['msg']}")
            if arg in self._cache_ids:
                self._cache_ids.remove(arg)

    def complete_stop(self, text, line, begidx, endidx):
        return self._id_completions(text)

    def do_describe(self, arg):
        """Describe a coglet's channels and stats: describe ID"""
        if not arg:
            print("  usage: describe ID")
            return
        ch = self._get(f"/channels/{arg}")
        if not ch:
            return
        print(f"  {ch['id']} ({ch['class']})")
        if ch.get("transmit"):
            print(f"  transmit: {', '.join(ch['transmit'])}")
        if ch.get("listen"):
            print(f"  listen:   {', '.join(ch['listen'])}")

        stats = self._get(f"/stats/{arg}")
        if stats and stats.get("channels"):
            print()
            for ch_name, counts in stats["channels"].items():
                parts = [f"{k}={v}" for k, v in counts.items() if v > 0]
                if parts:
                    print(f"  {ch_name}: {', '.join(parts)}")

    def complete_describe(self, text, line, begidx, endidx):
        return self._id_completions(text)

    def do_stats(self, arg):
        """Show channel stats: stats ID[:CHANNEL]"""
        if not arg:
            print("  usage: stats ID or stats ID:CHANNEL")
            return
        if ":" in arg:
            cid, ch = arg.split(":", 1)
            resp = self._get(f"/stats/{cid}?channel={ch}")
            if not resp:
                return
            print(f"  {cid}:{ch}")
            for k, v in resp.get("counts", {}).items():
                print(f"    {k}: {v}")
            hist = resp.get("history", [])
            if hist:
                print(f"  last {len(hist)} messages:")
                for m in hist:
                    print(f"    {json.dumps(m)}")
        else:
            resp = self._get(f"/stats/{arg}")
            if not resp:
                return
            for ch_name, counts in resp.get("channels", {}).items():
                parts = " ".join(f"{k}={v}" for k, v in counts.items())
                print(f"  {ch_name}: {parts}")

    def complete_stats(self, text, line, begidx, endidx):
        return self._channel_ref_completions(text)

    def do_history(self, arg):
        """Show recent messages: history ID:CHANNEL [N]"""
        parts = arg.split()
        if not parts:
            print("  usage: history ID:CHANNEL [N]")
            return
        ref = parts[0]
        n = int(parts[1]) if len(parts) > 1 else 10
        if ":" not in ref:
            print("  usage: history ID:CHANNEL [N]")
            return
        cid, ch = ref.split(":", 1)
        resp = self._get(f"/history/{cid}/{ch}?n={n}")
        if not resp:
            return
        for m in resp.get("messages", []):
            print(f"  {json.dumps(m)}")
        if not resp.get("messages"):
            print("  (no messages)")

    def complete_history(self, text, line, begidx, endidx):
        return self._channel_ref_completions(text)

    def do_transmit(self, arg):
        """Transmit data: transmit ID:CHANNEL DATA"""
        parts = arg.split(None, 1)
        if len(parts) < 1:
            print("  usage: transmit ID:CHANNEL [DATA]")
            return
        ref = parts[0]
        data = parts[1] if len(parts) > 1 else None
        if ":" not in ref:
            print("  usage: transmit ID:CHANNEL [DATA]")
            return
        cid, ch = ref.split(":", 1)
        params = {}
        if data:
            try:
                params["data"] = json.dumps(json.loads(data))
            except json.JSONDecodeError:
                params["data"] = data
        resp = self._post(f"/transmit/{cid}/{ch}", **params)
        if resp:
            print(f"  {resp['msg']}")

    def complete_transmit(self, text, line, begidx, endidx):
        return self._channel_ref_completions(text)

    def do_enact(self, arg):
        """Send command: enact ID COMMAND [DATA]"""
        parts = arg.split(None, 2)
        if len(parts) < 2:
            print("  usage: enact ID COMMAND [DATA]")
            return
        cid = parts[0]
        command = parts[1]
        data = parts[2] if len(parts) > 2 else None
        params = {"command": command}
        if data:
            try:
                params["data"] = json.dumps(json.loads(data))
            except json.JSONDecodeError:
                params["data"] = data
        resp = self._post(f"/enact/{cid}", **params)
        if resp:
            print(f"  {resp['msg']}")

    def complete_enact(self, text, line, begidx, endidx):
        return self._id_completions(text)

    def do_observe(self, arg):
        """Observe channel (streams until ctrl-c): observe ID:CHANNEL"""
        if not arg or ":" not in arg:
            print("  usage: observe ID:CHANNEL")
            return
        cid, ch = arg.split(":", 1)
        url = self._url(f"/observe/{cid}/{ch}")
        print(f"  observing {cid}:{ch} (ctrl-c to stop)...")

        def _stream():
            try:
                with urllib.request.urlopen(url) as resp:
                    for raw in resp:
                        line = raw.decode().strip()
                        if line.startswith("data: "):
                            print(f"  << {line[6:]}")
            except Exception:
                pass

        self._observe_thread = threading.Thread(target=_stream, daemon=True)
        self._observe_thread.start()
        try:
            self._observe_thread.join()
        except KeyboardInterrupt:
            print("\n  stopped observing.")

    def complete_observe(self, text, line, begidx, endidx):
        return self._channel_ref_completions(text)

    def do_link(self, arg):
        """Link channels: link SRC:CH DEST:CH  (or: link ID to list channels)"""
        parts = arg.split()
        if len(parts) == 1:
            # List channels
            resp = self._get(f"/channels/{parts[0]}")
            if not resp:
                return
            print(f"  {resp['id']} ({resp['class']})")
            if resp.get("transmit"):
                print(f"  transmit: {', '.join(resp['transmit'])}")
            if resp.get("listen"):
                print(f"  listen:   {', '.join(resp['listen'])}")
        elif len(parts) == 2:
            src, dest = parts
            if ":" not in src or ":" not in dest:
                print("  usage: link SRC:CH DEST:CH")
                return
            src_id, src_ch = src.split(":", 1)
            dest_id, dest_ch = dest.split(":", 1)
            resp = self._post("/link", src_id=src_id, src_channel=src_ch,
                              dest_id=dest_id, dest_channel=dest_ch)
            if resp:
                print(f"  {resp['msg']}")
        else:
            print("  usage: link ID  or  link SRC:CH DEST:CH")

    def complete_link(self, text, line, begidx, endidx):
        parts = line.split()
        if len(parts) <= 2:
            return self._channel_ref_completions(text)
        return self._channel_ref_completions(text)

    def do_unlink(self, arg):
        """Unlink channels: unlink SRC:CH DEST:CH"""
        parts = arg.split()
        if len(parts) != 2:
            print("  usage: unlink SRC:CH DEST:CH")
            return
        src, dest = parts
        if ":" not in src or ":" not in dest:
            print("  usage: unlink SRC:CH DEST:CH")
            return
        src_id, src_ch = src.split(":", 1)
        dest_id, dest_ch = dest.split(":", 1)
        resp = self._delete("/link", src_id=src_id, src_channel=src_ch,
                            dest_id=dest_id, dest_channel=dest_ch)
        if resp:
            print(f"  {resp['msg']}")

    def complete_unlink(self, text, line, begidx, endidx):
        return self._channel_ref_completions(text)

    def do_links(self, _arg):
        """List all active links."""
        resp = self._get("/links")
        if not resp:
            return
        for lk in resp.get("links", []):
            print(f"  {lk['src']}:{lk['src_channel']} -> {lk['dest']}:{lk['dest_channel']}")
        if not resp.get("links"):
            print("  no links.")

    def do_quit(self, _arg):
        """Exit the shell."""
        return True

    do_exit = do_quit
    do_EOF = do_quit

    def emptyline(self):
        pass

    def default(self, line):
        print(f"  unknown command: {line}. Type help for commands.")


def run_shell(port: int) -> None:
    """Start the interactive coglet shell."""
    # Verify runtime is reachable
    try:
        url = f"http://127.0.0.1:{port}/status"
        urllib.request.urlopen(url)
    except urllib.error.URLError:
        sys.exit(f"error: cannot connect to runtime on port {port}")

    shell = CogletShell(port)
    try:
        shell.cmdloop()
    except KeyboardInterrupt:
        print()
