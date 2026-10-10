#!/bin/sh
# Runs "$@", killing it if the process whose PID is $FVS_WATCH_PPID disappears. macOS has no pdeathsig (the
# kernel feature linux/compat.py uses via setpriv), so this polls instead. "exec" below replaces this shell
# with the wrapped command, keeping the same PID, so the app's subprocess.Popen still sees the real process.
ppid="$FVS_WATCH_PPID"
mypid="$$"
# >/dev/null 2>&1 closes the watcher's own copies of stdout/stderr: without it, forking inherits the wrapped
# command's piped stdout/stderr, and the watcher holds that pipe open for as long as $ppid lives -- the real
# process can exit, but a caller reading via subprocess.PIPE (engine.py's pump thread) never sees EOF and hangs.
# The loop also stops as soon as the wrapped command itself (mypid, captured before "exec" replaces this shell
# with it) is gone, and the final kill only fires if mypid is still alive -- without this, a quick command
# (engine.py starts llama-tts once per ~40s segment) left its watcher polling for the rest of the app's life,
# and it would eventually kill -9 whatever pid the kernel had since reused.
( while kill -0 "$ppid" 2>/dev/null && kill -0 "$mypid" 2>/dev/null; do sleep 1; done
  kill -0 "$mypid" 2>/dev/null && kill -9 "$mypid" 2>/dev/null
) >/dev/null 2>&1 &
exec "$@"
