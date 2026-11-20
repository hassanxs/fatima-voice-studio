"""The bridge: a small helper (bridge/ in this repo, FVS-Bridge.exe) for other computers on the network.

On the other computer it serves this app at http://localhost:<port>, for the browser and for AI agents (MCP), so
nobody there types this PC's address or copies a key. This module is the host's side of it:

  * discovery: while "Other computers" is on, a bridge's broadcast on UDP DISCOVERY_PORT gets this PC's id, name
    and port back (local-network senders only, like everything else);
  * pairing: a bridge asks to connect, the person clicks Allow on this PC, and the bridge collects its own key once.
    Only a hash of each key is kept (config "devices"); a key is removed with its device;
  * files: a paired bridge uploads the files an agent passes (voice clips, scripts, audio to transcribe) to an
    inbox the MCP tools may read, and downloads the finished audio, subtitles and transcripts.
"""
import datetime as dt
import hashlib
import hmac
import json
import logging
import secrets
import shutil
import socket
import threading
import time
from pathlib import Path

from . import APP_NAME, __version__, config, lan

log = logging.getLogger(__name__)

DISCOVERY_PORT = lan.DISCOVERY_PORT
PAIR_TTL = 600                 # a pairing request waits this long for Allow / Deny
INBOX_TTL = 24 * 3600          # uploaded files are deleted after a day
INBOX_MAX = 2 * 1024 ** 3      # videos to transcribe can be large (voice clips and scripts: 50 MB, mcp_server.py)
DOWNLOAD_NAME = "FVS-Bridge.exe"


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def identity(cfg: dict) -> dict:
    """This PC as a bridge sees it. The id stays the same when the router hands out a new address."""
    if not cfg.get("host_id"):
        cfg["host_id"] = secrets.token_hex(8)
        config.save(cfg)
    return {"host_id": cfg["host_id"], "name": socket.gethostname(), "version": __version__}


def download_file() -> Path | None:
    """The bridge installer other computers download from this app: studio/bin in a release (the release workflow
    builds it there, so the installer and quick updates carry it with the app's files), or bridge/dist when run
    from source (bridge/build.ps1)."""
    for p in (config.ROOT / "studio" / "bin" / DOWNLOAD_NAME, config.ROOT / "bridge" / DOWNLOAD_NAME,
              config.ROOT / "bridge" / "dist" / DOWNLOAD_NAME):
        if p.is_file():
            return p
    return None


class Devices:
    """Paired bridges and the pairing requests waiting for Allow / Deny on this PC."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.pending: dict[str, dict] = {}
        self.lock = threading.Lock()
        self._seen_saved = 0.0

    @property
    def devices(self) -> list[dict]:
        return self.cfg.setdefault("devices", [])

    def _expire(self) -> None:
        cut = time.time() - PAIR_TTL
        for rid in [r for r, p in self.pending.items() if p["t"] < cut]:
            del self.pending[rid]

    def request(self, name: str, ip: str | None) -> dict:
        """A bridge asks to connect. The request id is its secret: only it can collect the key."""
        name = " ".join(str(name or "").split())[:60] or "Another computer"
        with self.lock:
            self._expire()
            for rid in [r for r, p in self.pending.items() if p["ip"] == ip]:  # asking again replaces the old one
                del self.pending[rid]
            if len(self.pending) >= 5:
                raise ValueError("Too many computers are waiting to connect. Try again in a few minutes.")
            rid = secrets.token_urlsafe(24)
            code = f"{secrets.randbelow(10000):04d}"
            self.pending[rid] = {"id": secrets.token_hex(4), "name": name, "ip": ip, "code": code, "t": time.time(),
                                 "status": "pending", "key": None, "device": None}
        log.info("Bridge pairing asked by %s (%s)", name, ip)
        return {"request": rid, "code": code}

    def waiting(self) -> list[dict]:
        """What the person on this PC is asked about."""
        with self.lock:
            self._expire()
            return [{"id": p["id"], "name": p["name"], "ip": p["ip"], "code": p["code"]}
                    for p in self.pending.values() if p["status"] == "pending"]

    def _by_short_id(self, short: str) -> dict | None:
        return next((p for p in self.pending.values() if p["id"] == short and p["status"] == "pending"), None)

    def answer(self, short: str, allow: bool) -> dict:
        with self.lock:
            p = self._by_short_id(short)
            if not p:
                raise KeyError(short)
            if not allow:
                p["status"] = "denied"
                log.info("Bridge pairing denied: %s (%s)", p["name"], p["ip"])
                return {"status": "denied"}
            key = "fvsb-" + secrets.token_urlsafe(32)
            dev = {"id": secrets.token_hex(6), "name": p["name"], "ip": p["ip"], "key_hash": _hash(key),
                   "added": _now(), "last_seen": _now()}
            self.devices.append(dev)
            config.save(self.cfg)
            p.update(status="allowed", key=key, device=dev["id"])
        log.info("Bridge paired: %s (%s)", dev["name"], dev["ip"])
        return {"status": "allowed", "device": self.view(dev)}

    def collect(self, rid: str) -> dict:
        """The bridge polls its request; the key is handed over once, then forgotten."""
        with self.lock:
            self._expire()
            p = self.pending.get(rid)
            if not p:
                return {"status": "expired"}
            out = {"status": p["status"]}
            if p["status"] == "allowed":
                out |= {"key": p["key"], "device": p["device"]}
                del self.pending[rid]
            elif p["status"] == "denied":
                del self.pending[rid]
            return out

    def cancel(self, rid: str) -> bool:
        """The bridge withdrew its request (Cancel there): stop asking on this PC."""
        with self.lock:
            return self.pending.pop(rid, None) is not None

    def check(self, key: str | None, ip: str | None = None) -> dict | None:
        """The device this key belongs to, or None. Compares every hash in constant time."""
        if not key or not key.startswith("fvsb-"):
            return None
        h = _hash(key)
        hit = None
        for d in self.devices:
            if hmac.compare_digest(d.get("key_hash", ""), h):
                hit = d
        if hit:
            hit["last_seen"] = _now()
            if ip:
                hit["ip"] = ip
            if time.monotonic() - self._seen_saved > 300:  # don't write the config on every request
                self._seen_saved = time.monotonic()
                config.save(self.cfg)
        return hit

    def remove(self, device_id: str) -> bool:
        before = len(self.devices)
        self.cfg["devices"] = [d for d in self.devices if d["id"] != device_id]
        if len(self.cfg["devices"]) == before:
            return False
        config.save(self.cfg)
        log.info("Bridge removed: %s", device_id)
        return True

    @staticmethod
    def view(d: dict) -> dict:
        return {k: d.get(k) for k in ("id", "name", "ip", "added", "last_seen")}

    def list(self) -> list[dict]:
        return [self.view(d) for d in self.devices]


class Discovery:
    """Answers a bridge's broadcast `{"fvs": "discover"}` with this PC's id, name, version and web port."""

    def __init__(self, cfg: dict, port: int):
        self.cfg, self.port = cfg, port
        self.sock: socket.socket | None = None

    def start(self) -> None:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("", DISCOVERY_PORT))
        except OSError as e:
            log.warning("Bridge discovery not available (UDP %s: %s); bridges can still connect by address",
                        DISCOVERY_PORT, e)
            return
        self.sock = s
        threading.Thread(target=self._run, name="bridge-discovery", daemon=True).start()

    def stop(self) -> None:
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None

    def _run(self) -> None:
        s = self.sock
        while self.sock is s:
            try:
                data, addr = s.recvfrom(1024)
            except OSError:
                return
            if not (self.cfg.get("lan") and (lan.is_lan(addr[0]) or lan.is_this_pc(addr[0]))):
                continue
            try:
                msg = json.loads(data)
                if not isinstance(msg, dict) or msg.get("fvs") != "discover":
                    continue
            except ValueError:
                continue
            reply = {"fvs": "here", "v": 1, "app": APP_NAME, "port": self.port} | identity(self.cfg)
            try:
                s.sendto(json.dumps(reply).encode(), addr)
            except OSError:
                pass


class Inbox:
    """Files a bridge uploads for the MCP tools to read; each in its own folder, removed after a day."""

    def __init__(self, root: Path = config.DATA / "inbox"):
        self.root = root

    def clean(self) -> None:
        if not self.root.exists():
            return
        cut = time.time() - INBOX_TTL
        for d in self.root.iterdir():
            try:
                if d.stat().st_mtime < cut:
                    shutil.rmtree(d, ignore_errors=True) if d.is_dir() else d.unlink()
            except OSError:
                pass

    def folder(self) -> Path:
        self.clean()
        d = self.root / secrets.token_hex(8)
        d.mkdir(parents=True, exist_ok=True)
        return d

    @staticmethod
    def safe_name(name: str) -> str:
        name = Path(str(name or "").replace("\\", "/")).name
        name = "".join(c for c in name if c not in '<>:"/\\|?*' and ord(c) >= 32).strip(" .")
        return name[:120] or "file"


def inside(path: Path, roots: list[Path]) -> bool:
    try:
        real = path.resolve()
    except OSError:
        return False
    for r in roots:
        try:
            r = r.resolve()
        except OSError:
            continue
        if real == r or r in real.parents:
            return True
    return False


def stat(path: Path, roots: list[Path], limit: int = 2000) -> dict:
    """What a bridge needs to mirror a file or folder: sizes and times (a folder lists its files)."""
    out = {"path": str(path)}
    if not inside(path, roots) or not path.exists():
        return out | {"kind": "missing"}
    if path.is_file():
        st = path.stat()
        return out | {"kind": "file", "size": st.st_size, "mtime": st.st_mtime}
    files = []
    for f in sorted(path.rglob("*")):
        if f.is_file() and inside(f, roots):
            st = f.stat()
            files.append({"path": str(f), "size": st.st_size, "mtime": st.st_mtime})
            if len(files) >= limit:
                break
    return out | {"kind": "dir", "files": files}
