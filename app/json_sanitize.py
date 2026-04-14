"""
Escape raw control characters that appear *inside* JSON string values.
"""

from __future__ import annotations


def escape_control_chars_inside_json_strings(s: str) -> str:
    n = len(s)
    i = 0
    out: list[str] = []
    in_string = False

    while i < n:
        c = s[i]
        if not in_string:
            if c == '"':
                in_string = True
                out.append(c)
                i += 1
            else:
                out.append(c)
                i += 1
            continue

        # Inside a JSON string.
        if c == "\\":
            out.append("\\")
            i += 1
            if i >= n:
                break
            c2 = s[i]
            out.append(c2)
            i += 1
            if c2 == "u":
                for _ in range(4):
                    if i < n and s[i] in "0123456789abcdefABCDEF":
                        out.append(s[i])
                        i += 1
                    else:
                        break
            continue

        if c == '"':
            in_string = False
            out.append(c)
            i += 1
            continue

        o = ord(c)
        if c == "\n":
            out.extend(["\\", "n"])
            i += 1
            continue
        if c == "\r":
            out.extend(["\\", "r"])
            i += 1
            continue
        if c == "\t":
            out.extend(["\\", "t"])
            i += 1
            continue
        if o < 32:
            out.append(f"\\u{o:04x}")
            i += 1
            continue

        out.append(c)
        i += 1

    return "".join(out)
