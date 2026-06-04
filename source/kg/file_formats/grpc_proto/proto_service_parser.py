"""Deterministic proto3/proto2 parser for gRPC service declarations.

This is a real lexer + recursive-descent parser over the protobuf grammar's
service blocks (``service S { rpc M (Req) returns (Resp); }``); it is not a
keyword/regex heuristic. ``service``, ``rpc``, ``returns``, ``stream``, and
``package`` are reserved words of the protobuf grammar, recognized the same way
a Python AST recognizes ``def``.

Only what is needed to surface gRPC endpoints is parsed: the package name, each
service, and each rpc method's name, request/response message types, and
streaming flags. Message/enum/option bodies are skipped (balanced).
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Ordinary whitespace plus a UTF-8 BOM, which some proto files begin with (e.g. eShop's
# basket.proto). chr(0xFEFF) keeps the BOM out of the source as an invisible literal.
_WHITESPACE = " \t\r\f\v" + chr(0xFEFF)
_IDENT_EXTRA = "_."


@dataclass(frozen=True)
class _Token:
    kind: str  # "name" | "punct" | "string" | "other"
    text: str
    line: int


@dataclass(frozen=True)
class RpcMethod:
    name: str
    request_type: str
    response_type: str
    client_streaming: bool
    server_streaming: bool
    line: int


@dataclass(frozen=True)
class ProtoService:
    name: str
    package: str | None
    rpcs: tuple[RpcMethod, ...]


@dataclass
class ProtoParseResult:
    services: list[ProtoService] = field(default_factory=list)
    # Lines where an ``rpc`` keyword was seen but the signature could not be
    # parsed into request/response types — surfaced as loud-refusal coverage,
    # never guessed.
    unparsed_rpc_lines: list[int] = field(default_factory=list)


def parse_proto_services(text: str) -> ProtoParseResult:
    tokens = _tokenize(text)
    result = ProtoParseResult()
    package: str | None = None
    i = 0
    n = len(tokens)
    while i < n:
        token = tokens[i]
        if token.kind == "name" and token.text == "package":
            package, i = _parse_package(tokens, i + 1)
            continue
        if token.kind == "name" and token.text == "service":
            service, i = _parse_service(tokens, i + 1, package, result)
            if service is not None:
                result.services.append(service)
            continue
        i += 1
    return result


def _tokenize(text: str) -> list[_Token]:
    tokens: list[_Token] = []
    i = 0
    line = 1
    n = len(text)
    while i < n:
        char = text[i]
        if char == "\n":
            line += 1
            i += 1
            continue
        if char in _WHITESPACE:
            i += 1
            continue
        if char == "/" and i + 1 < n and text[i + 1] == "/":
            i += 2
            while i < n and text[i] != "\n":
                i += 1
            continue
        if char == "/" and i + 1 < n and text[i + 1] == "*":
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                if text[i] == "\n":
                    line += 1
                i += 1
            i += 2  # consume the closing */
            continue
        if char in "\"'":
            quote = char
            start_line = line
            i += 1
            while i < n and text[i] != quote:
                if text[i] == "\\" and i + 1 < n:
                    i += 2
                    continue
                if text[i] == "\n":
                    line += 1
                i += 1
            i += 1  # consume the closing quote
            tokens.append(_Token("string", "", start_line))
            continue
        if char.isalpha() or char == "_":
            start = i
            while i < n and (text[i].isalnum() or text[i] in _IDENT_EXTRA):
                i += 1
            tokens.append(_Token("name", text[start:i], line))
            continue
        tokens.append(_Token("punct", char, line))
        i += 1
    return tokens


def _parse_package(tokens: list[_Token], i: int) -> tuple[str | None, int]:
    parts: list[str] = []
    n = len(tokens)
    while i < n and not _is_punct(tokens[i], ";"):
        if tokens[i].kind == "name":
            parts.append(tokens[i].text)
        i += 1
    return (".".join(parts) if parts else None), i + 1


def _parse_service(
    tokens: list[_Token],
    i: int,
    package: str | None,
    result: ProtoParseResult,
) -> tuple[ProtoService | None, int]:
    n = len(tokens)
    if i >= n or tokens[i].kind != "name":
        return None, i + 1
    service_name = tokens[i].text
    i += 1
    while i < n and not _is_punct(tokens[i], "{"):
        if _is_punct(tokens[i], ";"):  # forward declaration / malformed — no body
            return None, i + 1
        i += 1
    if i >= n:
        return None, i
    i += 1  # consume "{"
    rpcs: list[RpcMethod] = []
    depth = 1
    while i < n and depth > 0:
        token = tokens[i]
        if _is_punct(token, "{"):
            depth += 1
            i += 1
            continue
        if _is_punct(token, "}"):
            depth -= 1
            i += 1
            continue
        if depth == 1 and token.kind == "name" and token.text == "rpc":
            rpc, i = _parse_rpc(tokens, i + 1, token.line)
            if rpc is not None:
                rpcs.append(rpc)
            else:
                result.unparsed_rpc_lines.append(token.line)
            continue
        i += 1
    return ProtoService(name=service_name, package=package, rpcs=tuple(rpcs)), i


def _parse_rpc(tokens: list[_Token], i: int, rpc_line: int) -> tuple[RpcMethod | None, int]:
    n = len(tokens)

    def fail() -> tuple[None, int]:
        # Resync to the end of this statement so the service loop keeps progress
        # without mis-reading the remainder of the rpc. Stop at the service-closing
        # "}" WITHOUT consuming it, so the service-body loop still sees it and does
        # not bleed into the next service block.
        j = i
        while (
            j < n
            and not _is_punct(tokens[j], ";")
            and not _is_punct(tokens[j], "{")
            and not _is_punct(tokens[j], "}")
        ):
            j += 1
        if j < n and _is_punct(tokens[j], "{"):
            j = _skip_balanced_braces(tokens, j)
        elif j < n and _is_punct(tokens[j], ";"):
            j += 1
        return None, j

    if i >= n or tokens[i].kind != "name":
        return fail()
    method = tokens[i].text
    i += 1
    if not (i < n and _is_punct(tokens[i], "(")):
        return fail()
    i += 1
    client_streaming, i = _consume_stream(tokens, i)
    request_type, i = _consume_type_name(tokens, i)
    if request_type is None:
        return fail()
    if not (i < n and _is_punct(tokens[i], ")")):
        return fail()
    i += 1
    if not (i < n and tokens[i].kind == "name" and tokens[i].text == "returns"):
        return fail()
    i += 1
    if not (i < n and _is_punct(tokens[i], "(")):
        return fail()
    i += 1
    server_streaming, i = _consume_stream(tokens, i)
    response_type, i = _consume_type_name(tokens, i)
    if response_type is None:
        return fail()
    if not (i < n and _is_punct(tokens[i], ")")):
        return fail()
    i += 1
    # A proper rpc statement is terminated by ";" or an options block "{ ... }".
    # Without a terminator the signature is malformed — refuse, don't surface it.
    if i < n and _is_punct(tokens[i], ";"):
        i += 1
    elif i < n and _is_punct(tokens[i], "{"):
        i = _skip_balanced_braces(tokens, i)
    else:
        return fail()
    return (
        RpcMethod(
            name=method,
            request_type=request_type,
            response_type=response_type,
            client_streaming=client_streaming,
            server_streaming=server_streaming,
            line=rpc_line,
        ),
        i,
    )


def _consume_type_name(tokens: list[_Token], i: int) -> tuple[str | None, int]:
    # Message type at a request/response position, optionally root-qualified with a
    # leading dot (e.g. `.google.protobuf.Empty`). The lexer emits the leading "." as
    # its own punct token because identifiers cannot start with ".", so consume it here.
    # Inner dots (`google.protobuf.Empty`) are already part of a single name token.
    n = len(tokens)
    if i < n and _is_punct(tokens[i], "."):
        i += 1
    if i < n and tokens[i].kind == "name":
        return tokens[i].text, i + 1
    return None, i


def _consume_stream(tokens: list[_Token], i: int) -> tuple[bool, int]:
    if i < len(tokens) and tokens[i].kind == "name" and tokens[i].text == "stream":
        return True, i + 1
    return False, i


def _skip_balanced_braces(tokens: list[_Token], i: int) -> int:
    # tokens[i] is the opening "{"; return the index just past its matching "}".
    n = len(tokens)
    depth = 0
    while i < n:
        if _is_punct(tokens[i], "{"):
            depth += 1
        elif _is_punct(tokens[i], "}"):
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return i


def _is_punct(token: _Token, char: str) -> bool:
    return token.kind == "punct" and token.text == char
