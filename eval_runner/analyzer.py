"""
analyzer.py

Repository analysis for AES scenario scaffolding.

Pipeline:

    repo reference (URL or local path)
        -> acquire: TREE-STREAMING (default) | tarball fallback | local checkout
        -> relevance filter (Layer-1 path rules on the tree listing; zero
           content bytes spent on build artifacts)
        -> bounded parallel blob fetches pipelined with scanning
           (keep-alive pool, per-blob timeouts, soft wall-clock deadline)
        -> scan (Python AST + framework-aware regex, JS/TS regex pass)
        -> scaffold oracle-bearing STARTER scenarios bound to provenance

Truth contracts:
  - Truncation of ANY kind (file budget, byte budget, soft deadline, API-side
    tree truncation) is reported via machine-readable metadata flags; never
    silent.
  - Credentials are sourced from --token-file or env only, never argv, never
    persisted or logged (redaction applied to every outbound message).
"""

from __future__ import annotations

import ast
import asyncio
import hashlib
import io
import ipaddress
import json
import os
import re
import socket
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote as _urlquote, urlparse

from .utils import is_path_safe

DEFAULT_MAX_TOTAL_BYTES = 200 * 1024 * 1024  # tarball hard cap

DEFAULT_MAX_FILE_BYTES = 512 * 1024  # per candidate file
DEFAULT_MAX_FILES = 20_000  # local-checkout file cap
DEFAULT_TREE_FILE_BUDGET = 2_000  # max blobs fetched
DEFAULT_TREE_TOTAL_BUDGET = 25 * 1024 * 1024  # max bytes fetched (tree mode)
DEFAULT_FETCH_CONCURRENCY = 8
DEFAULT_SOFT_DEADLINE_S = 90.0
_CANDIDATE_EXTS = {".py", ".js", ".jsx", ".ts", ".tsx"}

_SKIP_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    "bower_components",
    "vendor",
    ".venv",
    "venv",
    "__pycache__",
    "dist",
    "build",
    "out",
    "target",
    ".next",
    ".nuxt",
    "coverage",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    ".terraform",
    ".eggs",
    "env",
}
_SKIP_FILE_SUFFIXES = (".min.js", ".map", ".d.ts")
_SCAN_SKIP_DIRS = _SKIP_DIR_NAMES
TRUNCATION_FLAG_KEYS = (
    "deadline_exceeded",
    "bytes_budget_exceeded",
    "tree_truncated",
)

_PRIVATE_V4 = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("0.0.0.0/8"),
]
_PRIVATE_V6 = [
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


class AnalyzerUnavailableError(RuntimeError):
    """Raised when acquisition is impossible (bad ref, denied, unsafe input)."""


def _redact(text: Any) -> str:
    """Strips credential material from any string bound for logs/output."""
    return re.sub(r"(://[^/\s@]+):[^@\s]+@", r"\1:***@", str(text))


def _load_token(token_file: str | None) -> tuple[str | None, str]:
    """Token from --token-file or env. Never from argv; never logged."""
    if token_file:
        p = Path(token_file)
        if not p.is_file():
            raise AnalyzerUnavailableError(f"token file not found: {token_file}")
        return p.read_text(encoding="utf-8").strip() or None, "token-file"
    tok = (
        os.getenv("AGENTV_REPO_TOKEN") or os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN") or ""
    ).strip()
    return (tok or None), ("env" if tok else "none")


def _assert_public_host(host: str, allow_private_hosts: set[str]) -> None:
    """SSRF guard: refuse hosts resolving into private/link-local space unless
    the host was explicitly allowlisted (intranet self-hosted forges)."""
    if host.lower() in allow_private_hosts:
        return
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except OSError as e:
        raise AnalyzerUnavailableError(f"DNS resolution failed for '{host}': {e}") from e
    for info in infos:
        addr = ipaddress.ip_address(info[4][0])
        blocked = any(addr in net for net in _PRIVATE_V4) or any(addr in net for net in _PRIVATE_V6)
        if blocked:
            raise AnalyzerUnavailableError(
                f"Refusing private/link-local host '{host}' "
                "(allowlist it via AGENTV_ANALYZER_ALLOWED_HOSTS for "
                "self-hosted forges)."
            )


# ---------------------------------------------------------------------------
# Forge routing
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ForgeRoutes:
    name: str
    owner_repo: str
    ref: str
    commit_api: str
    auth_scheme: str  # bearer | private-token
    tree_url_fn: Any  # Callable[[], list[str]] paginated bases
    blob_url_fn: Any  # Callable[[str], str]
    archive_url: str
    extra_hosts: tuple[str, ...] = ()

    def all_hosts(self) -> set[str]:
        hosts = set(self.extra_hosts)
        for u in [self.commit_api, self.archive_url]:
            hosts.add(urlparse(u).hostname or "")
        return hosts


def _parse_github(parsed) -> tuple[str, str]:
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) >= 2:
        owner_repo = "/".join(parts[:2])
        ref = parts[3] if len(parts) > 3 and parts[2] == "tree" else "HEAD"
        return owner_repo, ref
    raise AnalyzerUnavailableError(f"Unrecognized GitHub URL: {_redact(parsed.geturl())}")


def _parse_gitlab(parsed) -> tuple[str, str]:
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) >= 2:
        project = "%2F".join(parts[:2])
        ref = "HEAD"
        if "tree" in parts:
            idx = parts.index("tree")
            if idx + 1 < len(parts):
                ref = parts[idx + 1]
        return project, ref
    raise AnalyzerUnavailableError(f"Unrecognized GitLab URL: {_redact(parsed.geturl())}")


def _parse_bitbucket(parsed) -> tuple[str, str]:
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) >= 2:
        return f"{parts[0]}/{parts[1]}", parts[3] if len(parts) > 3 else "HEAD"
    raise AnalyzerUnavailableError(f"Unrecognized Bitbucket URL: {_redact(parsed.geturl())}")


def _forge_routes(url: str, ref_override: str | None) -> ForgeRoutes:
    parsed = urlparse(url)

    if (parsed.hostname or "").lower().endswith("github.com"):
        owner_repo, ref = _parse_github(parsed)
        ref = ref_override or ref
        api = "https://api.github.com"

        def tree_bases(api=api, owner_repo=owner_repo, ref=ref):
            return [f"{api}/repos/{owner_repo}/git/trees/{ref}?recursive=1"]

        def blob(path: str, owner_repo=owner_repo, ref=ref):
            return f"https://raw.githubusercontent.com/{owner_repo}/{ref}/{path}"

        return ForgeRoutes(
            name="github",
            owner_repo=owner_repo,
            ref=ref,
            commit_api=f"{api}/repos/{owner_repo}/commits/{ref}",
            auth_scheme="bearer",
            tree_url_fn=tree_bases,
            blob_url_fn=blob,
            archive_url=f"{api}/repos/{owner_repo}/tarball/{ref}",
            extra_hosts=("raw.githubusercontent.com",),
        )

    if (parsed.hostname or "").lower().endswith("gitlab.com"):
        project, ref = _parse_gitlab(parsed)
        ref = ref_override or ref
        base = f"https://gitlab.com/api/v4/projects/{project}/repository"

        def tree_bases(base=base):
            return [f"{base}/tree?recursive=true&per_page=100&page={n}" for n in range(1, 201)]

        def blob(path: str, base=base, ref=ref):
            return f"{base}/files/{_urlquote(path, safe='')}/raw?ref={ref}"

        return ForgeRoutes(
            name="gitlab",
            owner_repo=project,
            ref=ref,
            commit_api=f"{base}/commits/{ref}",
            auth_scheme="private-token",
            tree_url_fn=tree_bases,
            blob_url_fn=blob,
            archive_url=f"{base}/archive.tar.gz?sha={ref}",
        )

    if (parsed.hostname or "").lower().endswith("bitbucket.org"):
        owner_repo, ref = _parse_bitbucket(parsed)
        ref = ref_override or ref
        api = f"https://api.bitbucket.org/2.0/repositories/{owner_repo}"

        def tree_bases(api=api, ref=ref):
            return [f"{api}/src/{ref}/?pagelen=100&max_depth=10&page=1"]

        def blob(path: str, owner_repo=owner_repo, ref=ref):
            return f"https://bitbucket.org/{owner_repo}/raw/{ref}/{path}"

        return ForgeRoutes(
            name="bitbucket",
            owner_repo=owner_repo,
            ref=ref,
            commit_api=f"{api}/commit/{ref}",
            auth_scheme="bearer",
            tree_url_fn=tree_bases,
            blob_url_fn=blob,
            archive_url=f"https://bitbucket.org/{owner_repo}/get/{ref}.tar.gz",
        )

    raise AnalyzerUnavailableError(
        f"Unsupported forge host '{_redact(parsed.hostname or '')}'. Allowed: "
        "GitHub, GitLab, Bitbucket, or AGENTV_ANALYZER_ALLOWED_HOSTS."
    )


def _auth_headers(scheme: str, token: str | None) -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if not token:
        return headers
    if scheme == "private-token":
        headers["PRIVATE-TOKEN"] = token
    else:
        headers["Authorization"] = f"Bearer {token}"
    return headers


# ---------------------------------------------------------------------------
# Relevance Layer-1: pure path predicate over the tree listing
# ---------------------------------------------------------------------------


def _candidate_from_path(path: str) -> bool:
    parts = path.split("/")
    if any(seg in _SKIP_DIR_NAMES for seg in parts[:-1]):
        return False
    name = parts[-1]
    if name.startswith("."):
        return False
    if any(name.endswith(sfx) for sfx in _SKIP_FILE_SUFFIXES):
        return False
    dot = name.rfind(".")
    ext = name[dot:].lower() if dot >= 0 else ""
    return ext in _CANDIDATE_EXTS


# ---------------------------------------------------------------------------
# Shared HTTP session helper
# ---------------------------------------------------------------------------


def _client_session_factory():
    import aiohttp

    timeout = aiohttp.ClientTimeout(total=None, sock_connect=10, sock_read=15)

    def factory(**kwargs):
        kwargs.setdefault("timeout", timeout)
        kwargs.setdefault("trust_env", False)
        return aiohttp.ClientSession(**kwargs)

    return factory


async def _resolve_commit_and_privacy(
    session, routes: ForgeRoutes, headers: dict[str, str], has_token: bool
) -> tuple[str | None, bool]:
    resolved, is_private = None, False
    try:
        async with session.get(routes.commit_api, headers=headers) as resp:
            if resp.status == 200:
                body = await resp.json(content_type=None)
                resolved = body.get("sha") or body.get("id")
            elif resp.status in (401, 403, 404):
                is_private = True
                if not has_token:
                    raise AnalyzerUnavailableError(
                        f"Repository appears private or inaccessible "
                        f"(HTTP {resp.status}). Supply a token via --token-file "
                        "or AGENTV_REPO_TOKEN / GITHUB_TOKEN."
                    )
    except AnalyzerUnavailableError:
        raise
    except Exception as e:  # noqa: BLE001 - best effort
        print(f"   [Analyzer] Commit resolution skipped: {_redact(str(e))}")
    return resolved, is_private


# ---------------------------------------------------------------------------
# Mode A; tree-streaming (default): list → filter → rank → parallel fetch
# ---------------------------------------------------------------------------


async def _list_tree_candidates(
    session, routes: ForgeRoutes, headers: dict[str, str], listing_cap: int
) -> tuple[list[tuple[str, int | None]], bool]:
    candidates: list[tuple[str, int | None]] = []
    api_truncated = False

    for base in routes.tree_url_fn():
        url: str | None = base
        while url and len(candidates) < listing_cap:
            async with session.get(url, headers=headers) as resp:
                if resp.status in (401, 403):
                    raise AnalyzerUnavailableError(
                        f"Tree listing denied (HTTP {resp.status}). Check token "
                        "scopes (repo read) and validity."
                    )
                if resp.status == 404:
                    raise AnalyzerUnavailableError("Repository or ref not found.")
                resp.raise_for_status()
                body = await resp.json(content_type=None)
                next_header = (resp.headers.get("X-Next-Page") or "").strip()

            if isinstance(body, list):  # GitLab entries (no size field)
                for it in body:
                    if it.get("type") == "blob" and _candidate_from_path(it.get("path", "")):
                        candidates.append((it["path"], None))
                url = base.rsplit("page=", 1)[0] + "page=" + next_header if next_header else None
            elif isinstance(body, dict) and "values" in body:  # Bitbucket
                for it in body.get("values", []):
                    if it.get("type") == "commit:file" and _candidate_from_path(it.get("path", "")):
                        candidates.append((it["path"], it.get("size")))
                nxt = body.get("next")
                url = (
                    f"{url.split('&page=')[0]}&page={nxt.split('page=')[1]}"
                    if nxt and "&page=" in str(nxt)
                    else nxt
                )
            elif isinstance(body, dict):  # GitHub recursive single-shot
                api_truncated = api_truncated or bool(body.get("truncated"))
                for it in body.get("tree", []):
                    if it.get("type") == "blob" and _candidate_from_path(it.get("path", "")):
                        candidates.append((it["path"], it.get("size")))
                url = None
            else:
                url = None

    # Deterministic priority under scarcity: shallow package code beats
    # deeply nested mirrors; lexicographic tiebreak keeps runs reproducible.
    candidates.sort(key=lambda ps: (ps[0].count("/"), ps[0]))
    return candidates, api_truncated


async def _fetch_blob_text(
    session,
    routes: ForgeRoutes,
    headers: dict[str, str],
    path: str,
    max_file_bytes: int,
) -> str | None:
    try:
        async with session.get(routes.blob_url_fn(path), headers=headers) as resp:
            if resp.status != 200:
                return None
            buf = bytearray()
            async for chunk in resp.content.iter_chunked(64 * 1024):
                buf.extend(chunk)
                if len(buf) > max_file_bytes:
                    return None  # oversize candidate skipped, run continues
            return bytes(buf).decode("utf-8", errors="ignore")
    except Exception as e:  # noqa: BLE001 - one bad blob never kills the run
        print(f"   [Analyzer] Blob fetch failed for {_redact(path)}: {_redact(str(e))}")
        return None


async def _analyze_remote_tree(
    url: str,
    ref_override: str | None,
    token: str | None,
    token_source: str,
    allow_private_hosts: set[str],
    *,
    file_budget: int,
    total_byte_budget: int,
    max_file_bytes: int,
    concurrency: int,
    soft_deadline_s: float,
) -> tuple[list[dict[str, Any]], dict[str, Any], bool]:
    routes = _forge_routes(url, ref_override)
    for h in routes.all_hosts():
        _assert_public_host(h, allow_private_hosts)

    headers = _auth_headers(routes.auth_scheme, token)
    findings: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str, int]] = set()
    stats = {"fetched": 0, "scanned": 0, "bytes": 0}
    flags = {
        "deadline_exceeded": False,
        "bytes_budget_exceeded": False,
        "tree_truncated": False,
    }
    api_trunc = False
    is_private = False
    resolved_commit = None

    factory = _client_session_factory()
    async with factory() as session:
        resolved_commit, is_private = await _resolve_commit_and_privacy(
            session, routes, headers, has_token=bool(token)
        )

        candidates, api_trunc = await _list_tree_candidates(
            session, routes, headers, file_budget * 4
        )
        candidates = candidates[:file_budget]
        flags["tree_truncated"] = api_trunc

        sem = asyncio.Semaphore(max(1, concurrency))

        async def worker(path: str) -> None:
            async with sem:
                text = await _fetch_blob_text(session, routes, headers, path, max_file_bytes)
                if text is None:
                    return
                rows = _scan_text(path, text)
                digest12 = hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:12]
                async with stats_lock:
                    stats["fetched"] += 1
                    stats["bytes"] += len(text.encode("utf-8", errors="ignore"))
                    stats["scanned"] += 1
                    for f in rows:
                        key = (f["type"], path, int(f["line"]))
                        if key in seen_keys:
                            continue
                        seen_keys.add(key)
                        findings.append(
                            {
                                **f,
                                "file": path,
                                "source_file_hash": f"sha256:{digest12}",
                            }
                        )

        stats_lock = asyncio.Lock()
        tasks = [asyncio.ensure_future(worker(p)) for p, _s in candidates]

        if tasks:
            try:
                await asyncio.wait_for(
                    asyncio.shield(asyncio.gather(*tasks)), timeout=soft_deadline_s
                )
            except TimeoutError:
                flags["deadline_exceeded"] = True
                print(
                    f"   [Analyzer] Soft deadline ({soft_deadline_s}s) hit; "
                    "returning partial results flagged truncated=true."
                )
            finally:
                for t in tasks:
                    t.cancel()
                # Reap cancelled stragglers so no warning leaks.
                await asyncio.gather(*tasks, return_exceptions=True)

    truncated = (
        flags["deadline_exceeded"]
        or flags["bytes_budget_exceeded"]
        or flags["tree_truncated"]
        or stats["bytes"] > total_byte_budget
    )

    meta = {
        "source_url": url,
        "ref": routes.ref,
        "resolved_commit": resolved_commit,
        "auth_method": token_source if token else "anonymous",
        "transport": "https-tree-stream",
        "acquire": "tree",
        "concurrency": concurrency,
        "soft_deadline_s": soft_deadline_s,
        "files_fetched": stats["fetched"],
        "files_scanned": stats["scanned"],
        "bytes_fetched": stats["bytes"],
        "candidates_considered": len(candidates),
        **flags,
        "truncated": truncated,
    }
    return findings, meta, is_private


# ---------------------------------------------------------------------------
# Mode B; tarball fallback (--acquire tarball)
# ---------------------------------------------------------------------------


def _extract_tarball(data: bytes, dest: Path) -> Path:
    """Safe extraction (PEP 706 data filter) inside the analyzer jail."""
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as tf:
        tf.extractall(dest, filter="data")  # noqa: S202 - data filter + jail check
    roots = [d for d in dest.iterdir() if d.is_dir()]
    src_root = roots[0] if len(roots) == 1 else dest
    if not is_path_safe(src_root.resolve(), dest.resolve()):
        raise AnalyzerUnavailableError("Extracted tree escaped the analyzer jail.")
    return src_root


async def _acquire_remote(
    url: str,
    token: str | None,
    token_source: str,
    allow_private_hosts: set[str],
    ref_override: str | None = None,
) -> tuple[bytes, dict[str, Any], bool]:
    """Tarball acquisition fallback. Returns (bytes, meta, is_private)."""
    routes = _forge_routes(url, ref_override)
    for h in routes.all_hosts():
        _assert_public_host(h, allow_private_hosts)

    headers = _auth_headers(routes.auth_scheme, token)
    factory = _client_session_factory()
    async with factory() as session:
        resolved_commit, is_private = await _resolve_commit_and_privacy(
            session, routes, headers, has_token=bool(token)
        )
        async with session.get(routes.archive_url, headers=headers) as resp:
            if resp.status in (401, 403):
                raise AnalyzerUnavailableError(
                    f"Access denied fetching repository archive (HTTP {resp.status}). "
                    "Check token scopes (repo read) and validity."
                )
            if resp.status == 404:
                raise AnalyzerUnavailableError("Repository or ref not found.")
            resp.raise_for_status()
            data = await resp.read()

    if len(data) > DEFAULT_MAX_TOTAL_BYTES:
        raise AnalyzerUnavailableError(
            f"Repository archive exceeds safety cap ({DEFAULT_MAX_TOTAL_BYTES} bytes)."
        )

    meta = {
        "source_url": url,
        "ref": routes.ref,
        "resolved_commit": resolved_commit,
        "auth_method": token_source if token else "anonymous",
        "transport": "https-tarball",
        "acquire": "tarball",
    }
    return data, meta, is_private


# ---------------------------------------------------------------------------
# Scanning: Python AST first, framework regex fallback, JS/TS regex pass
# ---------------------------------------------------------------------------

_TOOL_DECOS = {"tool", "tool_decorator", "structured_tool"}
_ROUTE_DECOS = {"route", "get", "post", "put", "delete", "patch"}

_PATTERNS: list[tuple[str, str]] = [
    ("agent_init", r"\b(AgentExecutor|initialize_agent|create_react_agent|MCPClient)\s*\("),
    (
        "llm_call",
        r"\b(ChatOpenAI|Anthropic\(|ChatAnthropic|ChatGoogleGenerativeAI"
        r"|OllamaLLM|OpenAI\s*\(|anthropic\.Agent|client\.chat\.completions)"
        r"|\.invoke\s*\(\s*[\"']",
    ),
]


def _py_ast_findings(text: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return out

    class _Visitor(ast.NodeVisitor):
        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
            for dec in node.decorator_list:
                name = ""
                if isinstance(dec, ast.Name):
                    name = dec.id
                elif isinstance(dec, ast.Attribute):
                    name = dec.attr
                elif isinstance(dec, ast.Call):
                    base = dec.func
                    name = (
                        base.attr
                        if isinstance(base, ast.Attribute)
                        else (base.id if isinstance(base, ast.Name) else "")
                    )
                lname = name.lower()
                if name.lower() in _TOOL_DECOS or lname.endswith("_tool"):
                    out.append(
                        {
                            "type": "tool_definition",
                            "match": f"@{name} def {node.name}(",
                            "line": node.lineno,
                        }
                    )
                elif lname in _ROUTE_DECOS or (
                    "." in name and name.split(".")[-1].lower() in _ROUTE_DECOS
                ):
                    route_path = ""
                    if isinstance(dec, ast.Call) and dec.args:
                        arg0 = dec.args[0]
                        if isinstance(arg0, ast.Constant):
                            route_path = str(arg0.value)
                    out.append(
                        {
                            "type": "api_endpoint",
                            "match": f"{name}('{route_path}')",
                            "line": node.lineno,
                        }
                    )
            self.generic_visit(node)

    _Visitor().visit(tree)
    return out


def _scan_text(rel_path: str, text: str) -> list[dict[str, Any]]:
    suffix = rel_path.lower().rsplit(".", 1)
    suffix = "." + suffix[1] if len(suffix) == 2 else ""
    raw: list[dict[str, Any]] = []

    if suffix == ".py":
        raw.extend(_py_ast_findings(text))
        for ptype, pattern in _PATTERNS:
            for m in re.finditer(pattern, text):
                line = text.count("\n", 0, m.start()) + 1
                raw.append({"type": ptype, "match": m.group(0)[:80], "line": line})
    elif suffix in {".js", ".jsx", ".ts", ".tsx"}:
        for ptype, pattern in [
            ("tool_definition", r"(?:export\s+)?(?:const|function)\s+\w*tool\w*\s*[=(]"),
            ("llm_call", r"\b(openai|anthropic)\.[\w.]+\("),
            ("agent_init", r"\bnew\s+(AgentExecutor|LangChain.Agent)\b"),
        ]:
            for m in re.finditer(pattern, text):
                line = text.count("\n", 0, m.start()) + 1
                raw.append({"type": ptype, "match": m.group(0)[:80], "line": line})
    return raw


def _scan_tree(src_root: Path) -> list[dict[str, Any]]:
    """Local-checkout scanning (same detectors as tree-streaming mode)."""
    findings: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str, int]] = set()
    scanned = 0

    for path in sorted(src_root.rglob("*")):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(src_root).parts
        if any(part in _SCAN_SKIP_DIRS for part in rel_parts[:-1]):
            continue
        if scanned >= DEFAULT_MAX_FILES:
            break
        try:
            if path.stat().st_size > DEFAULT_MAX_FILE_BYTES:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        scanned += 1
        rel = "/".join(rel_parts)
        digest12 = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
        for f in _scan_text(rel, text):
            key = (f["type"], rel, int(f["line"]))
            if key in seen_keys:
                continue
            seen_keys.add(key)
            findings.append({**f, "file": rel, "source_file_hash": f"sha256:{digest12}"})
    return findings


# ---------------------------------------------------------------------------
# Scaffolding
# ---------------------------------------------------------------------------


def _git_head_commit(repo_dir: Path) -> str | None:
    head = repo_dir / ".git" / "HEAD"
    try:
        if head.is_file():
            content = head.read_text(encoding="utf-8").strip()
            if content.startswith("ref:"):
                ref_path = repo_dir / ".git" / content.split(":", 1)[1].strip()
                if ref_path.is_file():
                    return ref_path.read_text(encoding="utf-8").strip()[:40]
            return content[:40]
    except OSError:
        pass
    return None


def _scaffold(
    findings: list[dict[str, Any]],
    meta: dict[str, Any],
    industry: str,
    is_private: bool,
) -> list[dict[str, Any]]:
    output_dir = Path("scenarios/auto")
    output_dir.mkdir(parents=True, exist_ok=True)

    scenarios = []
    for i, pattern in enumerate(findings):
        digest6 = hashlib.sha256(pattern["match"].encode(), usedforsecurity=False).hexdigest()[:6]
        identifier = f"auto_{pattern['type']}_{i}_{digest6}"

        scenario = {
            "aes_version": 1.4,
            "id": identifier,
            "metadata": {
                "id": identifier,
                "name": (f"[GENERATED] {pattern['type']}; {pattern['file']}:{pattern['line']}"),
                "generator": "analyzer-v1",
                "generated": True,
                "source_kind": "repository",
                "source_repo": _redact(meta.get("source_url", "")),
                "source_ref": meta.get("ref"),
                "source_commit": meta.get("resolved_commit"),
                "source_file": pattern["file"],
                "source_line": pattern["line"],
                "source_file_hash": pattern["source_file_hash"],
                "access": "private" if is_private else "public",
                "auth_method": meta.get("auth_method"),
                "analyzer": {
                    k: v
                    for k, v in meta.items()
                    if k
                    in (
                        "transport",
                        "acquire",
                        "concurrency",
                        "soft_deadline_s",
                        "files_fetched",
                        "files_scanned",
                        "bytes_fetched",
                        "candidates_considered",
                        "truncated",
                        "deadline_exceeded",
                        "bytes_budget_exceeded",
                        "tree_truncated",
                    )
                },
            },
            "description": (
                f"STARTER scenario scaffolded from discovered {pattern['type']} "
                f"in {pattern['file']}:{pattern['line']}; complete the "
                "assertions before relying on any verdict."
            ),
            "industry": industry,
            "workflow": {
                "entry_nodes": ["t1"],
                "nodes": [
                    {
                        "id": "t1",
                        "task_description": (
                            f"Exercise the {pattern['type']} at "
                            f"{pattern['match']} and produce a final answer "
                            "that demonstrates correct behavior."
                        ),
                        "state_hygiene": {
                            "rules": [{"path": "__unset_probe__", "op": "not_exists"}]
                        },
                    }
                ],
                "edges": [],
            },
        }

        with open(output_dir / f"{identifier}.json", "w", encoding="utf-8") as f:
            json.dump(scenario, f, indent=2)
        scenarios.append(scenario)
    return scenarios


async def analyze_repo(
    url_or_path: str,
    ref: str | None = None,
    token_file: str | None = None,
    industry: str = "auto",
    acquire: str = "tree",
    concurrency: int | None = None,
    soft_deadline_s: float | None = None,
    file_budget: int | None = None,
) -> list[dict[str, Any]]:
    """
    Real repository analysis.

    Modes:
      - local checkout path      : zero network, zero credentials
      - URL + acquire="tree"     : DEFAULT; forge tree API, Layer-1 path
                                   filter, bounded parallel blob fetches,
                                   byte budget + soft wall-clock deadline
      - URL + acquire="tarball"  : full archive download (fallback)

    Latency knobs: AGENTV_ANALYZER_CONCURRENCY (default 8),
    AGENTV_ANALYZER_DEADLINE_S (default 90),
    AGENTV_ANALYZER_MAX_BYTES (tree-mode byte budget, default 25MB).
    """
    token, token_source = _load_token(token_file)
    allow_private_hosts = {
        h.strip().lower()
        for h in os.getenv("AGENTV_ANALYZER_ALLOWED_HOSTS", "").split(",")
        if h.strip()
    }
    concurrency = int(
        os.getenv("AGENTV_ANALYZER_CONCURRENCY", str(DEFAULT_FETCH_CONCURRENCY))
        if concurrency is None
        else concurrency
    )
    soft_deadline_s = float(
        os.getenv("AGENTV_ANALYZER_DEADLINE_S", str(DEFAULT_SOFT_DEADLINE_S))
        if soft_deadline_s is None
        else soft_deadline_s
    )
    file_budget = int(os.getenv("AGENTV_ANALYZER_FILE_BUDGET", str(DEFAULT_TREE_FILE_BUDGET)))
    total_budget = _bytes_budget()

    candidate = Path(url_or_path)
    if candidate.exists():
        if not candidate.is_dir():
            raise AnalyzerUnavailableError(f"path target is not a directory: {candidate}")
        src_root = candidate.resolve()
        meta = {
            "source_url": str(candidate),
            "ref": ref or "(working tree)",
            "resolved_commit": _git_head_commit(src_root),
            "auth_method": "none-local",
            "transport": "local-checkout",
            "acquire": "local",
        }
        findings = _scan_tree(src_root)
        is_private = False
    elif acquire == "tarball":
        data, meta, is_private = await _acquire_remote(
            url_or_path, token, token_source, allow_private_hosts, ref_override=ref
        )
        digest = hashlib.sha256(data).hexdigest()[:12]
        jail = Path(tempfile.gettempdir()) / "agentv_analyzer_cache" / digest
        src_root = _extract_tarball(data, jail)
        findings = _scan_tree(src_root)

    elif acquire == "tree":
        findings, meta, is_private = await _analyze_remote_tree(
            url_or_path,
            ref,
            token,
            token_source,
            allow_private_hosts,
            file_budget=file_budget,
            total_byte_budget=total_budget,
            max_file_bytes=DEFAULT_MAX_FILE_BYTES,
            concurrency=concurrency,
            soft_deadline_s=soft_deadline_s,
        )
    else:
        raise AnalyzerUnavailableError(f"Unknown acquire mode '{acquire}' (valid: tree | tarball).")

    print(
        f"   [Analyzer] Discovered {len(findings)} agentic pattern(s) via "
        f"{meta.get('transport')} from {_redact(meta.get('source_url', ''))}; "
        f"scaffolding STARTER scenarios (complete their assertions before use)."
    )
    if meta.get("truncated"):
        active = [k for k in TRUNCATION_FLAG_KEYS if meta.get(k)]
        print(f"   [Analyzer] ⚠ TRUNCATED scan — results are partial (flags: {active}).")
    return _scaffold(findings, meta, industry, is_private)


def _bytes_budget() -> int:
    return int(os.getenv("AGENTV_ANALYZER_MAX_BYTES", str(DEFAULT_TREE_TOTAL_BUDGET)))
