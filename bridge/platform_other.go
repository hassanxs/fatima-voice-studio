//go:build !windows

package main

import (
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
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

// downloadsDir is the user's Downloads folder (XDG_DOWNLOAD_DIR when set).
func downloadsDir() string {
	if d := os.Getenv("XDG_DOWNLOAD_DIR"); d != "" {
		return d
	}
	if home, err := os.UserHomeDir(); err == nil {
		return filepath.Join(home, "Downloads")
	}
	return ""
}

// userDirs are the user's own folders: Documents, Downloads, Desktop and Music.
func userDirs() []string {
	home, err := os.UserHomeDir()
	if err != nil {
		return nil
	}
	out := []string{filepath.Join(home, "Documents"), downloadsDir(), filepath.Join(home, "Desktop"),
		filepath.Join(home, "Music")}
	return out
}

func fatal(text string) { fmt.Fprintln(os.Stderr, text) }

func autostartSupported() bool { return false }

func autostartEnabled() bool { return false }

func setAutostart(on bool) error {
	return errors.New("starting with the computer isn't available here yet")
}

func installOnce(extra ...string) bool { return false }

func needsInstall() (installing, updating bool) { return false, false }

func showProgress(heading, detail string) {}

func setProgress(heading, detail string) {}

func closeProgress() {}

func portable() bool { return true }

func uninstall() {
	forgetOnHost()
	_ = os.RemoveAll(configDir())
	fmt.Println("FVS Bridge forgot its settings. Delete the program file to remove it.")
}
