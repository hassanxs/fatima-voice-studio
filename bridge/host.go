package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"os"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
)

const discoveryPort = 9830 // UDP, the same on every Fatima Voice Studio PC (studio/lan.py)

// Found is a Fatima Voice Studio PC that answered the broadcast.
type Found struct {
	HostID  string   `json:"host_id"`
	Name    string   `json:"name"`
	Version string   `json:"version"`
	Port    int      `json:"port"`
	Addrs   []string `json:"addrs"`
}

// Health is what /v1/health says.
type Health struct {
	Status  string `json:"status"`
	App     string `json:"app"`
	HostID  string `json:"host_id"`
	Name    string `json:"name"`
	Version string `json:"version"`
	Port    int    `json:"port"`
}

// HostInfo is where the PC keeps its files (from /api/bridge/host/info).
type HostInfo struct {
	BatchesDir     string `json:"batches_dir"`
	ExportsDir     string `json:"exports_dir"`
	TranscriptsDir string `json:"transcripts_dir"`
	InboxDir       string `json:"inbox_dir"`
	Version        string `json:"version"`
}

// State is what the page and the tray show; guarded by stateMu.
type State struct {
	Reachable bool      `json:"reachable"`
	Paired    bool      `json:"paired"`
	Removed   bool      `json:"removed"` // the PC removed this computer (its key is refused)
	Version   string    `json:"version"`
	Checking  bool      `json:"checking"`
	LastError string    `json:"last_error"`
	Found     []Found   `json:"found"`
	Searched  bool      `json:"searched"`
	Pairing   *Pairing  `json:"pairing"`
	CheckedAt time.Time `json:"checked_at"`
}

// Pairing is a request waiting for Allow on the PC.
type Pairing struct {
	Status  string `json:"status"` // waiting, allowed, denied, expired, error
	Code    string `json:"code"`
	Message string `json:"message"`
	rid     string
}

var (
	stateMu  sync.Mutex
	state    State
	hostInfo *HostInfo
	recheck  = make(chan struct{}, 1)

	shortClient = &http.Client{Timeout: 4 * time.Second}
	longClient  = &http.Client{Timeout: 0} // tool calls like wait_for_batch take minutes
)

func getState() State {
	stateMu.Lock()
	defer stateMu.Unlock()
	s := state
	if s.Pairing != nil {
		p := *s.Pairing
		s.Pairing = &p
	}
	return s
}

func setState(fn func(s *State)) {
	stateMu.Lock()
	fn(&state)
	stateMu.Unlock()
	trayRefresh()
}

func baseURL(c Config) string {
	return "http://" + net.JoinHostPort(c.Addr, strconv.Itoa(c.Port))
}

// hostRequest sends a request to the PC with this computer's key and the header its /api routes want.
func hostRequest(client *http.Client, method, path string, body io.Reader, contentType string) (*http.Response, error) {
	h := map[string]string{}
	if contentType != "" {
		h["Content-Type"] = contentType
	}
	return hostRequestHeaders(client, method, path, body, h, nil)
}

func hostRequestHeaders(client *http.Client, method, path string, body io.Reader, headers, extra map[string]string) (*http.Response, error) {
	c := getConfig()
	if c.Addr == "" {
		return nil, errors.New("not connected to a PC yet")
	}
	req, err := http.NewRequest(method, baseURL(c)+path, body)
	if err != nil {
		return nil, err
	}
	if c.Key != "" {
		req.Header.Set("Authorization", "Bearer "+c.Key)
	}
	req.Header.Set("X-Studio", "1")
	req.Header.Set("X-FVS-Bridge", "1")
	for k, v := range extra {
		if v != "" {
			req.Header.Set(k, v)
		}
	}
	for k, v := range headers {
		req.Header.Set(k, v)
	}
	return client.Do(req)
}

func hostJSON(method, path string, in any, out any) error {
	var body io.Reader
	ct := ""
	if in != nil {
		b, _ := json.Marshal(in)
		body, ct = bytes.NewReader(b), "application/json"
	}
	resp, err := hostRequest(shortClient, method, path, body, ct)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	data, _ := io.ReadAll(resp.Body)
	if resp.StatusCode >= 400 {
		var d struct {
			Detail string `json:"detail"`
		}
		_ = json.Unmarshal(data, &d)
		if d.Detail == "" {
			d.Detail = resp.Status
		}
		return &HTTPError{resp.StatusCode, d.Detail}
	}
	if out != nil {
		return json.Unmarshal(data, out)
	}
	return nil
}

type HTTPError struct {
	Code   int
	Detail string
}

func (e *HTTPError) Error() string { return e.Detail }

// health asks one address whether Fatima Voice Studio answers there.
func health(addr string, port int) (*Health, error) {
	resp, err := shortClient.Get("http://" + net.JoinHostPort(addr, strconv.Itoa(port)) + "/v1/health")
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	var h Health
	if resp.StatusCode == http.StatusForbidden {
		return nil, errors.New("that PC refuses this computer: turn on Settings → Other computers there")
	}
	if err := json.NewDecoder(resp.Body).Decode(&h); err != nil || h.Status != "ok" {
		return nil, errors.New("that address answers, but it isn't Fatima Voice Studio")
	}
	if h.Port == 0 {
		h.Port = port
	}
	return &h, nil
}

// discover broadcasts on every network and collects the answers for a moment.
func discover(wait time.Duration) []Found {
	conn, err := net.ListenUDP("udp4", &net.UDPAddr{})
	if err != nil {
		log.Printf("discovery: %v", err)
		return nil
	}
	defer conn.Close()
	msg := []byte(`{"fvs":"discover","v":1}`)
	targets := map[string]bool{"255.255.255.255": true}
	if ifaces, err := net.Interfaces(); err == nil {
		for _, ifc := range ifaces {
			if ifc.Flags&net.FlagUp == 0 || ifc.Flags&net.FlagLoopback != 0 {
				continue
			}
			addrs, _ := ifc.Addrs()
			for _, a := range addrs {
				n, ok := a.(*net.IPNet)
				if !ok || n.IP.To4() == nil {
					continue
				}
				ip, mask := n.IP.To4(), n.Mask
				if len(mask) == 16 {
					mask = mask[12:]
				}
				b := make(net.IP, 4)
				for i := range b {
					b[i] = ip[i] | ^mask[i]
				}
				targets[b.String()] = true
			}
		}
	}
	for t := range targets {
		_, _ = conn.WriteToUDP(msg, &net.UDPAddr{IP: net.ParseIP(t), Port: discoveryPort})
	}
	byID := map[string]*Found{}
	_ = conn.SetReadDeadline(time.Now().Add(wait))
	buf := make([]byte, 2048)
	for {
		n, from, err := conn.ReadFromUDP(buf)
		if err != nil {
			break
		}
		var r struct {
			FVS     string `json:"fvs"`
			HostID  string `json:"host_id"`
			Name    string `json:"name"`
			Version string `json:"version"`
			Port    int    `json:"port"`
		}
		if json.Unmarshal(buf[:n], &r) != nil || r.FVS != "here" || r.HostID == "" {
			continue
		}
		f := byID[r.HostID]
		if f == nil {
			f = &Found{HostID: r.HostID, Name: r.Name, Version: r.Version, Port: r.Port}
			byID[r.HostID] = f
		}
		a := from.IP.String()
		if !contains(f.Addrs, a) {
			f.Addrs = append(f.Addrs, a)
		}
	}
	out := make([]Found, 0, len(byID))
	for _, f := range byID {
		out = append(out, *f)
	}
	sort.Slice(out, func(i, j int) bool { return strings.ToLower(out[i].Name) < strings.ToLower(out[j].Name) })
	return out
}

func contains(list []string, s string) bool {
	for _, x := range list {
		if x == s {
			return true
		}
	}
	return false
}

// reachableAddr returns the first address of a found PC that really answers (a PC with virtual network cards
// answers the broadcast on each of them).
func reachableAddr(f Found) (string, *Health) {
	for _, a := range f.Addrs {
		if h, err := health(a, f.Port); err == nil && h.HostID == f.HostID {
			return a, h
		}
	}
	return "", nil
}

// check sees whether the linked PC answers at its last address; if not, it looks for it on the network by its
// id (its address may have changed), and it checks that this computer's key is still accepted.
func check() {
	c := getConfig()
	if c.HostID == "" && c.Addr == "" {
		setState(func(s *State) { s.Reachable, s.Paired, s.CheckedAt = false, false, time.Now() })
		return
	}
	setState(func(s *State) { s.Checking = true })
	defer setState(func(s *State) { s.Checking = false; s.CheckedAt = time.Now() })

	h, err := health(c.Addr, c.Port)
	if err == nil && c.HostID != "" && h.HostID != c.HostID {
		err = errors.New("another Fatima Voice Studio PC answers at that address now")
	}
	if err != nil && c.HostID != "" {
		for _, f := range discover(1500 * time.Millisecond) {
			if f.HostID != c.HostID {
				continue
			}
			if a, fh := reachableAddr(f); a != "" {
				log.Printf("found %s at a new address: %s", f.Name, a)
				_ = updateConfig(func(c *Config) { c.Addr, c.Port, c.HostName = a, fh.Port, fh.Name })
				h, err = fh, nil
			}
		}
	}
	if err != nil {
		setState(func(s *State) { s.Reachable, s.LastError = false, err.Error() })
		return
	}
	if h.Name != c.HostName {
		_ = updateConfig(func(c *Config) { c.HostName = h.Name })
	}
	paired, removed := false, false
	if c.Key != "" {
		var info HostInfo
		if err := hostJSON("GET", "/api/bridge/host/info", nil, &info); err == nil {
			paired = true
			stateMu.Lock()
			hostInfo = &info
			stateMu.Unlock()
		} else if he, ok := err.(*HTTPError); ok && he.Code == http.StatusUnauthorized {
			removed = true
		}
	}
	setState(func(s *State) {
		s.Reachable, s.Paired, s.Removed, s.Version, s.LastError = true, paired, removed, h.Version, ""
	})
}

// watch keeps checking the PC in the background, at once when something failed.
func watch() {
	for {
		check()
		wait := 20 * time.Second
		if !getState().Reachable {
			wait = 8 * time.Second
		}
		select {
		case <-recheck:
		case <-time.After(wait):
		}
	}
}

func askRecheck() {
	select {
	case recheck <- struct{}{}:
	default:
	}
}

// link points the bridge at a PC (found, or typed in) and asks it to pair.
func link(addr string, port int) error {
	addr = strings.TrimSpace(addr)
	addr = strings.TrimPrefix(strings.TrimPrefix(addr, "http://"), "https://")
	addr = strings.TrimSuffix(addr, "/")
	if i := strings.Index(addr, "/"); i >= 0 {
		addr = addr[:i]
	}
	if h, p, err := net.SplitHostPort(addr); err == nil {
		addr = h
		if n, err := strconv.Atoi(p); err == nil {
			port = n
		}
	}
	if addr == "" {
		return errors.New("type the address of the PC that runs Fatima Voice Studio")
	}
	if port == 0 {
		port = 9830
	}
	h, err := health(addr, port)
	if err != nil {
		var ne net.Error
		if errors.As(err, &ne) || strings.Contains(err.Error(), "refused") || strings.Contains(err.Error(), "no such host") {
			return fmt.Errorf("nothing answers at %s on port %d. Check the address on that PC (Settings → Other computers) and that it's on the same network", addr, port)
		}
		return err
	}
	if h.HostID == "" {
		return fmt.Errorf("the PC at %s runs Fatima Voice Studio %s, which can't pair with the bridge yet. Update it there (About → Updates)", addr, h.Version)
	}
	c := getConfig()
	sameHost := c.HostID == h.HostID
	_ = updateConfig(func(c *Config) {
		if !sameHost {
			c.Key, c.DeviceID = "", ""
		}
		c.HostID, c.HostName, c.Addr, c.Port = h.HostID, h.Name, addr, h.Port
	})
	setState(func(s *State) { s.Reachable, s.Version, s.LastError, s.Removed = true, h.Version, "", false })
	if sameHost && c.Key != "" {
		askRecheck()
		return nil
	}
	return startPairing()
}

// cancelPairing withdraws a request still waiting, so the PC stops asking.
func cancelPairing() {
	stateMu.Lock()
	p := state.Pairing
	stateMu.Unlock()
	if p != nil && p.Status == "waiting" && p.rid != "" {
		if err := hostJSON("DELETE", "/api/bridge/pair/"+p.rid, nil, nil); err != nil {
			log.Printf("cancel pairing: %v", err)
		}
	}
	setState(func(s *State) { s.Pairing = nil })
}

// startPairing asks the PC for a key and waits (in the background) for Allow there.
func startPairing() error {
	cancelPairing()
	name, _ := os.Hostname()
	var r struct {
		Request string `json:"request"`
		Code    string `json:"code"`
	}
	_ = updateConfig(func(c *Config) { c.Key, c.DeviceID = "", "" })
	if err := hostJSON("POST", "/api/bridge/pair", map[string]string{"name": name}, &r); err != nil {
		setState(func(s *State) { s.Pairing = &Pairing{Status: "error", Message: err.Error()} })
		return err
	}
	p := &Pairing{Status: "waiting", Code: r.Code, rid: r.Request}
	setState(func(s *State) { s.Pairing, s.Paired, s.Removed = p, false, false })
	go func() {
		deadline := time.Now().Add(10 * time.Minute)
		for time.Now().Before(deadline) {
			time.Sleep(1500 * time.Millisecond)
			stateMu.Lock()
			current := state.Pairing
			stateMu.Unlock()
			if current == nil || current.rid != r.Request {
				return // cancelled, or a newer request
			}
			var st struct {
				Status string `json:"status"`
				Key    string `json:"key"`
				Device string `json:"device"`
				HostID string `json:"host_id"`
				Name   string `json:"name"`
			}
			if err := hostJSON("GET", "/api/bridge/pair/"+r.Request, nil, &st); err != nil {
				continue // the PC may be restarting; keep asking
			}
			switch st.Status {
			case "pending":
				continue
			case "allowed":
				_ = updateConfig(func(c *Config) { c.Key, c.DeviceID, c.HostID, c.HostName = st.Key, st.Device, st.HostID, st.Name })
				setState(func(s *State) { s.Pairing = &Pairing{Status: "allowed"} })
				log.Printf("paired with %s", st.Name)
				check()
				return
			case "denied":
				setState(func(s *State) { s.Pairing = &Pairing{Status: "denied", Message: "The PC said no."} })
				return
			default:
				setState(func(s *State) { s.Pairing = &Pairing{Status: "expired", Message: "Nobody answered on the PC in time."} })
				return
			}
		}
		setState(func(s *State) { s.Pairing = &Pairing{Status: "expired", Message: "Nobody answered on the PC in time."} })
	}()
	return nil
}

// forgetOnHost tells the PC to remove this computer from its list (unlinking, uninstalling).
func forgetOnHost() {
	if c := getConfig(); c.Key != "" && c.Addr != "" {
		if err := hostJSON("POST", "/api/bridge/host/forget", map[string]string{}, nil); err != nil {
			log.Printf("forget: %v", err)
		}
	}
}

func unlink() {
	cancelPairing()
	forgetOnHost()
	_ = updateConfig(func(c *Config) { c.HostID, c.HostName, c.Addr, c.Key, c.DeviceID = "", "", "", "", "" })
	stateMu.Lock()
	hostInfo = nil
	stateMu.Unlock()
	setState(func(s *State) { *s = State{} })
}

func getHostInfo() (*HostInfo, error) {
	stateMu.Lock()
	hi := hostInfo
	stateMu.Unlock()
	if hi != nil {
		return hi, nil
	}
	var info HostInfo
	if err := hostJSON("GET", "/api/bridge/host/info", nil, &info); err != nil {
		return nil, err
	}
	stateMu.Lock()
	hostInfo = &info
	stateMu.Unlock()
	return &info, nil
}

// trayText is the one-line status for the tray menu.
func trayText() string {
	c := getConfig()
	s := getState()
	name := c.HostName
	if name == "" {
		name = "the PC"
	}
	switch {
	case c.Addr == "":
		return "Not connected yet"
	case s.Pairing != nil && s.Pairing.Status == "waiting":
		return "Waiting for Allow on " + name
	case s.Removed:
		return name + " removed this computer"
	case c.Key == "":
		return "Not paired with " + name
	case s.Reachable:
		return "Connected to " + name
	case s.Checking:
		return "Looking for " + name + "…"
	default:
		return "Can't reach " + name
	}
}
