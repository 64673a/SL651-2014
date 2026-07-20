"""Web 调试控制台：实时报文 + 下行调试 + 模拟 RTU 控制"""

import asyncio
import threading
from pathlib import Path
from typing import Any, Optional

from .bus import bus
from .center import CenterHub, hub
from .constants import FUNC_CODES
from .encoder import build_down_frame
from .hexutil import bytes_to_hex, hex_to_bytes
from .parser import parse_frame, parse_hex
from .rtu import SimulatedRtu
from .store import store

STATIC_DIR = Path(__file__).resolve().parent / "static"

_rtu: Optional[SimulatedRtu] = None
_rtu_thread: Optional[threading.Thread] = None
_rtu_lock = threading.Lock()


def create_app(center: Optional[CenterHub] = None):
    try:
        from fastapi import FastAPI, Query, WebSocket
        from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
        from fastapi.staticfiles import StaticFiles
    except ImportError as e:
        raise SystemExit(
            "Web 模式需要安装依赖: pip install fastapi uvicorn[standard]"
        ) from e

    app = FastAPI(title="SL651 中心站调试助手", version="0.3.0")
    center = center or hub

    assets_dir = STATIC_DIR / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")
    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/")
    async def index():
        index_path = STATIC_DIR / "index.html"
        if index_path.is_file():
            return FileResponse(index_path)
        return HTMLResponse(
            "<h1>前端未构建</h1><p>请执行: <code>cd web && npm install && npm run build</code></p>",
            status_code=500,
        )

    # ── 状态 ──────────────────────────────────────────────

    @app.get("/api/status")
    async def status():
        with _rtu_lock:
            rtu_info = None
            if _rtu:
                rtu_info = {
                    "running": _rtu._connected or (_rtu_thread and _rtu_thread.is_alive()),
                    "remote_addr": _rtu.remote_addr,
                    "center_addr": f"{_rtu.center_addr:02X}",
                    "host": _rtu.host,
                    "port": _rtu.port,
                    "heartbeat_interval": _rtu.heartbeat_interval,
                    "report_interval": _rtu.report_interval,
                    "water_level": _rtu.water_level,
                    "rain": _rtu.rain,
                    "voltage": _rtu.voltage,
                }
        try:
            stats = store.stats()
        except Exception:
            stats = {}
        return {
            "center": {
                "running": center.running,
                "host": center.host,
                "port": center.port,
                "auto_ack": center.auto_ack,
            },
            "clients": center.list_clients(),
            "rtu": rtu_info,
            "func_codes": {f"{k:02X}": v for k, v in FUNC_CODES.items()},
            "stats": stats,
            "db": str(store.db_path),
        }

    # ── 报文（SQLite 分页）────────────────────────────────

    @app.get("/api/messages")
    async def messages(
        limit: int = Query(50, ge=1, le=500),
        offset: int = Query(0, ge=0),
        direction: Optional[str] = None,
        peer: Optional[str] = None,
        func_code: Optional[str] = None,
        crc_ok: Optional[bool] = None,
        keyword: Optional[str] = None,
    ):
        return store.query(
            direction=direction,
            peer=peer,
            func_code=func_code,
            crc_ok=crc_ok,
            keyword=keyword,
            limit=limit,
            offset=offset,
        )

    @app.get("/api/messages/{msg_id}")
    async def message_detail(msg_id: str):
        rec = store.get(msg_id)
        if not rec:
            return JSONResponse({"ok": False, "error": "not found"}, status_code=404)
        return rec

    @app.delete("/api/messages")
    async def clear_messages(scope: str = Query("db", pattern="^(db|memory|all)$")):
        """
        scope:
          - db: 仅清空 SQLite 历史库
          - memory: 仅清空服务端内存缓存（一般由前端本地清空实时流）
          - all: 两者都清
        """
        deleted = 0
        if scope in ("db", "all"):
            deleted = bus.clear_store()
        if scope in ("memory", "all"):
            bus.clear_memory()
        bus.emit("system", {"msg": f"报文已清空 scope={scope} deleted={deleted}"})
        return {"ok": True, "scope": scope, "deleted": deleted}

    @app.get("/api/stats")
    async def api_stats():
        return store.stats()

    @app.get("/api/clients")
    async def clients():
        return center.list_clients()

    # ── 解析 ──────────────────────────────────────────────

    @app.post("/api/parse")
    async def api_parse(payload: dict[str, Any]):
        hex_str = payload.get("hex", "")
        try:
            frame = parse_hex(hex_str)
            return {"ok": True, "parsed": frame.to_dict()}
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=400)

    # ── 下行 ──────────────────────────────────────────────

    @app.post("/api/send")
    async def api_send(payload: dict[str, Any]):
        peer = payload.get("peer")
        if not peer:
            return JSONResponse({"ok": False, "error": "缺少 peer"}, status_code=400)
        try:
            mode = payload.get("mode", "hex")
            if mode == "hex":
                rec = center.send_hex(
                    peer, payload.get("hex", ""), note=payload.get("note", "Web 下行 hex")
                )
            elif mode == "ack":
                rec = center.send_ack(peer, payload.get("hex", ""))
            else:
                rec = center.send_down(
                    peer=peer,
                    func_code=int(str(payload.get("func_code", "37")), 16),
                    body_hex=payload.get("body_hex", ""),
                    remote_addr=payload.get("remote_addr"),
                    center_addr=int(str(payload.get("center_addr", "1")), 16)
                    if payload.get("center_addr") is not None
                    else None,
                    password=payload.get("password"),
                    end_flag=int(str(payload.get("end_flag", "04")), 16),
                    note=payload.get("note", "Web 下行调试"),
                )
            return {"ok": True, "record": rec}
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=400)

    @app.post("/api/build-down")
    async def api_build_down(payload: dict[str, Any]):
        try:
            frame = build_down_frame(
                remote_addr=payload.get("remote_addr", "0010100001"),
                center_addr=int(str(payload.get("center_addr", "01")), 16),
                password=payload.get("password", "0000"),
                func_code=int(str(payload.get("func_code", "37")), 16),
                body=hex_to_bytes(payload.get("body_hex", "")) if payload.get("body_hex") else b"",
                end_flag=int(str(payload.get("end_flag", "04")), 16),
            )
            parsed = parse_frame(frame).to_dict()
            return {"ok": True, "hex": bytes_to_hex(frame, sep=""), "parsed": parsed}
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=400)

    @app.post("/api/center/config")
    async def center_config(payload: dict[str, Any]):
        if "auto_ack" in payload:
            center.auto_ack = bool(payload["auto_ack"])
            bus.emit("system", {"msg": f"自动应答 = {center.auto_ack}"})
        return {"ok": True, "auto_ack": center.auto_ack}

    # ── 模拟 RTU ──────────────────────────────────────────

    @app.post("/api/rtu/start")
    async def rtu_start(payload: dict[str, Any] | None = None):
        global _rtu, _rtu_thread
        payload = payload or {}
        with _rtu_lock:
            if _rtu_thread and _rtu_thread.is_alive():
                return {"ok": False, "error": "模拟 RTU 已在运行"}
            _rtu = SimulatedRtu(
                host=payload.get("host", "127.0.0.1"),
                port=int(payload.get("port", center.port)),
                center_addr=int(str(payload.get("center_addr", "01")), 16),
                remote_addr=payload.get("remote_addr", "0010100001"),
                password=payload.get("password", "A000"),
                heartbeat_interval=float(payload.get("heartbeat", 30)),
                report_interval=float(payload.get("report", 60)),
                water_level=float(payload.get("water", 12.34)),
                rain=float(payload.get("rain", 1.5)),
                voltage=float(payload.get("voltage", 12.6)),
            )
            _rtu_thread = threading.Thread(target=_rtu.run, daemon=True)
            _rtu_thread.start()
        bus.emit("system", {"msg": f"模拟 RTU {_rtu.remote_addr} 已启动"})
        return {"ok": True}

    @app.post("/api/rtu/stop")
    async def rtu_stop():
        global _rtu, _rtu_thread
        with _rtu_lock:
            if _rtu:
                _rtu.close()
            _rtu = None
            _rtu_thread = None
        bus.emit("system", {"msg": "模拟 RTU 已停止"})
        return {"ok": True}

    @app.post("/api/rtu/send")
    async def rtu_send(payload: dict[str, Any]):
        with _rtu_lock:
            if not _rtu or not _rtu._connected:
                return JSONResponse({"ok": False, "error": "模拟 RTU 未连接"}, status_code=400)
            kind = payload.get("kind", "report")
            try:
                if kind == "heartbeat":
                    frame = _rtu.send_heartbeat()
                elif kind == "alarm":
                    frame = _rtu.send_report(0x33)
                elif kind == "hex":
                    frame = _rtu.send_hex(payload.get("hex", ""))
                else:
                    if "water" in payload:
                        _rtu.water_level = float(payload["water"])
                    if "rain" in payload:
                        _rtu.rain = float(payload["rain"])
                    if "voltage" in payload:
                        _rtu.voltage = float(payload["voltage"])
                    frame = _rtu.send_report(0x32)
                return {
                    "ok": True,
                    "hex": bytes_to_hex(frame) if frame else payload.get("hex", ""),
                }
            except Exception as e:
                return JSONResponse({"ok": False, "error": str(e)}, status_code=400)

    # ── WebSocket ─────────────────────────────────────────

    @app.websocket("/ws")
    async def ws_endpoint(websocket: WebSocket):
        await websocket.accept()
        loop = asyncio.get_running_loop()
        queue = asyncio.Queue()

        def on_event(event):
            try:
                loop.call_soon_threadsafe(queue.put_nowait, event)
            except Exception:
                pass

        unsub = bus.subscribe(on_event)
        try:
            await websocket.send_json(
                {
                    "type": "snapshot",
                    "data": {
                        "messages": bus.history(100),
                        "clients": center.list_clients(),
                        "status": {
                            "running": center.running,
                            "port": center.port,
                            "auto_ack": center.auto_ack,
                        },
                        "stats": store.stats(),
                    },
                }
            )
            while True:
                get_task = asyncio.create_task(queue.get())
                recv_task = asyncio.create_task(websocket.receive_text())
                done, pending = await asyncio.wait(
                    {get_task, recv_task}, return_when=asyncio.FIRST_COMPLETED
                )
                for t in pending:
                    t.cancel()
                if get_task in done:
                    await websocket.send_json(get_task.result())
                if recv_task in done:
                    try:
                        msg = recv_task.result()
                        if msg == "ping":
                            await websocket.send_json({"type": "pong"})
                    except Exception:
                        break
        except Exception:
            pass
        finally:
            unsub()

    return app


def run_web(
    host: str = "0.0.0.0",
    port: int = 8080,
    tcp_port: int = 9000,
    auto_ack: bool = True,
) -> None:
    import uvicorn

    hub.host = "0.0.0.0"
    hub.port = tcp_port
    hub.auto_ack = auto_ack
    hub.start(blocking=False)

    app = create_app(hub)
    print(f"[Web] http://127.0.0.1:{port}  |  RTU TCP :{tcp_port}")
    print(f"[DB]  {store.db_path}")
    try:
        uvicorn.run(app, host=host, port=port, log_level="info")
    finally:
        hub.stop()
        with _rtu_lock:
            if _rtu:
                _rtu.close()
