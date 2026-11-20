# FVS Bridge

A small program for other computers on the same network as the PC that runs Fatima Voice Studio. On that computer
it serves the app at `http://localhost:9830` (web page and MCP at `/mcp`), so nobody there types the PC's address or
copies a key, and it keeps working after the PC's address changes. The PC's side is `studio/bridge.py`.

How to use it: [Settings → Other computers → The bridge](../studio/help/settings.md#the-bridge-for-computers-you-use-often).

## How it works

- **Finding the PC:** a UDP broadcast `{"fvs":"discover"}` to port 9830; the PC answers with its id, name, version and
  web port. The bridge remembers the PC by that id and looks for it again when its address changes. An address can
  also be typed in.
- **Pairing:** `POST /api/bridge/pair` on the PC; the person clicks Allow there (both show the same 4-digit code); the
  bridge collects its own key once. The PC keeps only a hash of it, and can remove the computer at any time.
- **Proxy:** everything on `localhost:<port>` goes to the PC. The bridge adds its key to `/v1` and `/mcp`, but only
  for requests from programs or its own page: requests with another website's `Origin`, or with a `Host` other than
  localhost (DNS rebinding), get no key.
- **Files in MCP calls:** for `add_voice`, `transcribe` and `create_batch`, a file on this computer is uploaded to
  the PC's inbox (`/api/bridge/host/inbox`), or mapped back to the PC's own file if it is a copy the bridge made.
  Paths in answers that point into the PC's batches, exports or transcripts folders are downloaded to
  `Downloads\Fatima Voice Studio` (`/api/bridge/host/stat`, `/api/bridge/host/file`) and replaced with the local paths.
- **Folders:** agents may pass files from `local_read_dirs` in `bridge.json` (default: Documents, Downloads,
  Desktop, Music) and from the copies the bridge made; `get_settings` reports these as `agents_may_read`. Other
  paths are refused.
- **Batches:** for `create_batch`, `get_batch` and `wait_for_batch` the bridge also brings back a finished batch's
  `batch.json`, and remembers the batch (`batches.json`). When such a batch folder is deleted here and the PC has
  finished the batch, the bridge deletes it on the PC (`DELETE /api/batches/<id>`, to the Recycle Bin), logs it,
  and never brings it back. `"sync_deletes": false` turns this off. Files arrive under a temporary name and are
  renamed when complete.
- **stdio:** `FVS-Bridge.exe mcp` does the same over stdin/stdout.
- **Installing (Windows):** a release build copies itself to `%LOCALAPPDATA%\Programs\FVS Bridge`, adds a Start menu
  entry, an entry in Settings → Apps (`--uninstall`) and starts with Windows. No admin rights. Running a newer
  download replaces the running copy. `--portable` (and every `dev` build) runs where it is.

Settings and the log: `%APPDATA%\FVS Bridge`.

## Building

```powershell
powershell -ExecutionPolicy Bypass -File bridge\build.ps1
```

Needs Go 1.24 or newer. Writes `bridge\dist\FVS-Bridge.exe` with the app's version and icon; a copy of the app run
from source serves it from there at `/bridge/download`. `packaging\build.ps1` builds it into the installer.

For a quick test copy: `go build -o test\FVS-Bridge.exe .` in this folder, then run it with
`--portable --no-browser` (add `--no-tray` for no tray icon).

It also builds for Linux (with the tray icon) and macOS (without one), but only Windows is tested so far.
