"""Resolving a reference to what it refers to, in any language.

The graph needs one operation: given a position in a file, what does the symbol
there refer to, and what refers to it. Everything else — propagation, scoring,
the whole product — rests on that operation being correct, so this module is the
foundation and its quality bounds everything above it.

**Why a language server rather than a parser.** A parser gives syntax; syntax
cannot tell that `found.describe()` refers to one class's method rather than
another's. A first attempt at this resolved by matching qualified-name strings
and would have collapsed four distinct `describe` methods in one package into a
single node. That is not a Python problem — it is what syntax without
resolution can do in any language.

**Why LSP rather than a per-language library.** The tool has to resolve C,
Rust, Go, JavaScript, OCaml, Lisp, Lua, Python. A resolver library per language
is eight integrations with eight models of what a reference is. The Language
Server Protocol is one interface every one of those languages already
implements, maintained by the people who wrote the language. `references`,
`definition`, and `documentSymbol` are the three operations this needs, and
every mature server provides them.

**What this costs, stated plainly.** A server is a subprocess with a lifecycle:
it must be started, initialized, told about open files, waited for while it
indexes, and shut down. It reports readiness unreliably. It can crash. That
machinery is the price of resolution that works across languages, and it is
paid here so that nothing above this module has to know a subprocess exists.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

from pydantic import BaseModel, Field

logger = logging.getLogger("vesta.resolve")

# Directories never worth handing to a server. Third-party source resolves and
# is not a propagation target, and sending it multiplies indexing time.
_SKIP = (".venv", "node_modules", ".git", "target", "__pycache__", "dist", "build")

# How long to wait for a server to answer one request. Servers index in the
# background and a request arriving mid-index can be slow; a request that never
# returns would hang a build.
TIMEOUT = 20.0

# How long to let a server index before asking it anything. Crude, and the
# reason is that readiness reporting is not reliable across servers: some send
# a progress notification, some send nothing, and none guarantees the index is
# complete when it says it is.
SETTLE = 2.0


class Server(BaseModel):
    """One language server, and what it speaks for."""

    name: str
    command: List[str]
    languages: List[str] = Field(default_factory=list)
    suffixes: List[str] = Field(default_factory=list)

    @property
    def is_available(self) -> bool:
        import shutil

        return bool(self.command) and shutil.which(self.command[0]) is not None


# The servers this knows how to speak to. Adding a language is adding a row —
# no code, because every one of them implements the same three operations.
#
# A server absent from the machine is not an error: the tree is indexed for the
# languages whose servers are present, and the coverage report says which those
# were. A graph that silently omitted a language would under-report propagation
# in exactly the way that makes a correctness claim worthless.
SERVERS: List[Server] = [
    Server(
        name="clangd", command=["clangd", "--log=error"],
        languages=["c", "cpp"], suffixes=[".c", ".h", ".cc", ".cpp", ".hpp"],
    ),
    Server(
        name="rust-analyzer", command=["rust-analyzer"],
        languages=["rust"], suffixes=[".rs"],
    ),
    Server(
        name="pyright", command=["pyright-langserver", "--stdio"],
        languages=["python"], suffixes=[".py"],
    ),
    Server(
        name="gopls", command=["gopls"],
        languages=["go"], suffixes=[".go"],
    ),
    Server(
        name="typescript", command=["typescript-language-server", "--stdio"],
        languages=["javascript", "typescript"],
        suffixes=[".js", ".jsx", ".ts", ".tsx"],
    ),
    Server(
        name="ocamllsp", command=["ocamllsp"],
        languages=["ocaml"], suffixes=[".ml", ".mli"],
    ),
    Server(
        name="lua", command=["lua-language-server"],
        languages=["lua"], suffixes=[".lua"],
    ),
]


class Location(BaseModel):
    """A place in a file. The protocol's own unit, kept rather than translated."""

    path: str
    line: int = Field(description="Zero-based, as the protocol reports it")
    character: int = 0

    @property
    def id(self) -> str:
        return f"{self.path}:{self.line}"

    def describe(self) -> str:
        return f"{self.path}:{self.line + 1}"


class Symbol(BaseModel):
    """A named thing a server found in a file."""

    name: str
    kind: int = Field(description="LSP SymbolKind: 5 class, 6 method, 12 function")
    at: Location
    container: str = ""

    @property
    def is_definition(self) -> bool:
        # Only the kinds a change can meaningfully be *to*. A variable or a
        # field is a real symbol and propagating from every one of them would
        # reach the whole tree.
        return self.kind in (5, 6, 11, 12, 23)

    def describe(self) -> str:
        return f"{self.container + '.' if self.container else ''}{self.name}"


class Coverage(BaseModel):
    """Which languages were resolved and which were not.

    Reported rather than assumed. A propagation result over a tree where half
    the languages had no server is not wrong — it is partial, and the
    difference has to be visible or the correctness claim is hollow.
    """

    resolved: Dict[str, int] = Field(default_factory=dict)
    unresolved: Dict[str, int] = Field(default_factory=dict)

    @property
    def share(self) -> float:
        total = sum(self.resolved.values()) + sum(self.unresolved.values())
        return sum(self.resolved.values()) / total if total else 1.0

    def describe(self) -> str:
        if not self.unresolved:
            return f"{sum(self.resolved.values())} file(s), all resolved"
        missing = ", ".join(
            f"{n} {suffix}" for suffix, n in sorted(self.unresolved.items())
        )
        return (
            f"{sum(self.resolved.values())} of "
            f"{sum(self.resolved.values()) + sum(self.unresolved.values())} "
            f"file(s) resolved; no server for {missing}"
        )


class Session:
    """A running language server, spoken to over the protocol.

    One per language per tree. Held open across queries because starting and
    indexing is the expensive part and a per-query server would pay it every
    time.
    """

    def __init__(self, server: Server, root: Path) -> None:
        self.server = server
        self.root = Path(root).resolve()
        self._process: Optional[subprocess.Popen] = None
        self._next_id = 1
        self._lock = threading.Lock()
        self._opened: set = set()
        self._tree_opened = False

    def __enter__(self) -> "Session":
        self.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.stop()

    def start(self) -> bool:
        if not self.server.is_available:
            return False
        try:
            self._process = subprocess.Popen(
                self.server.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                cwd=str(self.root),
            )
        except OSError as exc:
            logger.warning("could not start %s: %s", self.server.name, exc)
            return False

        answer = self._request(
            "initialize",
            {
                "processId": os.getpid(),
                "rootUri": self.root.as_uri(),
                # Declared, and both are load-bearing. A server told the client
                # cannot supply configuration takes a different startup path;
                # pyright asks twice before it will resolve an import, and a
                # client that neither declares the capability nor answers the
                # request leaves the server half-initialized. It still answers
                # queries — with the wrong answer. Every reference from a test
                # file was missing, and it presented as "this function has two
                # callers" rather than as a failure.
                "workspaceFolders": [
                    {"uri": self.root.as_uri(), "name": self.root.name}
                ],
                "capabilities": {
                    "workspace": {
                        "configuration": True,
                        "workspaceFolders": True,
                    },
                    "textDocument": {
                        "references": {},
                        "definition": {},
                        "documentSymbol": {"hierarchicalDocumentSymbolSupport": True},
                    },
                },
            },
        )
        if answer is None:
            self.stop()
            return False

        self._notify("initialized", {})
        # The server's own requests arrive *after* `initialized`, so the settle
        # has to be a loop that answers them rather than a sleep. Sleeping here
        # was the defect: the requests queued unanswered, the server never
        # finished starting, and it went on answering queries incorrectly.
        self._serve(SETTLE)
        return True

    def _serve(self, seconds: float) -> None:
        """Answer whatever the server asks, for a while.

        A server blocked on a request it sent stops making progress. Draining
        its requests is not optional politeness — it is what lets the server
        finish initializing.
        """
        import select

        deadline = time.time() + seconds
        while time.time() < deadline:
            if self._process is None or self._process.stdout is None:
                return
            readable, _, _ = select.select([self._process.stdout], [], [], 0.2)
            if not readable:
                continue
            message = self._read()
            if message is None:
                return
            if "method" in message and "id" in message:
                self._answer(message)

    def stop(self) -> None:
        if self._process is None:
            return
        try:
            self._notify("exit", None)
            self._process.terminate()
            self._process.wait(timeout=5)
        except Exception:  # noqa: BLE001 - a server that will not die is killed
            try:
                self._process.kill()
            except Exception:  # noqa: BLE001
                pass
        self._process = None

    # ── The three operations ─────────────────────────────────────────────

    def symbols(self, path: Path) -> List[Symbol]:
        """Every named definition in a file."""
        self._open(path)
        answer = self._request(
            "textDocument/documentSymbol",
            {"textDocument": {"uri": Path(path).resolve().as_uri()}},
        )
        return list(self._flatten(answer or [], str(path), ""))

    def references(self, path: Path, line: int, character: int) -> List[Location]:
        """Everywhere a symbol at a position is referred to.

        The tree must be opened first. A server searches the files it has been
        told about, not the files on disk: pyright returned zero references to
        a function called from three places until every file in the tree had
        been sent, and reported that absence as an answer rather than as an
        error. An editor opens files as a user visits them; a whole-tree
        analysis has to open them deliberately.
        """
        self.open_tree(Path(path).resolve().parent)
        self._open(path)
        answer = self._request(
            "textDocument/references",
            {
                "textDocument": {"uri": Path(path).resolve().as_uri()},
                "position": {"line": line, "character": character},
                "context": {"includeDeclaration": False},
            },
        )
        return self._locations(answer)

    def definition(self, path: Path, line: int, character: int) -> List[Location]:
        """What a symbol at a position refers to."""
        self._open(path)
        answer = self._request(
            "textDocument/definition",
            {
                "textDocument": {"uri": Path(path).resolve().as_uri()},
                "position": {"line": line, "character": character},
            },
        )
        return self._locations(answer)

    def open_tree(self, hint: Optional[Path] = None) -> int:
        """Tell the server about every file it can resolve.

        Idempotent and cheap after the first call, since `_open` skips what it
        has already sent. Called before the first reference query rather than
        at startup, so a caller asking only for symbols never pays for it.
        """
        if self._tree_opened:
            return 0
        self._tree_opened = True

        opened = 0
        for path in sorted(self.root.rglob("*")):
            if path.suffix not in self.server.suffixes:
                continue
            if any(part in _SKIP for part in path.parts):
                continue
            self._open(path)
            opened += 1

        if opened:
            # The server has to index what it was just handed, and says
            # nothing reliable about when it has.
            time.sleep(SETTLE)
        return opened

    # ── Protocol ─────────────────────────────────────────────────────────

    def _open(self, path: Path) -> None:
        resolved = Path(path).resolve()
        if str(resolved) in self._opened:
            return
        try:
            text = resolved.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return
        self._notify(
            "textDocument/didOpen",
            {
                "textDocument": {
                    "uri": resolved.as_uri(),
                    "languageId": self.server.languages[0],
                    "version": 1,
                    "text": text,
                }
            },
        )
        self._opened.add(str(resolved))

    def _request(self, method: str, params: Any) -> Any:
        with self._lock:
            if self._process is None or self._process.stdin is None:
                return None
            request_id = self._next_id
            self._next_id += 1
            self._write({"jsonrpc": "2.0", "id": request_id, "method": method,
                         "params": params})

            deadline = time.time() + TIMEOUT
            while time.time() < deadline:
                message = self._read()
                if message is None:
                    # A frame that could not be read at all. Distinct from a
                    # message this client does not care about, and the earlier
                    # conflation of the two is what broke resolution: pyright
                    # asks the client for configuration mid-request, and a
                    # client that abandons the exchange on the first message it
                    # did not expect never receives its answer. Every reference
                    # from a test file was lost that way, and the failure
                    # presented as "this function has two callers" rather than
                    # as an error.
                    return None

                if message.get("id") == request_id:
                    return message.get("result")

                if "method" in message and "id" in message:
                    # A request *from* the server. It is waiting on a reply,
                    # and will not answer anything else until it gets one.
                    self._answer(message)
            return None

    def _answer(self, request: Dict[str, Any]) -> None:
        """Reply to a server-initiated request.

        Minimal by design: this client serves the handful of requests a server
        blocks on and declines the rest. What matters is that every request
        receives *some* well-formed reply, because a server waiting on one
        stops answering.
        """
        method = request.get("method", "")
        if method == "workspace/configuration":
            # One settings object per item asked for. Empty is a valid answer
            # and means "no opinion, use your defaults".
            items = (request.get("params") or {}).get("items") or [{}]
            result: Any = [{} for _ in items]
        elif method in ("client/registerCapability", "client/unregisterCapability"):
            result = None
        elif method == "workspace/workspaceFolders":
            result = [{"uri": self.root.as_uri(), "name": self.root.name}]
        else:
            result = None

        self._write({"jsonrpc": "2.0", "id": request["id"], "result": result})

    def _notify(self, method: str, params: Any) -> None:
        with self._lock:
            if self._process is None or self._process.stdin is None:
                return
            payload: Dict[str, Any] = {"jsonrpc": "2.0", "method": method}
            if params is not None:
                payload["params"] = params
            self._write(payload)

    def _write(self, message: Dict[str, Any]) -> None:
        body = json.dumps(message).encode("utf-8")
        try:
            self._process.stdin.write(  # type: ignore[union-attr]
                b"Content-Length: %d\r\n\r\n%s" % (len(body), body)
            )
            self._process.stdin.flush()  # type: ignore[union-attr]
        except (BrokenPipeError, OSError):
            self._process = None

    def _read(self) -> Optional[Dict[str, Any]]:
        if self._process is None or self._process.stdout is None:
            return None
        headers: Dict[str, str] = {}
        while True:
            try:
                line = self._process.stdout.readline()
            except (OSError, ValueError):
                return None
            if not line:
                return None
            decoded = line.decode("utf-8", "replace").strip()
            if not decoded:
                break
            key, _, value = decoded.partition(": ")
            headers[key.lower()] = value
        length = int(headers.get("content-length", 0) or 0)
        if not length:
            return None
        try:
            return json.loads(self._process.stdout.read(length))
        except (json.JSONDecodeError, OSError):
            return None

    def _locations(self, answer: Any) -> List[Location]:
        """Locations from an answer, in whichever shape the server sent.

        The protocol admits `Location`, `Location[]`, and `LocationLink[]` for
        the same request, and servers differ. Handling one shape and silently
        dropping the others would make a server's choice of encoding look like
        an absence of references.
        """
        if not answer:
            return []
        if isinstance(answer, dict):
            answer = [answer]

        found: List[Location] = []
        seen: set = set()
        for entry in answer:
            uri = entry.get("uri") or entry.get("targetUri") or ""
            span = entry.get("range") or entry.get("targetSelectionRange") or {}
            start = span.get("start") or {}
            if not uri:
                continue
            location = Location(
                path=_from_uri(uri),
                line=int(start.get("line", 0)),
                character=int(start.get("character", 0)),
            )
            # Servers report a reference more than once — clangd returns both
            # the call and its enclosing expression. Deduplicated on position.
            if location.id in seen:
                continue
            seen.add(location.id)
            found.append(location)
        return found

    def _flatten(self, entries: Any, path: str, container: str) -> Iterator[Symbol]:
        for entry in entries or []:
            location = entry.get("selectionRange") or entry.get("range") or {}
            if "location" in entry:  # the flat SymbolInformation shape
                location = entry["location"].get("range", {})
            start = location.get("start") or {}
            symbol = Symbol(
                name=entry.get("name", ""),
                kind=int(entry.get("kind", 0)),
                container=container,
                at=Location(
                    path=path,
                    line=int(start.get("line", 0)),
                    character=int(start.get("character", 0)),
                ),
            )
            if symbol.name:
                yield symbol
            for child in entry.get("children") or []:
                yield from self._flatten(
                    [child], path, f"{container}.{symbol.name}" if container else symbol.name
                )


def _from_uri(uri: str) -> str:
    from urllib.parse import unquote, urlparse

    return unquote(urlparse(uri).path)


def for_suffix(suffix: str) -> Optional[Server]:
    for server in SERVERS:
        if suffix in server.suffixes:
            return server
    return None


def available() -> List[Server]:
    """Which servers this machine can actually run."""
    return [s for s in SERVERS if s.is_available]


def coverage(root: Path | str, ignore: Sequence[str] = (".venv", "node_modules", ".git", "target")) -> Coverage:
    """What share of a tree can be resolved here, before anything is built.

    Asked first because the answer bounds every claim the graph can make, and
    a user whose tree is half Go on a machine with no gopls should learn that
    from a coverage report rather than from a propagation set that quietly
    omits half their code.
    """
    found = Coverage()
    for path in Path(root).rglob("*"):
        if not path.is_file() or any(part in ignore for part in path.parts):
            continue
        server = for_suffix(path.suffix)
        if server is None:
            continue
        bucket = found.resolved if server.is_available else found.unresolved
        bucket[path.suffix] = bucket.get(path.suffix, 0) + 1
    return found
