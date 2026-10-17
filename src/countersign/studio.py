"""The dashboard's analyst. AG Studio runs its own agent loop in the browser and asks for one model turn at a time:
the conversation so far, its tools and instructions. This turns one such request into a chat call on the server's own
model, so the keys never reach the browser, and turns the reply back into the shape Studio reads.

Studio's tools only read the dashboard's data and rearrange its widgets. Nothing here can reach PayPal."""
import json

MAX_ITEMS = 80          # conversation items in one request
MAX_TOOLS = 40
MAX_TEXT = 24000        # characters of any one text
MAX_INSTRUCTIONS = 30000


class BadTurn(ValueError):
    pass


def _text(content) -> str:
    parts = []
    for c in content or []:
        if isinstance(c, dict) and c.get("type") == "text" and isinstance(c.get("text"), str):
            parts.append(c["text"])
    return "\n".join(parts)[:MAX_TEXT]


def to_chat(request: dict) -> tuple[list[dict], list[dict]]:
    """Studio's request as chat messages and tool specs."""
    items = request.get("input")
    if not isinstance(items, list) or len(items) > MAX_ITEMS:
        raise BadTurn("the conversation is missing or too long")
    messages = []
    instructions = request.get("instructions")
    if isinstance(instructions, str) and instructions:
        messages.append({"role": "system", "content": instructions[:MAX_INSTRUCTIONS]})
    calls: list[dict] = []     # assistant tool calls waiting to be attached to one message

    def flush():
        if calls:
            messages.append({"role": "assistant", "content": None, "tool_calls": list(calls)})
            calls.clear()

    for it in items:
        if not isinstance(it, dict):
            raise BadTurn("a conversation item is not an object")
        kind = it.get("type")
        if kind == "function_call":
            calls.append({"id": str(it.get("callId", ""))[:80], "type": "function",
                          "function": {"name": str(it.get("name", ""))[:80], "arguments": str(it.get("arguments") or "{}")[:MAX_TEXT]}})
            continue
        flush()
        if kind == "message":
            role = it.get("role")
            if role == "assistant":
                messages.append({"role": "assistant", "content": _text(it.get("content"))})
            elif role in ("user", "system"):
                messages.append({"role": role, "content": _text(it.get("content"))})
        elif kind == "function_call_output":
            messages.append({"role": "tool", "tool_call_id": str(it.get("callId", ""))[:80], "content": str(it.get("output") or "")[:MAX_TEXT]})
        # reasoning items are the model's own scratch notes and are not sent back
    flush()
    tools = request.get("tools") or []
    if not isinstance(tools, list) or len(tools) > MAX_TOOLS:
        raise BadTurn("too many tools")
    specs = []
    for t in tools:
        if isinstance(t, dict) and t.get("name"):
            specs.append({"type": "function", "function": {"name": str(t["name"])[:80], "description": str(t.get("description") or "")[:2000],
                                                           "parameters": t.get("parameters") or {"type": "object", "properties": {}}}})
    if request.get("toolChoice") == "none":
        specs = []
    return messages, specs


_PLAIN = {"string": str, "array": list, "boolean": bool}


def _fits(value, option) -> bool:
    """Whether a value already looks like this schema option, judged by its type and its `id` tag."""
    if not isinstance(option, dict):
        return False
    kind = option.get("type")
    if kind == "object":
        if not isinstance(value, dict):
            return False
        tag = (option.get("properties") or {}).get("id", {}).get("enum")
        return not tag or value.get("id") in tag
    expected = _PLAIN.get(kind)
    return expected is None or isinstance(value, expected)


def repair(value, schema):
    """Smaller models often get the shape of a tool call slightly wrong: a bare "data" where the schema wants
    {"id": "data"}, a number in quotes, a single item where a list belongs. This puts the value in the shape the
    tool's own schema asks for, when there is one obvious way to do it, and leaves it alone otherwise."""
    if not isinstance(schema, dict):
        return value
    options = schema.get("anyOf") or schema.get("oneOf")
    if options:
        for o in options:
            if _fits(value, o):
                return repair(value, o)
        if isinstance(value, str):     # a bare tag for an option that is an object with an `id`
            for o in options:
                tag = ((o or {}).get("properties") or {}).get("id", {}).get("enum") if isinstance(o, dict) else None
                if tag and value in tag and set(o.get("required") or []) <= {"id"}:
                    return {"id": value}
        return value
    kind = schema.get("type")
    if kind == "object" and isinstance(value, dict):
        props = schema.get("properties") or {}
        return {k: repair(v, props[k]) if k in props else v for k, v in value.items()}
    if kind == "array":
        items = value if isinstance(value, list) else [] if value is None else [value]
        return [repair(v, schema.get("items")) for v in items]
    if kind == "string" and isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    if kind in ("integer", "number") and isinstance(value, str):
        try:
            number = float(value)
        except ValueError:
            return value
        return int(number) if kind == "integer" and number == int(number) else number
    if kind == "boolean" and isinstance(value, str) and value.lower() in ("true", "false"):
        return value.lower() == "true"
    return value


def _repair_calls(output: list[dict], tools: list[dict]) -> None:
    schemas = {t["function"]["name"]: t["function"].get("parameters") for t in tools}
    for item in output:
        if item.get("type") != "function_call" or item.get("name") not in schemas:
            continue
        try:
            args = json.loads(item["arguments"])
        except ValueError:
            continue
        item["arguments"] = json.dumps(repair(args, schemas[item["name"]]))


def to_output(message: dict, tag: str) -> list[dict]:
    """The model's reply as Studio's output items."""
    out = []
    text = message.get("content")
    if isinstance(text, str) and text.strip():
        out.append({"id": f"{tag}-m", "kind": "output", "type": "message", "role": "assistant", "status": "completed",
                    "content": [{"type": "text", "text": text.strip(), "annotations": []}]})
    for i, call in enumerate(message.get("tool_calls") or []):
        fn = call.get("function") or {}
        call_id = call.get("id") or f"{tag}-c{i}"
        arguments = fn.get("arguments")
        if not isinstance(arguments, str):
            arguments = json.dumps(arguments or {})
        out.append({"id": call_id, "kind": "output", "type": "function_call", "callId": call_id, "name": fn.get("name", ""),
                    "arguments": arguments or "{}", "status": "completed"})
    return out


def turn(llm, request: dict, tag: str) -> dict:
    messages, tools = to_chat(request)
    reply = llm.chat(messages, tools or None, patient=False)
    output = to_output(reply, tag)
    _repair_calls(output, tools)
    return {"id": tag, "status": "completed", "output": output, "model": getattr(llm, "last_used", None)}
