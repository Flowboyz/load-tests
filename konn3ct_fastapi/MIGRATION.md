# Migration Guide: Flask to FastAPI

This migration guide details the architectural choices, structural adjustments, and technical enhancements implemented when converting the **Konn3ct Load Testing Framework** from a Flask-based gevent server into a modern, asynchronous FastAPI-based application.

---

## 1. Rationale for Migration

The original Flask application relied on:
- **Gevent monkey patching**: Gevent overrides standard blocking Python libraries with cooperative greenlets. While effective, gevent can be difficult to debug, conflicts with standard asynchronous Python runtimes (such as `aiortc` and `aiohttp` used in the bot engine), and is prone to event loop blocks when heavy CPU operations are run.
- **Flask-SocketIO**: A Socket.IO polling/websocket engine that runs on Eventlet/Gevent greenlets. It carries substantial frame overhead and does not integrate natively with modern Python `asyncio` loops.
- **Synchronous database calls**: Database updates blocked threads until commits were finalized.

By migrating to **FastAPI**, we gain:
1. **Native AsyncIO Event Loop**: Seamless integration with the underlying asynchronous bot dependencies (`aiortc`, `aiohttp`, `websockets`).
2. **Improved Concurrency**: FastAPI handles thousands of concurrent WebSocket connections on a single process thread without cooperative context-switch patching.
3. **No gevent monkey patching**: Prevents thread/socket collision bugs when launching heavy subprocesses or carrying out network operations.
4. **FastAPI Dependencies**: Dependency Injection simplifies injecting clean database connections, authenticating API keys, validating cookies, and validating JWT tokens in routers.

---

## 2. Directory Structure Changes

We transitioned from an ad-hoc Flask app package to a modern **Service-Router** modular design:

| File in Flask app (`Konn3ct_different`) | Mapped File in FastAPI (`konn3ct_fastapi`) | Architectural Role |
| :--- | :--- | :--- |
| `app/__init__.py` | `app.py` | FastAPI setup, middleware configuration, lifespan context, and router mounts. |
| `app/models.py` | `models.py` & `database.py` | SQLite engine setup and SQLAlchemy 2.0 schema classes. |
| `app/auth.py` | `auth.py` | Auth checking dependencies (JWT parsing, API keys, cookies, roles). |
| `app/routes.py` | `routers/api.py` & `routers/reports.py` | REST API routes and chunked report downloads. |
| `app/templates/` | `routers/dashboard.py` | HTML page routing. |
| `app/runner.py` | `services/bot_runner.py` | Spawning and managing the `py_guest` subprocess. |
| `app/runner.py` (tailer) | `services/metrics.py` | Log parsing, resource usage gathering, and WebSocket push triggers. |
| `app/runner.py` (compiler) | `services/reports.py` | Document compilers & converters. |

---

## 3. Database Layer Adaptation

We replaced **Flask-SQLAlchemy** with standard **SQLAlchemy 2.0**:
- **Connection Engine**: Added `check_same_thread=False` to the SQLite database connection, allowing multithreaded requests to query database tables safely.
- **Lifespan Setup**: Replaced Flask's database initialization with FastAPI's native lifespan context. On start, `Base.metadata.create_all` automatically builds tables.
- **Scoped Dependency**: Created a `get_db` generator that yields scoped database sessions and closes them cleanly upon request finalization.

---

## 4. WebSocket Migration: Socket.IO to Native WebSockets

We replaced **Socket.IO** with native HTML5 WebSockets on the `/ws` endpoint:
1. **Connection Manager**: Created a `ConnectionManager` class that maintains lists of active connections and maps them to "session rooms" based on the test session ID.
2. **Standard Upgrade Headers**: Configured Nginx to upgrade standard connections to WebSocket streams natively.
3. **Payload Structure**: Native WebSockets stream JSON packages instead of using custom Socket.IO event namespaces:
   - **Console logs**: `{ "event_type": "session_console_log", "log": "..." }`
   - **Metrics**: `{ "event_type": "session_metrics", "metrics": {...}, "lifecycle_summary": {...} }`
   - **Raw logs**: `{ "event_type": "session_raw_event", "event": {...} }`
   - **Status changes**: `{ "event_type": "session_status_changed", "status": "..." }`
4. **JS Client Upgrade**: Adapted `dashboard.js` to use the standard `new WebSocket()` constructor, sending room subscriptions on connection (`{"action": "join", "session_id": 123}`) and processing standard incoming messages dynamically.

---

## 5. Non-Blocking Subprocess Lifecycles

In Flask, running processes were awaited inside threaded background loops (`runner.py`). In FastAPI, we manage the subprocess runner asynchronously:
- We run `subprocess.Popen` processes asynchronously using `asyncio.to_thread` for waiting (`process.communicate()`), ensuring the main loop continues executing.
- Log tailing is handled using an `asyncio.create_task` loop that tails `report_log.jsonl`, calculates system CPU/RAM, and streams updates.
- Startup session re-adoption is executed in a background task during lifespan initialization, ensuring the server starts instantly without blocking network requests.
