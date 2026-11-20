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
	if running, runningVersion := alreadyRunning(); running {
		if portable() || runningVersion == version {
			if !noBrowser {
				openBrowser(fmt.Sprintf("http://localhost:%d/_bridge", getConfig().ListenPort))
			}
			return
		}
		askQuit()
		time.Sleep(1200 * time.Millisecond)
	}
	if moved := installOnce(); moved {
		return // the installed copy took over
	}
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
	go func() { // first run, or not paired yet: show the page where that's done
		c := getConfig()
		if c.Key == "" && !noBrowser {
			time.Sleep(300 * time.Millisecond)
			openBrowser(localURL() + "_bridge")
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

// alreadyRunning: is a bridge answering on our port, and which version?
func alreadyRunning() (bool, string) {
	c := &http.Client{Timeout: 1500 * time.Millisecond}
	resp, err := c.Get(fmt.Sprintf("http://127.0.0.1:%d/_bridge/api/status", getConfig().ListenPort))
	if err != nil {
		return false, ""
	}
	defer resp.Body.Close()
	var s struct {
		App     string `json:"app"`
		Version string `json:"version"`
	}
	ok := json.NewDecoder(resp.Body).Decode(&s) == nil && s.App == "fvs-bridge"
	return ok, s.Version
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

func hasArg(name string) bool {
	for _, a := range os.Args[1:] {
		if a == name {
			return true
		}
	}
	return false
}
