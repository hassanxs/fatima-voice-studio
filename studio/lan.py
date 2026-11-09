"""Use from other computers on the local network (LAN).

With the switch on, the server listens on every network card instead of only 127.0.0.1. It still answers only
this PC and devices with a local-network address (192.168.x.x, 10.x.x.x, 172.16-31.x.x, fe80::, fd00::/8), so a
request from the internet is refused even if the router forwards the port. No login: anyone on the network can
make voiceovers, but things that change this PC (settings, folders, downloads, updates) stay on this PC.
"""
import ipaddress
import logging
import socket
import subprocess
import sys
import time

log = logging.getLogger(__name__)

RULE = "Fatima Voice Studio (local network)"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _ip(host: str | None):
    try:
        ip = ipaddress.ip_address((host or "").split("%")[0])
    except ValueError:
        return None
    return ip.ipv4_mapped or ip if ip.version == 6 else ip


def is_this_pc(host: str | None) -> bool:
    ip = _ip(host)
    return ip is None or ip.is_loopback  # no address at all: an in-process call (tests, MCP)


def is_lan(host: str | None) -> bool:
    """A local-network address: private ranges and link-local, but not the internet or carrier-grade NAT."""
    ip = _ip(host)
    if ip is None:
        return False
    if ip.version == 4:
        return any(ip in ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
                                                           "169.254.0.0/16"))
    return ip.is_link_local or ip in ipaddress.ip_network("fc00::/7")


def addresses() -> list[str]:
    """This PC's local-network IPv4 addresses, the one with the default route first."""
    try:  # the address Windows would use to reach the internet (connect() on UDP sends nothing)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))
            main = s.getsockname()[0]
        if is_lan(main) and not main.startswith("169.254."):
            return [main]  # the others are usually virtual cards (WSL, Hyper-V, VPNs) other devices can't reach
    except OSError:
        pass
    found = []
    try:
        found += [a[4][0] for a in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)]
    except OSError:
        pass
    return [a for a in dict.fromkeys(found) if is_lan(a) and not a.startswith("169.254.")]


_cache: dict = {}


def _cached(key: str, ttl: float, fn):
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < ttl:
        return hit[1]
    value = fn()
    _cache[key] = (time.monotonic(), value)
    return value


def _ps(command: str) -> str:
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
                       capture_output=True, text=True, timeout=15, creationflags=NO_WINDOW)
    return r.stdout.strip()


def public_networks() -> list[str]:
    """Names of connected networks Windows treats as Public: its firewall blocks other devices there."""
    if sys.platform != "win32":
        return []

    def read():
        try:
            out = _ps("Get-NetConnectionProfile | Where-Object NetworkCategory -eq 'Public' | "
                      "ForEach-Object { $_.Name }")
        except (OSError, subprocess.SubprocessError):
            return []
        return [line.strip() for line in out.splitlines() if line.strip()]
    return _cached("public", 30, read)


def firewall_rule(port: int) -> bool | None:
    """Whether Windows Firewall lets other devices in on this port (None: not Windows, or can't tell)."""
    if sys.platform != "win32":
        return None

    def read():
        try:
            out = _ps(f"$r = Get-NetFirewallRule -DisplayName '{RULE}' -ErrorAction SilentlyContinue | "
                      "Where-Object { $_.Enabled -eq 'True' }; "
                      "if ($r) { ($r | Get-NetFirewallPortFilter).LocalPort } else { 'none' }")
        except (OSError, subprocess.SubprocessError):
            return None
        return out != "none" and str(port) in out.split()
    return _cached(f"rule:{port}", 10, read)


def add_firewall_rule(port: int) -> bool:
    """Ask Windows (one admin prompt on this PC) to let local-network devices reach this port. False if refused."""
    if sys.platform != "win32":
        return False
    import ctypes
    _cache.clear()
    netsh = (f'advfirewall firewall delete rule name="{RULE}" & netsh advfirewall firewall add rule name="{RULE}" '
             f'dir=in action=allow protocol=TCP localport={port} remoteip=localsubnet profile=private,domain')
    # through cmd, so both netsh commands run under the one prompt
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", "cmd.exe", f"/c netsh {netsh}", None, 0)
    if rc <= 32:  # the person said No, or Windows refused
        log.info("Firewall rule not added (ShellExecute %s)", rc)
        return False
    for _ in range(40):  # the prompt returns at once; wait for netsh to finish
        time.sleep(0.25)
        _cache.clear()
        if firewall_rule(port):
            return True
    return False
