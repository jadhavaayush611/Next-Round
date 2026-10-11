from typing import Any


def resolve_json_pointer(doc: Any, pointer: str) -> Any:
    """
    Resolve an RFC 6901 JSON pointer against a Python dictionary/list structure.
    Correctly handles:
    - '/' prefix
    - '~1' decoding to '/'
    - '~0' decoding to '~'
    - Object keys
    - Array indices (rejecting negative numbers, leading zeros, or out-of-range indices)

    Raises KeyError, IndexError, LookupError, or ValueError if resolution fails.
    """
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ValueError("JSON Pointer must be a string starting with '/'")

    if pointer == "/":
        if isinstance(doc, dict) and "" in doc:
            return doc[""]
        raise KeyError("Root empty key not found")

    parts = pointer[1:].split("/")
    curr = doc

    for raw_part in parts:
        token = raw_part.replace("~1", "/").replace("~0", "~")

        if isinstance(curr, dict):
            if token not in curr:
                raise KeyError(f"Key '{token}' not found in object")
            curr = curr[token]
        elif isinstance(curr, list):
            if not token.isdigit() or (len(token) > 1 and token.startswith("0")):
                raise IndexError(f"Invalid array index '{token}'")
            idx = int(token)
            if idx < 0 or idx >= len(curr):
                raise IndexError(f"Array index '{idx}' out of range")
            curr = curr[idx]
        else:
            raise LookupError(f"Cannot traverse into non-container value at '{token}'")

    return curr
