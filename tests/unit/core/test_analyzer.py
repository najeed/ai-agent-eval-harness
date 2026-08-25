"""
Analyzer tests repository analysis.

Covers: local-checkout scanning (AST + regex detectors), scaffold contract
(oracle-bearing STARTER scenarios, provenance metadata), tarball extraction
safety, SSRF guard, and token redaction. No network access in this suite.
"""

import io
import json
import tarfile

import pytest

from eval_runner.analyzer import (
    AnalyzerUnavailableError,
    _assert_public_host,
    _extract_tarball,
    _redact,
    analyze_repo,
)
from eval_runner.execution_ir import compile_workflow

SAMPLE_REPO = {
    "agent_core.py": """
from langchain.agents import initialize_agent
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(model="gpt-5.6")

def build():
    return initialize_agent(llm=llm)
""",
    "tools/support.py": '''
from langchain.tools import tool

@tool
def refund_tool(order_id: str) -> str:
    """Refund an order."""
    return f"refunded {order_id}"

def internal_helper():
    return 42
''',
    "app/billing.py": """
from flask import Flask

app = Flask(__name__)

@app.route("/api/v1/billing", methods=["GET"])
def billing_view():
    return {"ok": True}
""",
    "client.ts": """
import OpenAI from "openai";
const openai = new OpenAI();
export async function callModel() {
  return openai.chat.completions.create({});
}
""",
    "README.md": "# not code\n",
}


@pytest.fixture
def local_repo(tmp_path, monkeypatch):
    repo = tmp_path / "checkout"
    repo.mkdir()
    for name, content in SAMPLE_REPO.items():
        p = repo / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return repo


@pytest.mark.asyncio
async def test_local_checkout_scan_discovers_all_pattern_types(local_repo):
    results = await analyze_repo(str(local_repo))

    {r["metadata"]["source_file"].split("/")[0] + r["metadata"]["name"] for r in results}
    by_type: dict[str, list] = {}
    for r in results:
        # pattern type encoded in id prefix
        pid = r["id"].split("_")[1]
        by_type.setdefault(pid, []).append(r)

    assert "tool" in "".join(r["id"] for r in results) or any(
        r["metadata"]["name"].find("tool_definition") >= 0 for r in results
    )
    joined = json.dumps(results)
    assert "api_endpoint" in joined
    assert "llm_call" in joined
    assert "/api/v1/billing" in joined
    # README.md must NOT be scanned
    assert "README" not in joined


@pytest.mark.asyncio
async def test_scaffold_scenarios_are_valid_oracle_bearing_starters(local_repo):
    results = await analyze_repo(str(local_repo))
    assert len(results) >= 3

    for scen in results:
        # Provenance bound to the source checkout.
        md = scen["metadata"]
        assert md["generated"] is True
        assert md["generator"] == "analyzer-v1"
        assert md["source_file_hash"].startswith("sha256:")
        # Oracle-bearing: minimum-oracle rule satisfied via state_hygiene.
        node = scen["workflow"]["nodes"][0]
        assert node["state_hygiene"]["rules"], "starter nodes must carry an oracle"
        # Compiles against the canonical IR (entry declared, DAG valid).
        plan = compile_workflow(scen)
        assert plan.entry_node_ids == ["t1"]
        assert "[GENERATED]" in md["name"] or md.get("generated") is True


# ---------------------------------------------------------------------------
# Acquisition safety
# ---------------------------------------------------------------------------


def test_extract_tarball_blocks_path_traversal(tmp_path):
    malicious = io.BytesIO()
    with tarfile.open(fileobj=malicious, mode="w") as tf:
        info = tarfile.TarInfo(name="../escape.py")
        payload = b"x = 1\n"
        import io as _io

        info.size = len(payload)
        tf.addfile(info, _io.BytesIO(payload))

    with pytest.raises(
        (
            tarfile.OutsideDestinationError,
            tarfile.AbsolutePathError,
            tarfile.LinkOutsideDestinationError,
            AnalyzerUnavailableError,
        )
    ):
        _extract_tarball(malicious.getvalue(), tmp_path / "jail")
    assert not (tmp_path / "escape.py").exists()


def test_ssrf_guard_blocks_private_hosts(monkeypatch):
    import socket as _socket

    class _Info(tuple):
        pass

    monkeypatch.setattr(
        _socket,
        "getaddrinfo",
        lambda host, port, proto=0: [(_socket.AF_INET, None, None, "", ("127.0.0.1", 443))],
    )
    with pytest.raises(AnalyzerUnavailableError, match="private/link-local"):
        _assert_public_host("internal.example.com", set())

    # Explicit allowlist waives the block for that host only.
    _assert_public_host("internal.example.com", {"internal.example.com"})


def test_redact_strips_userinfo_credentials():
    dirty = "https://user:supersecret123@github.com/owner/repo"
    cleaned = _redact(dirty)
    assert "supersecret123" not in cleaned
    assert "github.com/owner/repo" in cleaned


@pytest.mark.asyncio
async def test_private_repo_without_token_fails_actionable(monkeypatch):
    """401/403/404 from the forge API with no token → one actionable error."""
    import eval_runner.analyzer as az

    monkeypatch.setattr(az, "_assert_public_host", lambda h, a: None)

    class _Resp:
        status = 404

        async def json(self, content_type=None):
            return {}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def get(self, url, headers=None):
            return _Resp()

    monkeypatch.setattr("aiohttp.ClientSession", lambda **k: _Session())

    with pytest.raises(AnalyzerUnavailableError, match="private or inaccessible"):
        await az._acquire_remote("https://github.com/owner/private-repo", None, "none", set())


@pytest.mark.asyncio
async def test_token_is_sent_as_header_never_logged(monkeypatch):
    """A supplied token authenticates the archive fetch and never leaks."""
    import eval_runner.analyzer as az

    captured: dict[str, str] = {}

    monkeypatch.setattr(az, "_assert_public_host", lambda h, a: None)

    class _Resp:
        status = 200

        def raise_for_status(self):
            pass

        async def json(self, content_type=None):
            return {"sha": "deadbeef" * 5}

        async def read(self):
            return b""

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    class _Headers(dict):
        def __setitem__(self, k, v):
            if k.lower() in ("authorization", "private-token"):
                captured[k.lower()] = v
                v = "***REDACTED***"
            super().__setitem__(k, v)

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def get(self, url, headers=None):
            for hk in ("Authorization", "PRIVATE-TOKEN"):
                if headers and hk in headers:
                    captured.setdefault(hk.lower(), headers[hk])
            return _Resp()

    monkeypatch.setattr("aiohttp.ClientSession", lambda **k: _Session())

    data, meta, is_private = await az._acquire_remote(
        "https://github.com/o/r",
        token="tok_abc123",
        token_source="token-file",
        allow_private_hosts=set(),
    )
    assert meta["resolved_commit"].startswith("deadbeef")
    assert meta["auth_method"] == "token-file"
    assert captured["authorization"] == "Bearer tok_abc123"
    # The secret never appears in any metadata we return.
    assert all("tok_abc123" not in str(v) for v in meta.values())


# ---------------------------------------------------------------------------
# [Humongous-repo] Tree-streaming mode: relevance filter + latency contract
# ---------------------------------------------------------------------------


class _BlobResp:
    status = 200

    def __init__(self, text):
        self._text = text.encode()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def raise_for_status(self):
        pass

    @property
    def content(self):
        data = self._text

        class _C:
            async def iter_chunked(self, n):
                yield data

        return _C()


class _JsonResp(dict):
    status = 200
    headers = {}

    def raise_for_status(self):
        pass

    async def json(self, content_type=None):
        return dict(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


@pytest.mark.asyncio
async def test_tree_stream_skips_build_artifacts_and_reports_honestly(monkeypatch):
    """[Layer-1] Build artifacts are never fetched; truncation flags are real."""
    import eval_runner.analyzer as az

    monkeypatch.setattr(az, "_assert_public_host", lambda h, a: None)

    tree = {
        "tree": [
            {"type": "blob", "path": "src/tools/pay.py", "size": 60},
            {"type": "blob", "path": "node_modules/leftpad/index.js", "size": 10},
            {"type": "blob", "path": "README.md", "size": 5},
            {"type": "blob", "path": "dist/bundle.min.js", "size": 900000},
            {"type": "blob", "path": "src/app.ts", "size": 40},
        ],
        "truncated": False,
    }
    blobs = {
        "src/tools/pay.py": "@tool\ndef pay_tool():\n    pass\n",
        "src/app.ts": "export const make_tool = () => 1;\nopenai.chat.completions.create({});\n",
    }
    requested: list[str] = []

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def get(self, url, headers=None):
            requested.append(url)
            if "/commits/" in url:
                return _JsonResp({"sha": "c0ffee"})
            if "/git/trees/" in url:
                return _JsonResp(tree)
            for rel, text in blobs.items():
                if url.endswith(rel):
                    return _BlobResp(text)
            return _BlobResp("")

    monkeypatch.setattr("aiohttp.ClientSession", lambda **k: _Session())

    findings, meta, is_private = await az._analyze_remote_tree(
        "https://github.com/o/r",
        None,
        None,
        "none",
        set(),
        file_budget=10,
        total_byte_budget=1_000_000,
        max_file_bytes=1000,
        concurrency=4,
        soft_deadline_s=15.0,
    )

    # Layer-1: build artifacts and non-source files NEVER hit the wire.
    assert not any("node_modules" in u for u in requested)
    assert not any(".min.js" in u for u in requested)
    assert not any("README.md" in u for u in requested)
    # Only candidate blobs were fetched (2), commit+tree included.
    assert meta["files_fetched"] == 2
    assert meta["files_scanned"] == 2
    assert meta["truncated"] is False
    assert meta["resolved_commit"] == "c0ffee"
    types = {f["type"] for f in findings}
    assert "tool_definition" in types
    assert "llm_call" in types


@pytest.mark.asyncio
async def test_tree_stream_soft_deadline_marks_truncated(monkeypatch):
    import asyncio as _aio

    import eval_runner.analyzer as az

    monkeypatch.setattr(az, "_assert_public_host", lambda h, a: None)

    tree = {"tree": [{"type": "blob", "path": "big.py", "size": 10}], "truncated": False}

    class _SlowBlob(_BlobResp):
        def __init__(self):
            super().__init__("x = 1\n")

        async def __aenter__(self):
            await _aio.sleep(5)  # far beyond the soft deadline
            return self

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def get(self, url, headers=None):
            if "/commits/" in url:
                return _JsonResp({"sha": "abc"})
            if "/git/trees/" in url:
                return _JsonResp(tree)
            return _SlowBlob()

    monkeypatch.setattr("aiohttp.ClientSession", lambda **k: _Session())

    findings, meta, _ = await az._analyze_remote_tree(
        "https://github.com/o/r",
        None,
        None,
        "none",
        set(),
        file_budget=5,
        total_byte_budget=1_000_000,
        max_file_bytes=1000,
        concurrency=1,
        soft_deadline_s=0.05,
    )
    assert meta["deadline_exceeded"] is True
    assert meta["truncated"] is True
