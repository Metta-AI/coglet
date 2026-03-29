"""Unit tests for coglet.trace: CogletTrace event recording."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from coglet.trace import CogletTrace


def test_trace_record_and_load():
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
        path = f.name
    try:
        trace = CogletTrace(path)
        trace.record("TestCoglet", "transmit", "ch1", {"key": "value"})
        trace.record("TestCoglet", "enact", "cmd1", "data")
        trace.close()

        entries = CogletTrace.load(path)
        assert len(entries) == 2
        assert entries[0]["coglet"] == "TestCoglet"
        assert entries[0]["op"] == "transmit"
        assert entries[0]["target"] == "ch1"
        assert entries[0]["data"] == {"key": "value"}
        assert entries[1]["op"] == "enact"
    finally:
        Path(path).unlink(missing_ok=True)


def test_trace_timestamps():
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
        path = f.name
    try:
        trace = CogletTrace(path)
        trace.record("A", "transmit", "ch", 1)
        trace.record("A", "transmit", "ch", 2)
        trace.close()

        entries = CogletTrace.load(path)
        assert entries[0]["t"] <= entries[1]["t"]
        assert entries[0]["t"] >= 0
    finally:
        Path(path).unlink(missing_ok=True)


def test_trace_unserializable_data():
    """Non-JSON-serializable data is repr'd instead of crashing."""
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
        path = f.name
    try:
        trace = CogletTrace(path)
        trace.record("A", "transmit", "ch", object())
        trace.close()

        entries = CogletTrace.load(path)
        assert len(entries) == 1
        assert isinstance(entries[0]["data"], str)
    finally:
        Path(path).unlink(missing_ok=True)


def test_trace_load_empty():
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
        path = f.name
    try:
        trace = CogletTrace(path)
        trace.close()
        entries = CogletTrace.load(path)
        assert entries == []
    finally:
        Path(path).unlink(missing_ok=True)
