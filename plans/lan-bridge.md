# FVS Bridge: a small helper for other computers on the network

Status: built 2026-11-20 (not released). Code: `bridge/` (Go) and `studio/bridge.py`; how it works: `bridge/README.md`.
Changes from this plan: discovery by UDP broadcast only (no mDNS); downloaded files go to `Music\FVS Bridge`, not the
app's own Music folder (the app may be installed on that computer too); the inbox takes files up to 2 GB (videos to
transcribe).

## What it does

You install the bridge on another computer on the same network. It finds the PC running Fatima Voice Studio (or you
type its address once), and from then on that computer treats FVS as if it ran on it:

- **Web:** open `http://localhost:9830` there. That address works even after the router hands the host a new address.
- **MCP:** agents on that computer are set to `http://localhost:9830/mcp`, the same as on the host. The bridge adds
  the key itself, so nobody copies a key by hand.
- **Agents that only start programs:** `fvs-bridge mcp` (stdio), like `studio_mcp.py` on the host.
- **Files:** an agent there can pass a file from its own disk (a voice clip, a script, audio to transcribe) and gets
  the finished WAV/MP3/SRT back on its own disk. Today the MCP tools only take and return paths on the host.

## What the code already gives us

- `/v1/health` exists: the bridge can use it to check an address you type in by hand.
- The web page polls for updates instead of keeping a live connection (no EventSource or WebSocket), so a plain
  pass-through proxy is enough for the page.
- MCP runs with `stateless_http=True, json_response=True`: every tool call is one plain JSON request and one JSON
  reply. That makes it easy for the bridge to read and rewrite file paths in tool calls.
- Files can already be downloaded over the network: `GET /api/batches/{id}/files/{rel}` and `/export.zip`.
- The MCP security check (`mcp_server.py:169`) only accepts the host names `127.0.0.1:<port>` and
  `localhost:<port>`. The bridge sends `localhost`, so it passes. **Side finding:** this probably means an agent that
  talks to MCP on the host's network address directly (`http://192.168.x.x:9830/mcp`) is refused today. Test that
  first; it is a small fix either way.

## Part 1: FVS changes (Python, in this repo)

1. **Host ID.** Add a fixed `host_id` and a display name (the PC name by default) to the config. `/v1/health`
   returns them along with the version, so the bridge knows which PC it is talking to even after its address changes.
2. **Answer a broadcast (discovery).** While "Other computers" is on, FVS listens on UDP port 9830 and answers a
   bridge's broadcast `FVS?` with `{host_id, name, version, port}`. It answers local-network senders only (same
   `lan.is_lan` check as the web side). I chose this over mDNS: it needs no new library (python-zeroconf is LGPL)
   and works the same way on all three systems. The firewall rule from 0.4.5 also has to allow UDP 9830, which
   means one more line in the same UAC step.
3. **Pairing and device keys.**
   - `POST /api/bridge/pair` with the device's name returns a request ID. The host shows "*Laptop-Ali* wants to
     connect: Allow / Deny" on Settings → Other computers, plus a pop-up notice if the app is open.
   - When you allow it, the bridge collects its own key once. FVS stores only the hashed key (`devices` in the
     config) and compares keys in constant time.
   - `/mcp` and `/v1` accept the main API key **or** a device key. Settings → Other computers lists the paired
     devices, each with a Remove button.
   - The tunnel needs the same per-device keys, so this part covers that groundwork too.
   - The web page stays as it is today, with no login on the network. That was your decision, and the bridge
     doesn't change it.
4. **Inbox for files sent from other computers.** `POST /api/inbox` (one file of 50 MB at most, which is already
   the limit `read_file` uses) saves to `data/inbox/<random>/<name>` and returns that path. The inbox becomes one of
   the folders agents may read. Files older than 24 hours are deleted. This endpoint is a good candidate for
   accepting device keys only, rather than anyone on the network.
5. **A download link on Settings → Other computers** that points to the bridge installer for each system.

## Part 2: the bridge itself

1. **Local listener** on `127.0.0.1:9830`, or the next free port if FVS is also installed on that computer. It never
   listens on the network, so nobody can use it as a relay.
2. **Pass-through proxy** to the host. It rewrites the `Host` header, adds the device key to `/mcp` and `/v1`, and
   uses long time limits: `wait_for_batch` can take minutes, and on the network there is no 100-second cut-off like
   on the tunnel.
3. **Finding the host:**
   - When it starts and whenever the host can't be reached, it broadcasts `FVS?`, then tries the last known address.
   - It recognises the host by `host_id`, not by its address.
   - With two hosts on the network, you pick one. Manual address entry is always available.
4. **Its own small page** at `http://localhost:9830/_bridge`: status (linked to *PC name*, address, version), a list
   of hosts it found, a box to type an address, the pairing step, and Unlink. While it isn't linked, `/` opens this
   page.
5. **Tray icon** with Open studio, Bridge settings and Quit. It starts with the computer (on Windows through the
   current user's Run key, so no admin rights are needed).
6. **Files in MCP calls.** The bridge reads each JSON `tools/call` before passing it on.
   - **Files in:** for `add_voice(source)`, `create_batch(scripts[].file)` and `transcribe(source)`, if the value is
     a file on this computer, the bridge uploads it to the inbox and swaps in the host path. Links pass through
     unchanged.
   - **Files out:**
     - For `speak`, `wait_for_batch`, `get_batch`, `export_batch` and `transcribe`, the bridge downloads the finished
       files into a local folder and swaps in local paths. That folder is `Music\Fatima Voice Studio` by default;
       your call.
     - Single parts are only downloaded when asked for.
     - Files already downloaded are skipped (checked by size and time).
   - **Tool descriptions:** in `tools/list`, the bridge rewrites the sentence about "folders allowed on the Connect
     page" so agents know any local file works.
7. **stdio mode:** `fvs-bridge mcp` sends requests through the same code as `/mcp`, with the same file handling.

## Part 3: packaging

- Windows first: one exe and a per-user install (no admin). macOS and Linux builds come later from the same code.
- Its own release asset, like the Linux engines. Nothing is pushed or published without your go-ahead.
- The exe isn't code-signed, so Windows SmartScreen will show a "Windows protected your PC" warning the first time.

## Testing (on your second PC, in the real app)

- Discovery, pairing, Allow / Deny / Remove, and a removed device being refused afterwards.
- The web page through `localhost`: making a batch, playing audio, and the actions only the host may do still being
  refused.
- Claude Desktop and Claude Code on the second PC using `localhost:9830/mcp`: `speak`, a long batch with
  `wait_for_batch`, `add_voice` from a local clip, `transcribe` of a local file, and `export_batch` arriving on the
  local disk.
- The host getting a new address (change its DHCP lease), the host turned off and back on, FVS restarted, and a
  port clash on the second PC.
- Testing in several languages, not just Spanish.

## Decisions for you

1. **Language for the bridge.**
   - Go (recommended): a single ~8–10 MB exe, fast start, builds for all three systems. Go isn't installed here; the
     toolchain is about a 70 MB download.
   - Python + PyInstaller: nothing new to install, but the exe is about 25 MB and slower to start.
2. **Pairing.** Should approving each device on the host be required? I recommend yes: it is a single click per
   device and gives each device its own key that you can revoke.
3. **Where downloaded files go** on the other computer (default `Music\Fatima Voice Studio`).
4. **Which release.** Before or together with the tunnel. The device keys from Part 1 serve both, so they could go
   first.

## Rough size

Part 1 is small, roughly a day. Part 2 is the bulk: the proxy and discovery are quick, while the file handling in MCP
calls and the bridge page take the most time. Part 3 depends on the language choice.
