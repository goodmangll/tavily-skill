#!/usr/bin/env python3
"""Tavily CLI for web search, extraction, mapping, crawling, and research.

Single-file and stdlib-only. By default, responses are written to the XDG data
directory and a compact status JSON is printed to stdout. Use --stdout to print
the full payload inline or --output to write to a specific path.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Iterable

# ---------------------------------------------------------------------------
# Paths and constants
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent


def _xdg_home(variable: str, fallback: str) -> Path:
    """Return an XDG home directory, using its standard home-directory fallback."""
    return Path(os.environ.get(variable, fallback)).expanduser()


CONFIG_FILE = _xdg_home("XDG_CONFIG_HOME", "~/.config") / "tavily" / "config.yaml"
DEFAULT_STATE_FILE = _xdg_home("XDG_STATE_HOME", "~/.local/state") / "tavily" / "state.json"
DEFAULT_OUTPUT_DIR = _xdg_home("XDG_DATA_HOME", "~/.local/share") / "tavily" / "results"

API_BASE = "https://api.tavily.com"
ENDPOINTS = {
    "search": "/search",
    "extract": "/extract",
    "map": "/map",
    "crawl": "/crawl",
    "research": "/research",
}

DEFAULT_TIMEOUT = 60
LONG_TIMEOUT = 150  # map / crawl can be slow

RESEARCH_POLL_INTERVAL = 3
RESEARCH_POLL_MAX = 180  # 3 minutes

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def _config_file() -> Path:
    return _xdg_home("XDG_CONFIG_HOME", "~/.config") / "tavily" / "config.yaml"


def load_config() -> dict[str, Any]:
    """Load Tavily's small YAML configuration file without external packages."""
    path = _config_file()
    if not path.exists():
        raise RuntimeError(f"Configuration file not found: {path}")

    config: dict[str, Any] = {}
    active_list: str | None = None
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if line.startswith((" ", "\t")):
            if active_list and line.strip().startswith("- "):
                config.setdefault(active_list, []).append(line.strip()[2:].strip().strip('"\''))
                continue
            raise RuntimeError(f"Invalid configuration at {path}:{number}")
        key, separator, value = line.partition(":")
        if not separator or not key.strip():
            raise RuntimeError(f"Invalid configuration at {path}:{number}")
        active_list = key.strip()
        value = value.strip().strip('"\'')
        config[active_list] = [] if not value else value
    return config


def _state_file() -> Path:
    return _xdg_home("XDG_STATE_HOME", "~/.local/state") / "tavily" / "state.json"


def _output_dir() -> Path:
    configured = load_config().get("output_dir")
    return Path(str(configured)).expanduser() if configured else _xdg_home(
        "XDG_DATA_HOME", "~/.local/share"
    ) / "tavily" / "results"


# ---------------------------------------------------------------------------
# API keys and quota handling
# ---------------------------------------------------------------------------

def fingerprint(key: str) -> str:
    """Stable hash of a key so state.json never stores the raw key."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


def load_keys() -> list[str]:
    configured = load_config().get("api_keys", [])
    keys = [str(key).strip() for key in configured] if isinstance(configured, list) else []
    keys = [key for key in keys if key]
    if not keys:
        raise RuntimeError(
            f"No API keys configured. Add api_keys to {_config_file()}."
        )
    return keys


def load_state() -> dict[str, Any]:
    path = _state_file()
    if not path.exists():
        return {"disabled": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or "disabled" not in data:
            return {"disabled": []}
        return data
    except (ValueError, OSError):
        return {"disabled": []}


def save_state(state: dict[str, Any]) -> None:
    path = _state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(state, ensure_ascii=False, indent=2)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)  # atomic


def pick_available_key(keys: list[str], state: dict) -> tuple[str | None, str | None]:
    """First key (in configured order) whose fingerprint is not disabled."""
    disabled = {d["fingerprint"] for d in state.get("disabled", [])}
    for key in keys:
        fp = fingerprint(key)
        if fp not in disabled:
            return fp, key
    return None, None


def pick_earliest_disabled(keys: list[str], state: dict) -> tuple[str | None, str | None]:
    """Earliest-disabled key fingerprint (for the retry-on-all-exhausted path)."""
    our_fps = {fingerprint(k) for k in keys}
    relevant = [d for d in state.get("disabled", []) if d.get("fingerprint") in our_fps]
    relevant.sort(key=lambda d: d.get("disabled_at", ""))
    if not relevant:
        return None, None
    fp = relevant[0]["fingerprint"]
    for key in keys:
        if fingerprint(key) == fp:
            return fp, key
    return None, None


def re_enable_key(state: dict, fp: str) -> None:
    state["disabled"] = [d for d in state.get("disabled", []) if d.get("fingerprint") != fp]


def disable_key(state: dict, fp: str) -> None:
    # Remove any existing entry then append with a fresh timestamp so this key
    # becomes the newest-disabled (matches proxy's Date.now() update on re-disable).
    state["disabled"] = [d for d in state.get("disabled", []) if d.get("fingerprint") != fp]
    state["disabled"].append({
        "fingerprint": fp,
        "disabled_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "reason": "432 quota exhausted",
    })


def is_quota_exhausted(status: int, body: str) -> bool:
    if status == 432:
        return True
    # Some Tavily responses embed the 432 in the JSON body.
    try:
        data = json.loads(body)
    except (ValueError, TypeError):
        return False
    if isinstance(data, dict):
        candidates = (
            data.get("status"),
            (data.get("error") or {}).get("status") if isinstance(data.get("error"), dict) else None,
            (data.get("error") or {}).get("code") if isinstance(data.get("error"), dict) else None,
        )
        if 432 in candidates:
            return True
    return False


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def http_request(
    method: str,
    url: str,
    api_key: str,
    payload: dict | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> tuple[int, str]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as e:
        raise RuntimeError(f"network error: {e.reason}") from e
    except socket.timeout:
        raise RuntimeError(f"request timed out after {timeout}s") from None


def call_api(
    method: str,
    endpoint_key: str,
    payload: dict | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> tuple[int, str]:
    """Make a Tavily API call, trying available configured keys after HTTP 432."""
    keys = load_keys()
    state = load_state()
    url = API_BASE + ENDPOINTS[endpoint_key]
    max_attempts = max(len(keys) * 2, 1)
    last_error = "no attempts made"

    for _ in range(max_attempts):
        fp, key = pick_available_key(keys, state)
        if key is None:
            # All disabled — retry the earliest-disabled once.
            fp, key = pick_earliest_disabled(keys, state)
            if key is None:
                break
            re_enable_key(state, fp)
            save_state(state)

        status, body = http_request(method, url, key, payload, timeout)

        if is_quota_exhausted(status, body):
            disable_key(state, fp)
            save_state(state)
            last_error = f"432 quota exhausted (key fp={fp})"
            continue

        return status, body

    raise RuntimeError(f"All API keys exhausted. Last: {last_error}")


# ---------------------------------------------------------------------------
# Output (file vs stdout, compact status JSON)
# ---------------------------------------------------------------------------

def _slugify(value: str, max_length: int = 48) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", value).strip("_").lower()
    return (slug[:max_length].rstrip("_") or "payload")


def _default_output_path(command: str, seed: str) -> Path:
    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = _slugify(seed)
    return _output_dir() / f"{command}_{timestamp}_{slug}.json"


def emit_payload(payload: dict[str, Any], stdout_mode: bool, output_path: str | None) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2)

    if stdout_mode and not output_path:
        print(text)
        return

    target = Path(output_path).expanduser() if output_path else _default_output_path(
        payload.get("command", "payload"),
        _seed_for(payload),
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")

    data = payload.get("data", {}) if isinstance(payload.get("data"), dict) else {}
    summary = {
        "result_count": data.get("result_count"),
        "failed_count": data.get("failed_count"),
        "image_count": data.get("image_count"),
        "has_answer": bool(data.get("answer")),
    }
    status = {
        "command": payload.get("command"),
        "status": "ok",
        "output_mode": "file",
        "output_path": str(target),
        "payload_bytes": len(text.encode("utf-8")),
        "summary": summary,
    }
    print(json.dumps(status, ensure_ascii=False, indent=2))
    print(f"Saved JSON to {target}", file=sys.stderr)


def _seed_for(payload: dict[str, Any]) -> str:
    cmd = payload.get("command")
    inp = payload.get("input") if isinstance(payload.get("input"), dict) else {}
    if cmd == "search":
        return str(inp.get("query") or "search")
    if cmd == "extract":
        urls = inp.get("urls") or []
        return urls[0] if urls else "extract"
    if cmd in ("map", "crawl"):
        return str(inp.get("url") or cmd)
    if cmd == "research":
        return str(inp.get("input") or "research")
    return str(cmd or "payload")


# ---------------------------------------------------------------------------
# Envelope builders
# ---------------------------------------------------------------------------

def envelope(command: str, input_data: dict, data: dict) -> dict[str, Any]:
    return {"command": command, "input": input_data, "data": data}


def parse_body(body: str) -> dict:
    try:
        parsed = json.loads(body)
        return parsed if isinstance(parsed, dict) else {"raw": parsed}
    except (ValueError, TypeError):
        return {"raw": body}


def build_search_payload(args: argparse.Namespace, status: int, body: str) -> dict[str, Any]:
    data_raw = parse_body(body)
    results = data_raw.get("results") or []
    images = data_raw.get("images") or []
    data = {
        "query": data_raw.get("query", args.query),
        "answer": data_raw.get("answer"),
        "results": results,
        "images": images,
        "response_time": data_raw.get("response_time"),
        "request_id": data_raw.get("request_id"),
        "usage": data_raw.get("usage"),
        "result_count": len(results),
        "image_count": len(images),
    }
    if status >= 400:
        data["error"] = data_raw.get("detail") or data_raw.get("error") or body
        data["http_status"] = status
    input_data = {
        "query": args.query,
        "max_results": args.max_results,
        "search_depth": args.search_depth,
        "topic": args.topic,
        "chunks_per_source": args.chunks_per_source,
        "time_range": args.time_range,
        "include_domains": args.include_domain,
        "exclude_domains": args.exclude_domain,
        "country": args.country,
    }
    return envelope("search", input_data, data)


def build_extract_payload(args: argparse.Namespace, status: int, body: str) -> dict[str, Any]:
    data_raw = parse_body(body)
    results = data_raw.get("results") or []
    failed = data_raw.get("failed_results") or []
    image_count = 0
    for r in results:
        if isinstance(r, dict) and isinstance(r.get("images"), list):
            image_count += len(r["images"])
    data = {
        "results": results,
        "failed_results": failed,
        "usage": data_raw.get("usage"),
        "result_count": len(results),
        "failed_count": len(failed),
        "image_count": image_count,
    }
    if status >= 400:
        data["error"] = data_raw.get("detail") or data_raw.get("error") or body
        data["http_status"] = status
    input_data = {
        "urls": args.urls,
        "extract_depth": args.extract_depth,
        "query": args.query,
        "chunks_per_source": args.chunks_per_source,
    }
    return envelope("extract", input_data, data)


def build_map_payload(args: argparse.Namespace, status: int, body: str) -> dict[str, Any]:
    data_raw = parse_body(body)
    results = data_raw.get("results") or []
    data = {
        "results": results,
        "response_time": data_raw.get("response_time"),
        "usage": data_raw.get("usage"),
        "result_count": len(results) if isinstance(results, list) else 0,
    }
    if status >= 400:
        data["error"] = data_raw.get("detail") or data_raw.get("error") or body
        data["http_status"] = status
    input_data = {
        "url": args.url,
        "instructions": args.instructions,
        "max_depth": args.max_depth,
        "max_breadth": args.max_breadth,
        "limit": args.limit,
    }
    return envelope("map", input_data, data)


def build_crawl_payload(args: argparse.Namespace, status: int, body: str) -> dict[str, Any]:
    data_raw = parse_body(body)
    results = data_raw.get("results") or []
    data = {
        "results": results,
        "response_time": data_raw.get("response_time"),
        "usage": data_raw.get("usage"),
        "result_count": len(results) if isinstance(results, list) else 0,
    }
    if status >= 400:
        data["error"] = data_raw.get("detail") or data_raw.get("error") or body
        data["http_status"] = status
    input_data = {
        "url": args.url,
        "instructions": args.instructions,
        "chunks_per_source": args.chunks_per_source,
        "max_depth": args.max_depth,
        "max_breadth": args.max_breadth,
        "limit": args.limit,
        "extract_depth": args.extract_depth,
    }
    return envelope("crawl", input_data, data)


def build_research_create_payload(args: argparse.Namespace, status: int, body: str) -> dict[str, Any]:
    data_raw = parse_body(body)
    data = {
        "request_id": data_raw.get("request_id"),
        "status": data_raw.get("status", "submitted"),
    }
    if status >= 400:
        data["error"] = data_raw.get("detail") or data_raw.get("error") or body
        data["http_status"] = status
    input_data = {
        "input": args.input,
        "model": args.model,
        "output_length": args.output_length,
        "citation_format": args.citation_format,
    }
    return envelope("research", input_data, data)


def build_research_result_payload(request_id: str, status: int, body: str) -> dict[str, Any]:
    data_raw = parse_body(body)
    data = {
        "request_id": request_id,
        "status": data_raw.get("status", "unknown"),
        "content": data_raw.get("content"),
        "sources": data_raw.get("sources", []),
    }
    if status >= 400:
        data["error"] = data_raw.get("detail") or data_raw.get("error") or body
        data["http_status"] = status
    return envelope("research", {"request_id": request_id}, data)


# ---------------------------------------------------------------------------
# Request builders
# ---------------------------------------------------------------------------

def run_search(args: argparse.Namespace) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "query": args.query,
        "search_depth": args.search_depth,
        "max_results": args.max_results,
        "topic": args.topic,
    }
    if args.search_depth in ("advanced", "fast"):
        payload["chunks_per_source"] = args.chunks_per_source
    if args.time_range:
        payload["time_range"] = args.time_range
    if args.include_domain:
        payload["include_domains"] = args.include_domain
    if args.exclude_domain:
        payload["exclude_domains"] = args.exclude_domain
    if args.country:
        payload["country"] = args.country
    status, body = call_api("POST", "search", payload, timeout=DEFAULT_TIMEOUT)
    return build_search_payload(args, status, body)


def run_extract(args: argparse.Namespace) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "urls": args.urls,
        "extract_depth": args.extract_depth,
    }
    if args.query:
        payload["query"] = args.query
        payload["chunks_per_source"] = args.chunks_per_source if args.chunks_per_source is not None else 3
    status, body = call_api("POST", "extract", payload, timeout=DEFAULT_TIMEOUT)
    return build_extract_payload(args, status, body)


def run_map(args: argparse.Namespace) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "url": args.url,
        "max_depth": args.max_depth,
        "max_breadth": args.max_breadth,
        "limit": args.limit,
    }
    if args.instructions:
        payload["instructions"] = args.instructions
    status, body = call_api("POST", "map", payload, timeout=LONG_TIMEOUT)
    return build_map_payload(args, status, body)


def run_crawl(args: argparse.Namespace) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "url": args.url,
        "max_depth": args.max_depth,
        "max_breadth": args.max_breadth,
        "limit": args.limit,
        "extract_depth": args.extract_depth,
    }
    if args.instructions:
        payload["instructions"] = args.instructions
        payload["chunks_per_source"] = args.chunks_per_source
    status, body = call_api("POST", "crawl", payload, timeout=LONG_TIMEOUT)
    return build_crawl_payload(args, status, body)


def run_research_create(args: argparse.Namespace) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "input": args.input,
        "model": args.model,
        "output_length": args.output_length,
        "citation_format": args.citation_format,
    }
    status, body = call_api("POST", "research", payload, timeout=DEFAULT_TIMEOUT)
    create_payload = build_research_create_payload(args, status, body)

    if status >= 400 or not args.wait:
        # On error or no-wait: print the create response inline (it's tiny).
        print(json.dumps(create_payload, ensure_ascii=False, indent=2))
        return None  # signal: already emitted

    request_id = create_payload["data"].get("request_id")
    if not request_id:
        print(json.dumps(create_payload, ensure_ascii=False, indent=2))
        return None

    print(f"Research task submitted ({request_id}), waiting for completion...", file=sys.stderr)
    elapsed = 0
    while elapsed < RESEARCH_POLL_MAX:
        time.sleep(RESEARCH_POLL_INTERVAL)
        elapsed += RESEARCH_POLL_INTERVAL
        result = _research_fetch(request_id)
        if result is None:
            print(f"  still in progress... ({elapsed}s)", file=sys.stderr)
            continue
        return result
    raise RuntimeError(f"research task {request_id} did not complete within {RESEARCH_POLL_MAX}s")


def _research_fetch(request_id: str) -> dict[str, Any] | None:
    """GET /research/{id}. Returns the result payload when complete, None when still running."""
    url = API_BASE + ENDPOINTS["research"] + "/" + urllib.request.quote(request_id, safe="")
    # research get uses GET; reuse key rotation by calling call_api with a GET helper.
    keys = load_keys()
    state = load_state()
    max_attempts = max(len(keys) * 2, 1)
    last_error = "no attempts made"
    for _ in range(max_attempts):
        fp, key = pick_available_key(keys, state)
        if key is None:
            fp, key = pick_earliest_disabled(keys, state)
            if key is None:
                break
            re_enable_key(state, fp)
            save_state(state)
        status, body = http_request("GET", url, key, payload=None, timeout=DEFAULT_TIMEOUT)
        if status == 202:
            return None  # still running (HTTP 202 Accepted)
        if is_quota_exhausted(status, body):
            disable_key(state, fp)
            save_state(state)
            last_error = f"432 quota exhausted (key fp={fp})"
            continue
        # Some Tavily responses use HTTP 200 with an embedded status field.
        try:
            body_status = json.loads(body).get("status")
        except (ValueError, TypeError):
            body_status = None
        if body_status == "in_progress" or body_status == "pending":
            return None  # still running (HTTP 200 + status field)
        return build_research_result_payload(request_id, status, body)
    raise RuntimeError(f"All API keys exhausted while polling research. Last: {last_error}")


def run_research_get(args: argparse.Namespace) -> dict[str, Any]:
    result = _research_fetch(args.request_id)
    if result is None:
        return envelope("research", {"request_id": args.request_id}, {
            "request_id": args.request_id,
            "status": "in_progress",
        })
    return result


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tavily.py",
        description="Tavily CLI — search, extract, map, crawl, research with multi-key rotation",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # search --------------------------------------------------------------
    s = sub.add_parser("search", help="Web search via Tavily Search API")
    s.add_argument("query", help="Search query")
    s.add_argument("--max-results", type=int, default=5, help="Results 1-20 (default 5)")
    s.add_argument("--search-depth", default="basic",
                   choices=["basic", "advanced", "fast", "ultra-fast"],
                   help="Search depth (default basic)")
    s.add_argument("--topic", default="general", choices=["general", "news", "finance"])
    s.add_argument("--chunks-per-source", type=int, default=3,
                   help="Chunks per source, advanced only (default 3)")
    s.add_argument("--time-range", choices=["day", "week", "month", "year"])
    s.add_argument("--include-domain", action="append", default=[])
    s.add_argument("--exclude-domain", action="append", default=[])
    s.add_argument("--country", help="Boost results by country")
    s.add_argument("--stdout", action="store_true", help="Print full payload to stdout")
    s.add_argument("--output", help="Write full payload to a named file")

    # extract -------------------------------------------------------------
    e = sub.add_parser("extract", help="Extract content from URLs via Tavily Extract API")
    e.add_argument("urls", nargs="+", help="URLs to extract (1-20)")
    e.add_argument("--extract-depth", default="basic", choices=["basic", "advanced"])
    e.add_argument("--query", help="Keep only chunks relevant to this query")
    e.add_argument("--chunks-per-source", type=int, default=None,
                   help="Chunks per source (requires --query), 1-5 (default 3)")
    e.add_argument("--stdout", action="store_true", help="Print full payload to stdout")
    e.add_argument("--output", help="Write full payload to a named file")

    # map -----------------------------------------------------------------
    m = sub.add_parser("map", help="Discover a site's URL structure via Tavily Map API")
    m.add_argument("--url", required=True, help="Starting URL")
    m.add_argument("--instructions", help="Natural-language traversal guidance")
    m.add_argument("--max-depth", type=int, default=1, help="Depth 1-5 (default 1)")
    m.add_argument("--max-breadth", type=int, default=20, help="Links per layer 1-500 (default 20)")
    m.add_argument("--limit", type=int, default=50, help="Total links before stopping (default 50)")
    m.add_argument("--stdout", action="store_true", help="Print full payload to stdout")
    m.add_argument("--output", help="Write full payload to a named file")

    # crawl ---------------------------------------------------------------
    c = sub.add_parser("crawl", help="Crawl a website via Tavily Crawl API")
    c.add_argument("--url", required=True, help="Starting URL")
    c.add_argument("--instructions", help="Natural-language crawl guidance")
    c.add_argument("--chunks-per-source", type=int, default=3,
                   help="Chunks per source (requires --instructions), 1-5")
    c.add_argument("--max-depth", type=int, default=1, help="Depth 1-5 (default 1)")
    c.add_argument("--max-breadth", type=int, default=20, help="Links per layer 1-500 (default 20)")
    c.add_argument("--limit", type=int, default=50, help="Total links before stopping (default 50)")
    c.add_argument("--extract-depth", default="basic", choices=["basic", "advanced"])
    c.add_argument("--stdout", action="store_true", help="Print full payload to stdout")
    c.add_argument("--output", help="Write full payload to a named file")

    # research ------------------------------------------------------------
    r = sub.add_parser("research", help="Deep research via Tavily Research API (async)")
    rs = r.add_subparsers(dest="research_command", required=True)

    rc = rs.add_parser("create", help="Create a research task")
    rc.add_argument("--input", required=True, help="Research question or topic")
    rc.add_argument("--model", default="auto", choices=["auto", "mini", "pro"])
    rc.add_argument("--output-length", default="standard",
                    choices=["short", "standard", "long"])
    rc.add_argument("--citation-format", default="numbered",
                    choices=["numbered", "mla", "apa", "chicago"])
    rc.add_argument("--wait", action="store_true",
                    help="Poll until complete; print the report to stdout")

    rg = rs.add_parser("get", help="Poll a research task")
    rg.add_argument("--request-id", required=True, help="Task ID from create")

    return parser


def _validate(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    if args.command == "search":
        if not 1 <= args.max_results <= 20:
            parser.error("--max-results must be between 1 and 20")
        if args.stdout and args.output:
            parser.error("use either --stdout or --output, not both")
    elif args.command == "extract":
        if not 1 <= len(args.urls) <= 20:
            parser.error("extract accepts between 1 and 20 URLs")
        if args.chunks_per_source is not None and args.chunks_per_source < 1:
            parser.error("--chunks-per-source must be >= 1")
        if args.chunks_per_source is not None and not args.query:
            parser.error("--chunks-per-source requires --query")
        if args.stdout and args.output:
            parser.error("use either --stdout or --output, not both")
    elif args.command in ("map", "crawl"):
        if not 1 <= args.max_depth <= 5:
            parser.error("--max-depth must be between 1 and 5")
        if args.stdout and args.output:
            parser.error("use either --stdout or --output, not both")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _validate(args, parser)

    try:
        if args.command == "search":
            payload = run_search(args)
            emit_payload(payload, args.stdout, args.output)
        elif args.command == "extract":
            payload = run_extract(args)
            emit_payload(payload, args.stdout, args.output)
        elif args.command == "map":
            payload = run_map(args)
            emit_payload(payload, args.stdout, args.output)
        elif args.command == "crawl":
            payload = run_crawl(args)
            emit_payload(payload, args.stdout, args.output)
        elif args.command == "research":
            if args.research_command == "create":
                payload = run_research_create(args)
                # research create prints directly to stdout (tiny status or full --wait report)
                if payload is not None:
                    print(json.dumps(payload, ensure_ascii=False, indent=2))
            elif args.research_command == "get":
                payload = run_research_get(args)
                print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            parser.error(f"unsupported command: {args.command}")
            return 1
        return 0
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
