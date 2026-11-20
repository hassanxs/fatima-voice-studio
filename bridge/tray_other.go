//go:build !windows && !linux

package main

import "os"

// macOS: no tray icon yet (it would need cgo); the bridge runs in the background and its page is the way in.

func runTray() { select {} }

func trayRefresh() {}

func quit() { os.Exit(0) }
