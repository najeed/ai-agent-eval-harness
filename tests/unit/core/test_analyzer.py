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


# ===========================================================================
# Exhaustive Coverage Expansion for analyzer.py
# ===========================================================================


class TestTokenLoadingAndSSRF:
    def test_load_token_from_file_success(self, tmp_path):
        from eval_runner.analyzer import _load_token

        tok_file = tmp_path / "token.txt"
        tok_file.write_text("ghp_secret123\n", encoding="utf-8")
        tok, source = _load_token(str(tok_file))
        assert tok == "ghp_secret123"
        assert source == "token-file"

    def test_load_token_from_file_missing_raises(self, tmp_path):
        from eval_runner.analyzer import AnalyzerUnavailableError, _load_token

        missing = tmp_path / "non_existent_token.txt"
        with pytest.raises(AnalyzerUnavailableError, match="token file not found"):
            _load_token(str(missing))

    def test_load_token_from_env(self, monkeypatch):
        from eval_runner.analyzer import _load_token

        monkeypatch.setenv("AGENTV_REPO_TOKEN", "agentv_tok_abc")
        tok, src = _load_token(None)
        assert tok == "agentv_tok_abc"
        assert src == "env"

    def test_load_token_none(self, monkeypatch):
        from eval_runner.analyzer import _load_token

        monkeypatch.delenv("AGENTV_REPO_TOKEN", raising=False)
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("GH_TOKEN", raising=False)
        tok, src = _load_token(None)
        assert tok is None
        assert src == "none"

    def test_assert_public_host_allowed_private_host(self):
        from eval_runner.analyzer import _assert_public_host

        # Host explicitly in allowlist passes without DNS lookup
        _assert_public_host("gitlab.local", {"gitlab.local"})

    def test_assert_public_host_dns_failure(self):
        import socket
        from unittest.mock import patch

        from eval_runner.analyzer import AnalyzerUnavailableError, _assert_public_host

        with patch("socket.getaddrinfo", side_effect=socket.gaierror("No such host")):
            with pytest.raises(AnalyzerUnavailableError, match="DNS resolution failed"):
                _assert_public_host("nonexistent.invalid.domain", set())

    def test_assert_public_host_private_ipv4(self):
        import socket
        from unittest.mock import patch

        from eval_runner.analyzer import AnalyzerUnavailableError, _assert_public_host

        mock_info = [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("127.0.0.1", 443))
        ]
        with patch("socket.getaddrinfo", return_value=mock_info):
            with pytest.raises(AnalyzerUnavailableError, match="Refusing private/link-local host"):
                _assert_public_host("localhost", set())

    def test_assert_public_host_private_ipv6(self):
        import socket
        from unittest.mock import patch

        from eval_runner.analyzer import AnalyzerUnavailableError, _assert_public_host

        mock_info = [
            (socket.AF_INET6, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("::1", 443, 0, 0))
        ]
        with patch("socket.getaddrinfo", return_value=mock_info):
            with pytest.raises(AnalyzerUnavailableError, match="Refusing private/link-local host"):
                _assert_public_host("localhost", set())


class TestForgeParsersAndRoutes:
    def test_parse_github_invalid_raises(self):
        from urllib.parse import urlparse

        from eval_runner.analyzer import AnalyzerUnavailableError, _parse_github

        with pytest.raises(AnalyzerUnavailableError, match="Unrecognized GitHub URL"):
            _parse_github(urlparse("https://github.com/"))

    def test_parse_gitlab_success_and_branches(self):
        from urllib.parse import urlparse

        from eval_runner.analyzer import AnalyzerUnavailableError, _parse_gitlab

        # Standard gitlab repo with tree
        proj, ref = _parse_gitlab(urlparse("https://gitlab.com/group/project/tree/develop"))
        assert proj == "group%2Fproject"
        assert ref == "develop"

        # Gitlab repo without tree
        proj2, ref2 = _parse_gitlab(urlparse("https://gitlab.com/group/project"))
        assert proj2 == "group%2Fproject"
        assert ref2 == "HEAD"

        # Invalid gitlab url
        with pytest.raises(AnalyzerUnavailableError, match="Unrecognized GitLab URL"):
            _parse_gitlab(urlparse("https://gitlab.com/"))

    def test_parse_bitbucket_success_and_invalid(self):
        from urllib.parse import urlparse

        from eval_runner.analyzer import AnalyzerUnavailableError, _parse_bitbucket

        # Valid bitbucket
        proj, ref = _parse_bitbucket(
            urlparse("https://bitbucket.org/owner/repo/src/feature-branch")
        )
        assert proj == "owner/repo"
        assert ref == "feature-branch"

        # Valid bitbucket without branch
        proj2, ref2 = _parse_bitbucket(urlparse("https://bitbucket.org/owner/repo"))
        assert proj2 == "owner/repo"
        assert ref2 == "HEAD"

        # Invalid bitbucket url
        with pytest.raises(AnalyzerUnavailableError, match="Unrecognized Bitbucket URL"):
            _parse_bitbucket(urlparse("https://bitbucket.org/"))

    def test_forge_routes_gitlab_and_bitbucket(self):
        from eval_runner.analyzer import AnalyzerUnavailableError, _forge_routes

        # GitLab routes
        gl = _forge_routes("https://gitlab.com/org/sub/tree/main", "override_ref")
        assert gl.name == "gitlab"
        assert gl.ref == "override_ref"
        assert gl.auth_scheme == "private-token"
        assert "gitlab.com" in gl.all_hosts()
        assert len(gl.tree_url_fn()) > 0
        assert "raw?ref=" in gl.blob_url_fn("src/main.py")

        # Bitbucket routes
        bb = _forge_routes("https://bitbucket.org/team/repo", None)
        assert bb.name == "bitbucket"
        assert bb.ref == "HEAD"
        assert bb.auth_scheme == "bearer"
        assert "bitbucket.org" in bb.all_hosts()
        assert len(bb.tree_url_fn()) > 0
        assert "raw/HEAD/" in bb.blob_url_fn("src/lib.py")

        # Unsupported forge host
        with pytest.raises(AnalyzerUnavailableError, match="Unsupported forge host"):
            _forge_routes("https://sourceforge.net/p/myproj", None)

    def test_auth_headers(self):
        from eval_runner.analyzer import _auth_headers

        assert _auth_headers("bearer", None) == {"Accept": "application/json"}
        assert _auth_headers("private-token", "gl_pat_123") == {
            "Accept": "application/json",
            "PRIVATE-TOKEN": "gl_pat_123",
        }
        assert _auth_headers("bearer", "ghp_abc") == {
            "Accept": "application/json",
            "Authorization": "Bearer ghp_abc",
        }


class TestCandidateFromPath:
    def test_candidate_from_path_hidden_and_skipped_suffixes(self):
        from eval_runner.analyzer import _candidate_from_path

        assert _candidate_from_path(".env") is False
        assert _candidate_from_path("src/.hidden.py") is False
        assert _candidate_from_path("dist/bundle.min.js") is False
        assert _candidate_from_path("src/app.d.ts") is False
        assert _candidate_from_path("src/valid.py") is True
        assert _candidate_from_path("src/valid.ts") is True


class TestRemoteResolutionAndTreeListing:
    @pytest.mark.asyncio
    async def test_resolve_commit_and_privacy_unauthorized_without_token(self):
        from eval_runner.analyzer import (
            AnalyzerUnavailableError,
            ForgeRoutes,
            _resolve_commit_and_privacy,
        )

        class _401Resp:
            status = 401

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

        class _Session:
            def get(self, url, headers=None):
                return _401Resp()

        routes = ForgeRoutes(
            name="github",
            owner_repo="o/r",
            ref="main",
            commit_api="http://dummy",
            auth_scheme="bearer",
            tree_url_fn=lambda: [],
            blob_url_fn=lambda p: "",
            archive_url="",
        )
        with pytest.raises(
            AnalyzerUnavailableError, match="Repository appears private or inaccessible"
        ):
            await _resolve_commit_and_privacy(_Session(), routes, {}, has_token=False)

    @pytest.mark.asyncio
    async def test_resolve_commit_and_privacy_exception_swallowed(self):
        from eval_runner.analyzer import ForgeRoutes, _resolve_commit_and_privacy

        class _ErrorSession:
            def get(self, url, headers=None):
                raise RuntimeError("Network glitch")

        routes = ForgeRoutes(
            name="github",
            owner_repo="o/r",
            ref="main",
            commit_api="http://dummy",
            auth_scheme="bearer",
            tree_url_fn=lambda: [],
            blob_url_fn=lambda p: "",
            archive_url="",
        )
        commit, is_priv = await _resolve_commit_and_privacy(
            _ErrorSession(), routes, {}, has_token=True
        )
        assert commit is None
        assert is_priv is False

    @pytest.mark.asyncio
    async def test_list_tree_candidates_errors(self):
        from eval_runner.analyzer import (
            AnalyzerUnavailableError,
            ForgeRoutes,
            _list_tree_candidates,
        )

        class _Resp:
            def __init__(self, status):
                self.status = status

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            def raise_for_status(self):
                pass

        routes = ForgeRoutes(
            name="github",
            owner_repo="o/r",
            ref="main",
            commit_api="",
            auth_scheme="bearer",
            tree_url_fn=lambda: ["http://tree1"],
            blob_url_fn=lambda p: "",
            archive_url="",
        )

        class _403Session:
            def get(self, url, headers=None):
                return _Resp(403)

        with pytest.raises(AnalyzerUnavailableError, match="Tree listing denied"):
            await _list_tree_candidates(_403Session(), routes, {}, 10)

        class _404Session:
            def get(self, url, headers=None):
                return _Resp(404)

        with pytest.raises(AnalyzerUnavailableError, match="Repository or ref not found"):
            await _list_tree_candidates(_404Session(), routes, {}, 10)

    @pytest.mark.asyncio
    async def test_list_tree_candidates_gitlab_and_bitbucket_formats(self):
        from eval_runner.analyzer import ForgeRoutes, _list_tree_candidates

        # 1. GitLab list format
        class _GLResp:
            status = 200
            headers = {"X-Next-Page": "2"}

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            def raise_for_status(self):
                pass

            async def json(self, content_type=None):
                return [{"type": "blob", "path": "gl_app.py"}, {"type": "tree", "path": "dir"}]

        class _GLSession:
            def get(self, url, headers=None):
                # Only return on page 1, stop on page 2
                resp = _GLResp()
                if "page=2" in url:
                    resp.headers = {"X-Next-Page": ""}
                return resp

        gl_routes = ForgeRoutes(
            name="gitlab",
            owner_repo="o/r",
            ref="main",
            commit_api="",
            auth_scheme="private-token",
            tree_url_fn=lambda: ["http://gl/tree?page=1"],
            blob_url_fn=lambda p: "",
            archive_url="",
        )
        cands, _ = await _list_tree_candidates(_GLSession(), gl_routes, {}, 10)
        assert len(cands) >= 1
        assert cands[0][0] == "gl_app.py"

        # 2. Bitbucket values format
        class _BBResp:
            status = 200
            headers = {}

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            def raise_for_status(self):
                pass

            async def json(self, content_type=None):
                return {
                    "values": [{"type": "commit:file", "path": "bb_app.py", "size": 100}],
                    "next": None,
                }

        class _BBSession:
            def get(self, url, headers=None):
                return _BBResp()

        bb_routes = ForgeRoutes(
            name="bitbucket",
            owner_repo="o/r",
            ref="main",
            commit_api="",
            auth_scheme="bearer",
            tree_url_fn=lambda: ["http://bb/src/?page=1"],
            blob_url_fn=lambda p: "",
            archive_url="",
        )
        cands_bb, _ = await _list_tree_candidates(_BBSession(), bb_routes, {}, 10)
        assert len(cands_bb) == 1
        assert cands_bb[0][0] == "bb_app.py"


class TestBlobFetchingAndScanning:
    @pytest.mark.asyncio
    async def test_fetch_blob_text_non_200_and_oversize_and_error(self):
        from eval_runner.analyzer import ForgeRoutes, _fetch_blob_text

        routes = ForgeRoutes(
            name="github",
            owner_repo="o/r",
            ref="main",
            commit_api="",
            auth_scheme="bearer",
            tree_url_fn=lambda: [],
            blob_url_fn=lambda p: f"http://blob/{p}",
            archive_url="",
        )

        class _StatusResp:
            def __init__(self, status):
                self.status = status

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

        class _404Session:
            def get(self, url, headers=None):
                return _StatusResp(404)

        # 404 returns None
        assert await _fetch_blob_text(_404Session(), routes, {}, "missing.py", 1000) is None

        class _BigContent:
            async def iter_chunked(self, n):
                yield b"x" * 2000

        class _BigResp:
            status = 200
            content = _BigContent()

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

        class _BigSession:
            def get(self, url, headers=None):
                return _BigResp()

        # Oversize returns None
        assert await _fetch_blob_text(_BigSession(), routes, {}, "big.py", 500) is None

        class _ErrSession:
            def get(self, url, headers=None):
                raise OSError("Connection reset")

        # Exception returns None
        assert await _fetch_blob_text(_ErrSession(), routes, {}, "err.py", 1000) is None

    def test_py_ast_findings_syntax_error_and_decorator_variants(self):
        from eval_runner.analyzer import _py_ast_findings

        # Syntax error returns empty
        assert _py_ast_findings("def invalid syntax (:") == []

        # Attribute decorator and non-constant route path
        code = """
import flask
app = flask.Flask(__name__)

class Tools:
    @custom_tool
    def helper_tool(self): pass

@app.route(get_dynamic_path())
def dynamic_endpoint(): pass

@regular_decorator
def non_matching(): pass
"""
        findings = _py_ast_findings(code)
        types = [f["type"] for f in findings]
        assert "tool_definition" in types
        assert "api_endpoint" in types


class TestLocalTreeScanAndGitHead:
    def test_scan_tree_skips_large_files_and_oserror(self, tmp_path):
        import stat
        from unittest.mock import patch

        from eval_runner.analyzer import _scan_tree

        # 1. Normal file
        (tmp_path / "valid.py").write_text("def test(): pass", encoding="utf-8")
        # 2. Oversize file
        (tmp_path / "large.py").write_text("x = 1\n" * 100, encoding="utf-8")

        with patch("pathlib.Path.stat") as mock_stat:

            class MockStat:
                st_size = 999_999_999  # Exceeds max
                st_mode = stat.S_IFREG | 0o644

            mock_stat.return_value = MockStat()
            findings = _scan_tree(tmp_path)
            assert findings == []

    def test_git_head_commit_direct_sha_and_ref(self, tmp_path):
        from eval_runner.analyzer import _git_head_commit

        git_dir = tmp_path / ".git"
        git_dir.mkdir()

        # 1. Direct commit SHA in HEAD
        (git_dir / "HEAD").write_text(
            "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678\n", encoding="utf-8"
        )
        assert _git_head_commit(tmp_path) == "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"

        # 2. Ref pointer in HEAD
        (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
        refs_main = git_dir / "refs" / "heads" / "main"
        refs_main.parent.mkdir(parents=True, exist_ok=True)
        refs_main.write_text("fedcba9876543210fedcba9876543210fedcba98\n", encoding="utf-8")
        assert _git_head_commit(tmp_path) == "fedcba9876543210fedcba9876543210fedcba98"

        # 3. No git HEAD returns None
        assert _git_head_commit(tmp_path / "non_git") is None


class TestAnalyzeRepoModes:
    @pytest.mark.asyncio
    async def test_analyze_repo_not_a_dir_raises(self, tmp_path):
        from eval_runner.analyzer import AnalyzerUnavailableError, analyze_repo

        file_target = tmp_path / "file.txt"
        file_target.write_text("not a dir", encoding="utf-8")

        with pytest.raises(AnalyzerUnavailableError, match="path target is not a directory"):
            await analyze_repo(str(file_target))

    @pytest.mark.asyncio
    async def test_analyze_repo_invalid_acquire_mode_raises(self):
        from eval_runner.analyzer import AnalyzerUnavailableError, analyze_repo

        with pytest.raises(AnalyzerUnavailableError, match="Unknown acquire mode"):
            await analyze_repo("https://github.com/o/r", acquire="ftp")

    @pytest.mark.asyncio
    async def test_analyze_repo_tarball_mode(self, tmp_path, monkeypatch):
        import io
        import tarfile
        from unittest.mock import patch

        from eval_runner.analyzer import analyze_repo

        # Build in-memory tarball
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            info = tarfile.TarInfo(name="repo/app.py")
            content = b"agent = initialize_agent(llm=None)\n"
            info.size = len(content)
            tf.addfile(info, io.BytesIO(content))
        tar_bytes = buf.getvalue()

        async def mock_acquire(*args, **kwargs):
            return (
                tar_bytes,
                {
                    "source_url": "https://github.com/o/r",
                    "transport": "https-tarball",
                    "ref": "main",
                },
                False,
            )

        with patch("eval_runner.analyzer._acquire_remote", side_effect=mock_acquire):
            with patch("eval_runner.analyzer._assert_public_host"):
                scenarios = await analyze_repo("https://github.com/o/r", acquire="tarball")
                assert len(scenarios) >= 1
                assert scenarios[0]["metadata"]["source_repo"] == "https://github.com/o/r"

    @pytest.mark.asyncio
    async def test_analyze_repo_tree_mode_with_truncation_warning(self, monkeypatch):
        from unittest.mock import patch

        from eval_runner.analyzer import analyze_repo

        mock_findings = [
            {
                "type": "llm_call",
                "match": "ChatOpenAI()",
                "line": 5,
                "file": "app.py",
                "source_file_hash": "sha256:1234567890ab",
            }
        ]
        mock_meta = {
            "source_url": "https://github.com/o/r",
            "ref": "main",
            "transport": "https-tree-stream",
            "truncated": True,
            "tree_truncated": True,
        }

        with patch(
            "eval_runner.analyzer._analyze_remote_tree",
            return_value=(mock_findings, mock_meta, False),
        ):
            scenarios = await analyze_repo("https://github.com/o/r", acquire="tree")
            assert len(scenarios) == 1
            assert scenarios[0]["metadata"]["source_repo"] == "https://github.com/o/r"


class TestTarballAndAcquisitionEdgeCases:
    def test_extract_tarball_jail_escape_raises(self, tmp_path):
        import io
        import tarfile
        from unittest.mock import patch

        from eval_runner.analyzer import AnalyzerUnavailableError, _extract_tarball

        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            info = tarfile.TarInfo(name="repo/app.py")
            content = b"x = 1\n"
            info.size = len(content)
            tf.addfile(info, io.BytesIO(content))
        tar_bytes = buf.getvalue()

        jail_dest = tmp_path / "jail"
        with patch("eval_runner.analyzer.is_path_safe", return_value=False):
            with pytest.raises(
                AnalyzerUnavailableError, match="Extracted tree escaped the analyzer jail"
            ):
                _extract_tarball(tar_bytes, jail_dest)

    @pytest.mark.asyncio
    async def test_acquire_remote_error_branches(self, monkeypatch):
        from eval_runner.analyzer import AnalyzerUnavailableError, _acquire_remote

        class _StatusResp:
            def __init__(self, status, data=b""):
                self.status = status
                self._data = data

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            def raise_for_status(self):
                pass

            async def read(self):
                return self._data

            async def json(self, content_type=None):
                return {"sha": "123"}

        monkeypatch.setattr("eval_runner.analyzer._assert_public_host", lambda h, a: None)

        class _403Session:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            def get(self, url, headers=None):
                if "commits" in url:
                    return _StatusResp(200, b'{"sha": "123"}')
                return _StatusResp(403)

        monkeypatch.setattr("aiohttp.ClientSession", lambda **k: _403Session())
        with pytest.raises(
            AnalyzerUnavailableError, match="Access denied fetching repository archive"
        ):
            await _acquire_remote("https://github.com/o/r", "tok", "token-file", set())

        class _404Session:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            def get(self, url, headers=None):
                if "commits" in url:
                    return _StatusResp(200, b'{"sha": "123"}')
                return _StatusResp(404)

        monkeypatch.setattr("aiohttp.ClientSession", lambda **k: _404Session())
        with pytest.raises(AnalyzerUnavailableError, match="Repository or ref not found"):
            await _acquire_remote("https://github.com/o/r", "tok", "token-file", set())

        class _OversizeSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            def get(self, url, headers=None):
                if "commits" in url:
                    return _StatusResp(200, b'{"sha": "123"}')
                return _StatusResp(200, b"x" * 2000)

        monkeypatch.setattr("eval_runner.analyzer.DEFAULT_MAX_TOTAL_BYTES", 1000)
        monkeypatch.setattr("aiohttp.ClientSession", lambda **k: _OversizeSession())
        with pytest.raises(AnalyzerUnavailableError, match="Repository archive exceeds safety cap"):
            await _acquire_remote("https://github.com/o/r", "tok", "token-file", set())


class TestASTAndScanTreeEdgeCases:
    def test_gitlab_parse_trailing_tree_without_branch(self):
        from urllib.parse import urlparse

        from eval_runner.analyzer import _parse_gitlab

        # When 'tree' is the last segment with no branch after it
        proj, ref = _parse_gitlab(urlparse("https://gitlab.com/group/project/tree"))
        assert proj == "group%2Fproject"
        assert ref == "HEAD"

    def test_py_ast_decorator_call_with_constant_path(self):
        from eval_runner.analyzer import _py_ast_findings

        code = """
@app.route("/api/v2/users")
def get_users(): pass

@custom.my_tool
def custom_tool_func(): pass
"""
        findings = _py_ast_findings(code)
        assert any(f["match"] == "route('/api/v2/users')" for f in findings)
        assert any("custom_tool_func" in f["match"] for f in findings)

    def test_scan_tree_skips_dirs_and_handles_oserror(self, tmp_path):
        from eval_runner.analyzer import _scan_tree

        # Node_modules directory should be skipped
        nm = tmp_path / "node_modules"
        nm.mkdir()
        (nm / "index.js").write_text("const tool = 1;", encoding="utf-8")

        # Regular dir with file
        src = tmp_path / "src"
        src.mkdir()
        f = src / "app.py"
        f.write_text(
            "from langchain.agents import initialize_agent\ninitialize_agent()", encoding="utf-8"
        )

        findings = _scan_tree(tmp_path)
        assert len(findings) >= 1
        assert not any("node_modules" in f["file"] for f in findings)

    def test_git_head_commit_missing_ref_file_and_oserror(self, tmp_path):
        from unittest.mock import patch

        from eval_runner.analyzer import _git_head_commit

        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "HEAD").write_text("ref: refs/heads/nonexistent_branch\n", encoding="utf-8")
        assert _git_head_commit(tmp_path) == "ref: refs/heads/nonexistent_branch"

        with patch("pathlib.Path.read_text", side_effect=OSError("Disk error")):
            assert _git_head_commit(tmp_path) is None

    def test_ast_and_tree_final_branches(self, tmp_path):
        from unittest.mock import patch

        from eval_runner.analyzer import _py_ast_findings, _scan_tree

        # 1. AST call with func being a lambda or complex expr, route decorator without args
        code = """
@(lambda: tool_decorator)()
def f1(): pass

@app.route
def f2(): pass

@app.route()
def f3(): pass
"""
        findings = _py_ast_findings(code)
        assert len(findings) >= 1

        # 2. _scan_tree with hit on DEFAULT_MAX_FILES and duplicate finding
        src = tmp_path / "src_max"
        src.mkdir()
        (src / "a.py").write_text("initialize_agent()\n", encoding="utf-8")
        (src / "b.py").write_text("initialize_agent()\n", encoding="utf-8")

        with patch("eval_runner.analyzer.DEFAULT_MAX_FILES", 1):
            findings_max = _scan_tree(src)
            assert len(findings_max) == 1

        # 3. _scan_tree OSError on file reading
        with patch("pathlib.Path.read_text", side_effect=OSError("Read error")):
            assert _scan_tree(src) == []


class TestTreeStreamRemainingBranches:
    @pytest.mark.asyncio
    async def test_list_tree_candidates_unknown_body_and_non_blob_values(self):
        from eval_runner.analyzer import ForgeRoutes, _list_tree_candidates

        class _UnknownResp:
            status = 200
            headers = {}

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            def raise_for_status(self):
                pass

            async def json(self, content_type=None):
                return "invalid_string_body"

        class _Session:
            def get(self, url, headers=None):
                return _UnknownResp()

        routes = ForgeRoutes(
            name="github",
            owner_repo="o/r",
            ref="main",
            commit_api="",
            auth_scheme="bearer",
            tree_url_fn=lambda: ["http://u"],
            blob_url_fn=lambda p: "",
            archive_url="",
        )
        cands, _ = await _list_tree_candidates(_Session(), routes, {}, 10)
        assert cands == []

        # Bitbucket with directory (non-commit:file)
        class _BBNonFileResp:
            status = 200
            headers = {}

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            def raise_for_status(self):
                pass

            async def json(self, content_type=None):
                return {"values": [{"type": "commit_directory", "path": "dir"}], "next": None}

        class _BBSession:
            def get(self, url, headers=None):
                return _BBNonFileResp()

        cands_bb, _ = await _list_tree_candidates(_BBSession(), routes, {}, 10)
        assert cands_bb == []

    @pytest.mark.asyncio
    async def test_analyze_remote_tree_empty_candidates_and_duplicate_findings(self, monkeypatch):
        import eval_runner.analyzer as az

        monkeypatch.setattr(az, "_assert_public_host", lambda h, a: None)

        # Tree with 0 candidates
        class _EmptyTreeSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            def get(self, url, headers=None):
                class _R:
                    status = 200
                    headers = {}

                    async def __aenter__(self):
                        return self

                    async def __aexit__(self, *a):
                        return False

                    def raise_for_status(self):
                        pass

                    async def json(self, content_type=None):
                        if "commits" in url:
                            return {"id": "123"}
                        return {"tree": []}

                return _R()

        monkeypatch.setattr("aiohttp.ClientSession", lambda **k: _EmptyTreeSession())
        findings, meta, _ = await az._analyze_remote_tree(
            "https://github.com/o/r",
            None,
            None,
            "none",
            set(),
            file_budget=5,
            total_byte_budget=1000,
            max_file_bytes=100,
            concurrency=1,
            soft_deadline_s=10.0,
        )
        assert findings == []
        assert meta["candidates_considered"] == 0

        # Tree with duplicate findings inside same file in remote tree scan
        class _RemoteDupeSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            def get(self, url, headers=None):
                class _R:
                    status = 200
                    headers = {}

                    async def __aenter__(self):
                        return self

                    async def __aexit__(self, *a):
                        return False

                    def raise_for_status(self):
                        pass

                    async def json(self, content_type=None):
                        if "commits" in url:
                            return ["not_a_dict"]
                        return {"tree": [{"type": "blob", "path": "dupe.py"}]}

                return _R()

        monkeypatch.setattr("aiohttp.ClientSession", lambda **k: _RemoteDupeSession())

        # Return text with multiple identical findings on line 1 (hits line 479)
        async def mock_fetch_dupe(*a, **k):
            return "initialize_agent(); initialize_agent()\n"

        monkeypatch.setattr(az, "_fetch_blob_text", mock_fetch_dupe)
        findings_dupe, _, _ = await az._analyze_remote_tree(
            "https://github.com/o/r",
            None,
            None,
            "none",
            set(),
            file_budget=5,
            total_byte_budget=1000,
            max_file_bytes=100,
            concurrency=1,
            soft_deadline_s=10.0,
        )
        assert len(findings_dupe) == 1

    def test_ast_call_decorator_non_attr_name(self):
        from eval_runner.analyzer import _py_ast_findings

        # Hits line 630->637 with call decorator where base is a constant or slice
        code = """
@("not_func")()
def fn(): pass
"""
        assert _py_ast_findings(code) == []

    def test_assert_public_host_allowed_public_ip(self):
        import socket
        from unittest.mock import patch

        from eval_runner.analyzer import _assert_public_host

        mock_info = [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("8.8.8.8", 443))]
        with patch("socket.getaddrinfo", return_value=mock_info):
            _assert_public_host("google.com", set())

    def test_scan_tree_duplicate_findings_in_same_file(self, tmp_path):
        from eval_runner.analyzer import _scan_tree

        src = tmp_path / "src_dupe"
        src.mkdir()
        # Same pattern twice on line 1
        (src / "app.py").write_text("initialize_agent(); initialize_agent()\n", encoding="utf-8")
        findings = _scan_tree(src)
        assert len(findings) == 1
