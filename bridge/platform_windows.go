//go:build windows

package main

import (
	"errors"
	"fmt"
	"io"
	"log"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"
	"time"
	"unsafe"

	"golang.org/x/sys/windows"
	"golang.org/x/sys/windows/registry"
)

const (
	runKey       = `Software\Microsoft\Windows\CurrentVersion\Run`
	runValue     = "FVS Bridge"
	uninstallKey = `Software\Microsoft\Windows\CurrentVersion\Uninstall\FVSBridge`
	exeName      = "FVS-Bridge.exe"
)

var noWindow = &syscall.SysProcAttr{HideWindow: true, CreationFlags: 0x08000000} // CREATE_NO_WINDOW

func installDir() string {
	base := os.Getenv("LOCALAPPDATA")
	if base == "" {
		base = configDir()
	}
	return filepath.Join(base, "Programs", "FVS Bridge")
}

// downloadsDir is the user's Downloads folder, wherever it really is (it may be moved to another drive).
func downloadsDir() string {
	if d, err := windows.KnownFolderPath(windows.FOLDERID_Downloads, 0); err == nil && d != "" {
		return d
	}
	if home, err := os.UserHomeDir(); err == nil {
		return filepath.Join(home, "Downloads")
	}
	return ""
}

func startMenuLink() string {
	return filepath.Join(os.Getenv("APPDATA"), `Microsoft\Windows\Start Menu\Programs`, "FVS Bridge.lnk")
}

func openBrowser(u string) {
	_ = exec.Command("rundll32", "url.dll,FileProtocolHandler", u).Start()
}

func openPath(p string) {
	_ = exec.Command("explorer", p).Start()
}

func messageBox(text string, icon uint32) {
	user32 := windows.NewLazySystemDLL("user32.dll")
	t, _ := windows.UTF16PtrFromString(text)
	c, _ := windows.UTF16PtrFromString("FVS Bridge")
	_, _, _ = user32.NewProc("MessageBoxW").Call(0, uintptr(unsafe.Pointer(t)), uintptr(unsafe.Pointer(c)), uintptr(icon))
}

func fatal(text string) { messageBox(text, 0x10) }

func autostartSupported() bool { return true }

func autostartEnabled() bool {
	k, err := registry.OpenKey(registry.CURRENT_USER, runKey, registry.QUERY_VALUE)
	if err != nil {
		return false
	}
	defer k.Close()
	_, _, err = k.GetStringValue(runValue)
	return err == nil
}

func setAutostart(on bool) error {
	k, _, err := registry.CreateKey(registry.CURRENT_USER, runKey, registry.SET_VALUE)
	if err != nil {
		return err
	}
	defer k.Close()
	if !on {
		if err := k.DeleteValue(runValue); err != nil && !errors.Is(err, registry.ErrNotExist) {
			return err
		}
		return nil
	}
	return k.SetStringValue(runValue, `"`+exePath()+`"`)
}

func portable() bool { return hasArg("--portable") || version == "dev" }

// installOnce copies the bridge to %LOCALAPPDATA%\Programs\FVS Bridge (no admin rights needed), adds it to the
// Start menu, to Settings → Apps (for removing it) and to the programs that start with Windows, then starts that
// copy. Running a newer download does the same, which updates it. Returns true when the installed copy took over.
func installOnce() bool {
	if portable() {
		return false
	}
	dir := installDir()
	target := filepath.Join(dir, exeName)
	self := exePath()
	if strings.EqualFold(filepath.Clean(self), filepath.Clean(target)) {
		_ = os.Remove(target + ".old") // the copy an update moved out of the way
		if !getConfig().Installed {    // installed by an older copy, or the settings were removed
			finishInstall(target)
		}
		return false
	}
	if err := os.MkdirAll(dir, 0o755); err != nil {
		log.Printf("install: %v", err)
		return false
	}
	if err := copyFile(self, target); err != nil {
		log.Printf("install: %v", err)
		fatal("FVS Bridge couldn't install itself: " + err.Error())
		return false
	}
	finishInstall(target)
	cmd := exec.Command(target, os.Args[1:]...) // e.g. --no-browser
	cmd.Dir = dir
	if err := cmd.Start(); err != nil {
		log.Printf("start installed copy: %v", err)
		return false
	}
	return true
}

func finishInstall(target string) {
	k, _, err := registry.CreateKey(registry.CURRENT_USER, runKey, registry.SET_VALUE)
	if err == nil {
		_ = k.SetStringValue(runValue, `"`+target+`"`)
		k.Close()
	}
	if k, _, err := registry.CreateKey(registry.CURRENT_USER, uninstallKey, registry.SET_VALUE); err == nil {
		_ = k.SetStringValue("DisplayName", "FVS Bridge (Fatima Voice Studio)")
		_ = k.SetStringValue("DisplayVersion", version)
		_ = k.SetStringValue("Publisher", "Fatima Voice Studio")
		_ = k.SetStringValue("DisplayIcon", target)
		_ = k.SetStringValue("InstallLocation", filepath.Dir(target))
		_ = k.SetStringValue("UninstallString", `"`+target+`" --uninstall`)
		_ = k.SetDWordValue("NoModify", 1)
		_ = k.SetDWordValue("NoRepair", 1)
		_ = k.SetDWordValue("EstimatedSize", 12*1024)
		k.Close()
	}
	ps := fmt.Sprintf(`$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%s'); $s.TargetPath='%s'; `+
		`$s.WorkingDirectory='%s'; $s.Description='Use Fatima Voice Studio from this computer'; $s.Save()`,
		psQuote(startMenuLink()), psQuote(target), psQuote(filepath.Dir(target)))
	cmd := exec.Command("powershell", "-NoProfile", "-NonInteractive", "-Command", ps)
	cmd.SysProcAttr = noWindow
	if err := cmd.Run(); err != nil {
		log.Printf("Start menu shortcut: %v", err)
	}
	_ = updateConfig(func(c *Config) { c.Installed = true })
}

func psQuote(s string) string { return strings.ReplaceAll(s, "'", "''") }

func copyFile(src, dst string) error {
	in, err := os.Open(src)
	if err != nil {
		return err
	}
	defer in.Close()
	tmp := dst + ".new"
	out, err := os.Create(tmp)
	if err != nil {
		return err
	}
	if _, err := io.Copy(out, in); err != nil {
		out.Close()
		os.Remove(tmp)
		return err
	}
	out.Close()
	// a running copy can't be overwritten, but it can be renamed out of the way
	if _, err := os.Stat(dst); err == nil {
		old := dst + ".old"
		_ = os.Remove(old)
		if err := os.Rename(dst, old); err != nil {
			os.Remove(tmp)
			return errors.New("FVS Bridge is still running: quit it from its tray icon, then try again")
		}
	}
	return os.Rename(tmp, dst)
}

// uninstall removes the bridge from this computer: it tells the PC to forget this computer, stops the running
// bridge, and removes the Start menu entry, the start-with-Windows entry, its settings and the program itself.
// The audio files it brought over stay.
func uninstall() {
	forgetOnHost()
	if running, _ := alreadyRunning(); running {
		askQuit()
		time.Sleep(800 * time.Millisecond)
	}
	_ = setAutostart(false)
	_ = registry.DeleteKey(registry.CURRENT_USER, uninstallKey)
	_ = os.Remove(startMenuLink())
	files := getConfig().FilesDir
	_ = os.RemoveAll(configDir())
	if !hasArg("--quiet") {
		messageBox("FVS Bridge was removed from this computer.\n\nThe audio it brought over is still in "+files+".", 0x40)
	}
	// the program can't delete itself while running: a hidden cmd does it a moment after we exit
	dir := installDir()
	if strings.EqualFold(filepath.Dir(exePath()), dir) {
		// a raw command line: cmd doesn't understand the \" quoting Go would use for the path
		line := `cmd /c ping -n 3 127.0.0.1 >nul & rmdir /s /q "` + dir + `"`
		cmd := exec.Command("cmd")
		// its own process, outside any job of whatever started the uninstall, so it outlives us
		cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CmdLine: line,
			CreationFlags: 0x08000000 | 0x01000000 | 0x00000200}
		if err := cmd.Start(); err != nil {
			cmd = exec.Command("cmd")
			cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CmdLine: line, CreationFlags: 0x08000000}
			_ = cmd.Start()
		}
	} else {
		_ = os.RemoveAll(dir)
	}
}
