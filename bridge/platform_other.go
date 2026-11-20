//go:build !windows

package main

import (
	"errors"
	"fmt"
	"os"
	"os/exec"
	"runtime"
)

// macOS and Linux: the bridge runs as it is (no installing, no start-at-login yet).

func openBrowser(u string) { openPath(u) }

func openPath(p string) {
	name := "xdg-open"
	if runtime.GOOS == "darwin" {
		name = "open"
	}
	_ = exec.Command(name, p).Start()
}

func fatal(text string) { fmt.Fprintln(os.Stderr, text) }

func autostartSupported() bool { return false }

func autostartEnabled() bool { return false }

func setAutostart(on bool) error {
	return errors.New("starting with the computer isn't available here yet")
}

func installOnce() bool { return false }

func portable() bool { return true }

func uninstall() {
	forgetOnHost()
	_ = os.RemoveAll(configDir())
	fmt.Println("FVS Bridge forgot its settings. Delete the program file to remove it.")
}
