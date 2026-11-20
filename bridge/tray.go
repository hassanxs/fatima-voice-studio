//go:build windows || linux

package main

import (
	"os"
	"sync"

	"fyne.io/systray"
)

var (
	trayMu     sync.Mutex
	trayReady  bool
	trayStatus *systray.MenuItem
)

func runTray() {
	systray.Run(onTrayReady, func() {})
}

func onTrayReady() {
	systray.SetIcon(iconICO)
	systray.SetTitle("FVS Bridge")
	systray.SetTooltip("FVS Bridge")
	status := systray.AddMenuItem("Starting…", "")
	status.Disable()
	systray.AddSeparator()
	open := systray.AddMenuItem("Open Fatima Voice Studio", "Open the app in your browser")
	settings := systray.AddMenuItem("Bridge settings", "Connect, pair, folders, MCP")
	systray.AddSeparator()
	quitItem := systray.AddMenuItem("Quit", "Stop the bridge")
	systray.SetOnTapped(func() { openApp() })

	trayMu.Lock()
	trayStatus, trayReady = status, true
	trayMu.Unlock()
	trayRefresh()

	go func() {
		for {
			select {
			case <-open.ClickedCh:
				openApp()
			case <-settings.ClickedCh:
				openBrowser(localURL() + "_bridge")
			case <-quitItem.ClickedCh:
				systray.Quit()
				os.Exit(0)
			}
		}
	}()
}

// openApp opens the app itself when connected, else the bridge's page.
func openApp() {
	c := getConfig()
	if c.Key != "" && getState().Reachable {
		openBrowser(localURL())
		return
	}
	openBrowser(localURL() + "_bridge")
}

func trayRefresh() {
	trayMu.Lock()
	defer trayMu.Unlock()
	if !trayReady {
		return
	}
	text := trayText()
	trayStatus.SetTitle(text)
	systray.SetTooltip("FVS Bridge · " + text)
}

func quit() {
	trayMu.Lock()
	ready := trayReady
	trayMu.Unlock()
	if ready {
		systray.Quit()
	}
	os.Exit(0)
}
