//go:build windows

package main

import (
	"runtime"
	"sync"
	"time"
	"unsafe"

	"golang.org/x/sys/windows"
)

// A small window that says what the bridge is doing while it installs or updates itself: a heading, a line of
// detail and a moving progress bar. Plain Win32, so it needs nothing else; the look (and the moving bar) comes from
// the common controls the exe's manifest asks for.

var (
	pUser32   = windows.NewLazySystemDLL("user32.dll")
	pGdi32    = windows.NewLazySystemDLL("gdi32.dll")
	pComctl32 = windows.NewLazySystemDLL("comctl32.dll")
	pShell32  = windows.NewLazySystemDLL("shell32.dll")

	registerClassEx   = pUser32.NewProc("RegisterClassExW")
	createWindowEx    = pUser32.NewProc("CreateWindowExW")
	defWindowProc     = pUser32.NewProc("DefWindowProcW")
	destroyWindow     = pUser32.NewProc("DestroyWindow")
	getMessage        = pUser32.NewProc("GetMessageW")
	translateMessage  = pUser32.NewProc("TranslateMessage")
	dispatchMessage   = pUser32.NewProc("DispatchMessageW")
	postMessage       = pUser32.NewProc("PostMessageW")
	sendMessage       = pUser32.NewProc("SendMessageW")
	postQuitMessage   = pUser32.NewProc("PostQuitMessage")
	getSystemMetrics  = pUser32.NewProc("GetSystemMetrics")
	setWindowText     = pUser32.NewProc("SetWindowTextW")
	loadCursor        = pUser32.NewProc("LoadCursorW")
	setForeground     = pUser32.NewProc("SetForegroundWindow")
	getDpiForSystem   = pUser32.NewProc("GetDpiForSystem")
	createFont        = pGdi32.NewProc("CreateFontW")
	initCommonControl = pComctl32.NewProc("InitCommonControlsEx")
	extractIcon       = pShell32.NewProc("ExtractIconW")
)

const (
	wmDestroy   = 0x0002
	wmClose     = 0x0010
	wmSetFont   = 0x0030
	wmSetIcon   = 0x0080
	pbmMarquee  = 0x0400 + 10
	wsPopup     = 0x80000000
	wsVisible   = 0x10000000
	wsChild     = 0x40000000
	wsCaption   = 0x00C00000
	wsExDlg     = 0x00000001
	wsExAppWin  = 0x00040000
	pbsMarquee  = 0x08
	colorBtn    = 15
	ssEndEllips = 0x00004000
)

type wndClassEx struct {
	Size       uint32
	Style      uint32
	WndProc    uintptr
	ClsExtra   int32
	WndExtra   int32
	Instance   windows.Handle
	Icon       windows.Handle
	Cursor     windows.Handle
	Background windows.Handle
	MenuName   *uint16
	ClassName  *uint16
	IconSm     windows.Handle
}

type winMsg struct {
	Hwnd     uintptr
	Message  uint32
	WParam   uintptr
	LParam   uintptr
	Time     uint32
	Pt       [2]int32
	LPrivate uint32
}

var prog struct {
	sync.Mutex
	hwnd, heading, detail uintptr
	done                  chan struct{}
	shown                 time.Time
}

var progProc = windows.NewCallback(func(hwnd, msg, wp, lp uintptr) uintptr {
	switch msg {
	case wmClose:
		destroyWindow.Call(hwnd)
		return 0
	case wmDestroy:
		postQuitMessage.Call(0)
		return 0
	}
	r, _, _ := defWindowProc.Call(hwnd, msg, wp, lp)
	return r
})

// keep holds the strings handed to Windows, so they stay in memory while it may still read them.
var (
	keep   [][]uint16
	keepMu sync.Mutex
)

func u16(s string) uintptr {
	b, _ := windows.UTF16FromString(s)
	keepMu.Lock()
	keep = append(keep, b)
	keepMu.Unlock()
	return uintptr(unsafe.Pointer(&b[0]))
}

// showProgress opens the window (once); setProgress changes its text; closeProgress closes it.
func showProgress(heading, detail string) {
	prog.Lock()
	if prog.hwnd != 0 {
		prog.Unlock()
		setProgress(heading, detail)
		return
	}
	prog.done = make(chan struct{})
	prog.Unlock()
	ready := make(chan struct{})
	go func() {
		runtime.LockOSThread() // a window belongs to the thread that made it
		defer close(prog.done)
		ok := makeProgressWindow(heading, detail)
		close(ready)
		if !ok {
			return
		}
		var m winMsg
		for {
			r, _, _ := getMessage.Call(uintptr(unsafe.Pointer(&m)), 0, 0, 0)
			if int32(r) <= 0 {
				return
			}
			translateMessage.Call(uintptr(unsafe.Pointer(&m)))
			dispatchMessage.Call(uintptr(unsafe.Pointer(&m)))
		}
	}()
	select {
	case <-ready:
	case <-time.After(3 * time.Second):
	}
}

func makeProgressWindow(heading, detail string) bool {
	icc := [2]uint32{8, 0x20} // INITCOMMONCONTROLSEX: size, ICC_PROGRESS_CLASS
	initCommonControl.Call(uintptr(unsafe.Pointer(&icc)))
	var inst windows.Handle
	_ = windows.GetModuleHandleEx(0, nil, &inst)
	icon, _, _ := extractIcon.Call(uintptr(inst), u16(exePath()), 0)
	cursor, _, _ := loadCursor.Call(0, 32512) // IDC_ARROW
	cls := wndClassEx{WndProc: progProc, Instance: inst, Icon: windows.Handle(icon), Cursor: windows.Handle(cursor),
		Background: windows.Handle(colorBtn + 1), ClassName: windows.StringToUTF16Ptr("FVSBridgeProgress")}
	cls.Size = uint32(unsafe.Sizeof(cls))
	registerClassEx.Call(uintptr(unsafe.Pointer(&cls)))

	dpi := uintptr(96)
	if getDpiForSystem.Find() == nil {
		if d, _, _ := getDpiForSystem.Call(); d != 0 {
			dpi = d
		}
	}
	px := func(v int) uintptr { return uintptr(v) * dpi / 96 }
	w, h := px(440), px(158)
	sw, _, _ := getSystemMetrics.Call(0)
	sh, _, _ := getSystemMetrics.Call(1)
	hwnd, _, _ := createWindowEx.Call(wsExDlg|wsExAppWin, u16("FVSBridgeProgress"), u16("FVS Bridge"),
		wsPopup|wsCaption|wsVisible, (sw-w)/2, (sh-h)/2, w, h, 0, 0, uintptr(inst), 0)
	if hwnd == 0 {
		return false
	}
	if icon != 0 {
		sendMessage.Call(hwnd, wmSetIcon, 0, icon)
		sendMessage.Call(hwnd, wmSetIcon, 1, icon)
	}
	font := func(pt, weight int) uintptr {
		f, _, _ := createFont.Call(uintptr(-int32(pt*int(dpi)/72)), 0, 0, 0, uintptr(weight), 0, 0, 0, 1, 0, 0, 5, 0,
			u16("Segoe UI"))
		return f
	}
	big, normal := font(12, 600), font(9, 400)
	label := func(text string, y, height int, f uintptr) uintptr {
		c, _, _ := createWindowEx.Call(0, u16("STATIC"), u16(text), wsChild|wsVisible|ssEndEllips,
			px(22), px(y), px(380), px(height), hwnd, 0, uintptr(inst), 0)
		sendMessage.Call(c, wmSetFont, f, 1)
		return c
	}
	hd := label(heading, 16, 28, big)
	dt := label(detail, 48, 20, normal)
	bar, _, _ := createWindowEx.Call(0, u16("msctls_progress32"), 0, wsChild|wsVisible|pbsMarquee,
		px(22), px(80), px(380), px(14), hwnd, 0, uintptr(inst), 0)
	sendMessage.Call(bar, pbmMarquee, 1, 25)
	setForeground.Call(hwnd)
	prog.Lock()
	prog.hwnd, prog.heading, prog.detail, prog.shown = hwnd, hd, dt, time.Now()
	prog.Unlock()
	return true
}

func setProgress(heading, detail string) {
	prog.Lock()
	defer prog.Unlock()
	if prog.hwnd == 0 {
		return
	}
	setWindowText.Call(prog.heading, u16(heading))
	setWindowText.Call(prog.detail, u16(detail))
}

// closeProgress closes the window, after it has been up long enough to read (about a second).
func closeProgress() {
	prog.Lock()
	hwnd, done, shown := prog.hwnd, prog.done, prog.shown
	prog.hwnd = 0
	prog.Unlock()
	if hwnd == 0 {
		return
	}
	if d := time.Since(shown); d < time.Second {
		time.Sleep(time.Second - d)
	}
	postMessage.Call(hwnd, wmClose, 0, 0)
	select {
	case <-done:
	case <-time.After(2 * time.Second):
	}
}
