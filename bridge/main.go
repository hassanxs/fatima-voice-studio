// FVS Bridge: use Fatima Voice Studio from another computer on the same network as if it ran there.
//
//	FVS-Bridge                 the bridge: http://localhost:9830 on this computer (web page and /mcp), tray icon
//	FVS-Bridge mcp             MCP over stdin/stdout, for agents that only start programs
//	FVS-Bridge --no-tray       the bridge without a tray icon (no window at all)
//	FVS-Bridge --no-browser    don't open the bridge's page on start
//	FVS-Bridge --portable      run from where it is (don't install itself)
//	FVS-Bridge --uninstall     remove it from this computer (Windows: also Settings → Apps)
//
// It finds the Fatima Voice Studio PC on the network (or takes its address), asks it to pair (the person clicks
// Allow on that PC), and from then on forwards everything to it, with this computer's own key. Files agents
// pass are sent over, and the finished audio comes back. See studio/bridge.py for the PC's side.
package main

import (
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"time"
)

var version = "dev" // set by build.ps1

// build tells two builds of the same version apart (set by build.ps1), so a newer download always replaces the
// running bridge, even before the version number changes.
var build = ""

func main() {
	args := os.Args[1:]
	mode := ""
	noTray, noBrowser := false, false
	for _, a := range args {
		switch a {
		case "mcp":
			mode = "mcp"
		case "--no-tray":
			noTray = true
		case "--no-browser":
			noBrowser = true
		case "--uninstall":
			mode = "uninstall"
		case "--version", "-v":
			fmt.Println("FVS Bridge", version)
			return
		}
	}
	loadConfig()
	setupLog(mode)

	switch mode {
	case "mcp":
		runStdio()
		return
	case "uninstall":
		uninstall()
		return
	}

	// started again while running: just open the page, unless this is a newer download (stop the old one, install)
	running, runningVersion, runningBuild := alreadyRunning()
	if running && (portable() || (runningVersion == version && runningBuild == build)) {
		if !noBrowser {
			openBrowser(fmt.Sprintf("http://localhost:%d/_bridge", getConfig().ListenPort))
		}
		return
	}
	// a download being installed: say so in a small window until the installed copy is up
	installing, updating := needsInstall()
	if installing {
		if updating {
			showProgress("Updating FVS Bridge", "Replacing the installed copy. Your connection and settings are kept.")
		} else {
			showProgress("Installing FVS Bridge", "Setting it up for this user. No admin rights needed.")
		}
	}
	if running {
		askQuit()
		for i := 0; i < 30; i++ { // until it has stopped (up to 6 s)
			time.Sleep(200 * time.Millisecond)
			if r, _, _ := alreadyRunning(); !r {
				break
			}
		}
	}
	done := "installed"
	if updating {
		done = "updated"
	}
	if moved := installOnce("--done=" + done); moved {
		// the installed copy takes over: keep the window until it answers
		for i := 0; i < 50; i++ {
			time.Sleep(200 * time.Millisecond)
			loadConfig() // it may have taken another port and saved that
			if r, v, b := alreadyRunning(); r && v == version && b == build {
				break
			}
		}
		if updating {
			setProgress("FVS Bridge is updated", "Version "+versionText()+". Opening its page…")
		} else {
			setProgress("FVS Bridge is installed", "Find it in Start as Fatima Voice Studio Bridge. Opening its page…")
		}
		time.Sleep(1500 * time.Millisecond)
		closeProgress()
		return
	}
	closeProgress()
	l, err := listen()
	if err != nil {
		log.Printf("can't listen: %v", err)
		fatal("FVS Bridge can't start: no free port near " + fmt.Sprint(getConfig().ListenPort) + ".")
		return
	}
	log.Printf("FVS Bridge %s on %s", version, localURL())
	go func() {
		if err := serve(l); err != nil {
			log.Printf("server: %v", err)
			os.Exit(1)
		}
	}()
	go watch()
	go syncDeletes()
	go func() { // just installed or updated, or not paired yet: show the page
		c := getConfig()
		if noBrowser {
			return
		}
		page := ""
		if d := argValue("--done="); d == "installed" || d == "updated" {
			page = "_bridge?done=" + d
		} else if c.Key == "" {
			page = "_bridge"
		}
		if page != "" {
			time.Sleep(300 * time.Millisecond)
			openBrowser(localURL() + page)
		}
	}()
	if noTray {
		select {}
	}
	runTray()
}

func setupLog(mode string) {
	if mode == "uninstall" { // its folder is about to be removed: an open log file would stay behind
		log.SetOutput(io.Discard)
		return
	}
	_ = os.MkdirAll(configDir(), 0o700)
	name := "bridge.log"
	if mode == "mcp" {
		name = "bridge-mcp.log"
	}
	p := filepath.Join(configDir(), name)
	if fi, err := os.Stat(p); err == nil && fi.Size() > 2<<20 {
		_ = os.Rename(p, p+".old")
	}
	f, err := os.OpenFile(p, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o600)
	if err != nil {
		return
	}
	if mode == "mcp" {
		log.SetOutput(f) // stdout is the MCP channel: never log there
	} else {
		log.SetOutput(io.MultiWriter(f, os.Stderr))
	}
	log.SetFlags(log.LstdFlags)
}

// alreadyRunning: is a bridge answering on our port, and which version and build?
func alreadyRunning() (bool, string, string) {
	c := &http.Client{Timeout: 1500 * time.Millisecond}
	resp, err := c.Get(fmt.Sprintf("http://127.0.0.1:%d/_bridge/api/status", getConfig().ListenPort))
	if err != nil {
		return false, "", ""
	}
	defer resp.Body.Close()
	var s struct {
		App     string `json:"app"`
		Version string `json:"version"`
		Build   string `json:"build"`
	}
	ok := json.NewDecoder(resp.Body).Decode(&s) == nil && s.App == "fvs-bridge"
	return ok, s.Version, s.Build
}

// askQuit stops the bridge that is running (to update or remove it).
func askQuit() {
	c := &http.Client{Timeout: 3 * time.Second}
	req, err := http.NewRequest("POST", fmt.Sprintf("http://127.0.0.1:%d/_bridge/api/quit", getConfig().ListenPort), nil)
	if err != nil {
		return
	}
	req.Header.Set("X-Bridge", "1")
	if resp, err := c.Do(req); err == nil {
		resp.Body.Close()
	}
}

// argValue returns the value of an argument like --done=updated ("" when it isn't given).
func argValue(prefix string) string {
	for _, a := range os.Args[1:] {
		if len(a) > len(prefix) && a[:len(prefix)] == prefix {
			return a[len(prefix):]
		}
	}
	return ""
}

// versionText is the version for people: "0.4.5 (20 Nov 2026)".
func versionText() string {
	if t, err := time.Parse("20060102150405", build); err == nil {
		return fmt.Sprintf("%s (%s)", version, t.Format("2 Jan 2006 15:04"))
	}
	return version
}

func hasArg(name string) bool {
	for _, a := range os.Args[1:] {
		if a == name {
			return true
		}
	}
	return false
}
