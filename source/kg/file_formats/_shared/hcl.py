from __future__ import annotations


def heredoc_start_marker(line: str) -> str | None:
    _, separator, raw_value = line.partition("=")
    if not separator:
        return None
    value = raw_value.strip()
    if value.startswith("<<-"):
        marker = value[3:].strip()
    elif value.startswith("<<"):
        marker = value[2:].strip()
    else:
        return None
    return marker or None


def strip_comments(line: str, *, in_block_comment: bool) -> tuple[str, bool]:
    chars: list[str] = []
    quote: str | None = None
    escaped = False
    index = 0
    while index < len(line):
        char = line[index]
        next_char = line[index + 1] if index + 1 < len(line) else ""
        if in_block_comment:
            if char == "*" and next_char == "/":
                in_block_comment = False
                index += 2
                continue
        elif escaped:
            chars.append(char)
            escaped = False
        elif quote is not None and char == "\\":
            chars.append(char)
            escaped = True
        elif char in {"'", '"'}:
            if quote == char:
                quote = None
            elif quote is None:
                quote = char
            chars.append(char)
        elif quote is None and char == "#":
            return "".join(chars), in_block_comment
        elif quote is None and char == "/" and next_char == "/":
            return "".join(chars), in_block_comment
        elif quote is None and char == "/" and next_char == "*":
            in_block_comment = True
            index += 2
            continue
        else:
            chars.append(char)
        index += 1
    return "".join(chars), in_block_comment


def brace_delta(line: str) -> int:
    quote: str | None = None
    escaped = False
    delta = 0
    for char in line:
        if escaped:
            escaped = False
        elif quote is not None and char == "\\":
            escaped = True
        elif char in {"'", '"'}:
            if quote == char:
                quote = None
            elif quote is None:
                quote = char
        elif quote is None and char == "{":
            delta += 1
        elif quote is None and char == "}":
            delta -= 1
    return delta


def has_brace_outside_quote(line: str) -> bool:
    quote: str | None = None
    escaped = False
    for char in line:
        if escaped:
            escaped = False
        elif quote is not None and char == "\\":
            escaped = True
        elif char in {"'", '"'}:
            if quote == char:
                quote = None
            elif quote is None:
                quote = char
        elif quote is None and char in {"{", "}"}:
            return True
    return False


def quoted_value_at(value: str, start_index: int) -> tuple[str | None, int]:
    quote = value[start_index]
    chars: list[str] = []
    escaped = False
    for index, char in enumerate(value[start_index + 1 :], start=start_index + 1):
        if escaped:
            chars.append(char)
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == quote:
            return "".join(chars).strip(), index + 1
        chars.append(char)
    return None, len(value)
