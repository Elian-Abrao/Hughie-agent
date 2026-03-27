# Python SDK

Python client for consuming a local `codex-bridge` broker.

This package is intentionally thin. It does not implement OAuth, token refresh, callback handling, or Codex transport rules locally. Those remain inside the broker.

Package name:

```bash
pip install codex-bridge-sdk
```

Import path:

```python
from codex_bridge_sdk import create_chat_client
```

## Local Install

From this repository:

```bash
pip install -e ./sdk
```

Install with FastAPI example dependencies:

```bash
pip install -e './sdk[examples]'
```

## Example

```python
from codex_bridge_sdk import create_chat_client

client = create_chat_client("http://127.0.0.1:47831")
reply = client.chat(
    {
        "model": "gpt-5.4",
        "reasoningEffort": "medium",
        "messages": [{"role": "user", "content": "Explain this file."}],
    }
)

print(reply["outputText"])
```

## Agent API

The SDK can also consume the local agent runtime:

```python
from codex_bridge_sdk import create_bridge_client

client = create_bridge_client("http://127.0.0.1:47831")
session = client.create_agent_session(
    {
        "permissionProfile": "read-only",
        "approvalPolicy": "manual",
    }
)["session"]

turn = client.send_agent_turn(session["id"], "Inspect the repository README.")
events = turn["events"]

pending = turn["session"].get("pendingAction")
if pending:
    approved = client.approve_agent_action(session["id"], pending["id"])
    print(approved["events"][-1]["outputText"])
```

Available agent client methods:

- `list_agent_tools()`
- `create_agent_session(...)`
- `get_agent_session(session_id)`
- `reset_agent_session(session_id)`
- `set_agent_permissions(session_id, permission_profile)`
- `set_agent_approval_policy(session_id, approval_policy)`
- `send_agent_turn(session_id, prompt)`
- `approve_agent_action(session_id, action_id)`
- `reject_agent_action(session_id, action_id, reason=None)`

## FastAPI Example

A minimal proxy example lives in [`examples/fastapi_app.py`](./examples/fastapi_app.py).

Run it with:

```bash
pip install -e './sdk[examples]'
uvicorn fastapi_app:app --app-dir sdk/examples --reload
```

## Tests

```bash
PYTHONPATH=sdk/src python -m unittest discover -s sdk/tests -p 'test_*.py'
```
