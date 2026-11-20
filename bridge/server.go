package main

import (
	_ "embed"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"net/http/httputil"
	"net/url"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

//go:embed page.html
var pageHTML []byte

//go:embed icon.ico
var iconICO []byte

var listenPort int

// listen opens http://localhost:<port> on this computer only: never on the network, so nobody else can use
// this computer's key through it. The port from last time first, then the next free one.
func listen() (net.Listener, error) {
	c := getConfig()
	var lastErr error
	for p := c.ListenPort; p < c.ListenPort+20; p++ {
		addr := net.JoinHostPort("127.0.0.1", strconv.Itoa(p))
		// Windows lets us take 127.0.0.1:p even when another program listens on all addresses at p (Fatima
		// Voice Studio itself, with Other computers on), and would then send localhost to us: skip such ports.
		if conn, err := net.DialTimeout("tcp", addr, 300*time.Millisecond); err == nil {
			conn.Close()
			lastErr = fmt.Errorf("port %d is in use", p)
			continue
		}
		l, err := net.Listen("tcp", addr)
		if err == nil {
			listenPort = p
			if p != c.ListenPort {
				_ = updateConfig(func(c *Config) { c.ListenPort = p })
			}
			return l, nil
		}
		lastErr = err
	}
	return nil, lastErr
}

func localURL() string { return fmt.Sprintf("http://localhost:%d/", listenPort) }

// ownHost: a request for this bridge by name, not one that reached it through a web page's DNS trick
// (DNS rebinding), which would otherwise get this computer's key.
func ownHost(r *http.Request) bool {
	h, _, err := net.SplitHostPort(r.Host)
	if err != nil {
		h = r.Host
	}
	return h == "localhost" || h == "127.0.0.1" || h == "[::1]" || h == "::1"
}

// ownOrigin: no Origin (agents, tools) or this bridge's own page. A website must not drive the PC with
// this computer's key.
func ownOrigin(r *http.Request) bool {
	o := r.Header.Get("Origin")
	if o == "" {
		return true
	}
	u, err := url.Parse(o)
	if err != nil {
		return false
	}
	h := u.Hostname()
	return (h == "localhost" || h == "127.0.0.1" || h == "::1") && u.Port() == strconv.Itoa(listenPort)
}

func serve(l net.Listener) error {
	mux := http.NewServeMux()
	mux.HandleFunc("/_bridge", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		w.Header().Set("Cache-Control", "no-cache")
		_, _ = w.Write(pageHTML)
	})
	mux.HandleFunc("/_bridge/icon.ico", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "image/x-icon")
		_, _ = w.Write(iconICO)
	})
	mux.HandleFunc("/_bridge/api/", pageAPI)
	mux.HandleFunc("/mcp", mcpHTTP)
	mux.HandleFunc("/", proxyHTTP)

	srv := &http.Server{
		Handler: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if !ownHost(r) {
				http.Error(w, "FVS Bridge only answers http://localhost.", http.StatusForbidden)
				return
			}
			mux.ServeHTTP(w, r)
		}),
		ReadHeaderTimeout: 20 * time.Second,
	}
	return srv.Serve(l)
}

// ---- the proxy -------------------------------------------------------------------------------------------

var proxy = &httputil.ReverseProxy{
	Rewrite: func(pr *httputil.ProxyRequest) {
		c := getConfig()
		target := &url.URL{Scheme: "http", Host: net.JoinHostPort(c.Addr, strconv.Itoa(c.Port))}
		pr.SetURL(target)
		pr.Out.Host = pr.In.Host // the app then shows addresses that work here (http://localhost:<port>)
		pr.Out.Header.Set("X-FVS-Bridge", "1")
		p := pr.In.URL.Path
		if strings.HasPrefix(p, "/v1/") && c.Key != "" && ownOrigin(pr.In) {
			pr.Out.Header.Set("Authorization", "Bearer "+c.Key)
		}
		if strings.HasPrefix(p, "/api/bridge/host/") { // only the bridge itself uses these
			pr.Out.Header.Del("Authorization")
		}
	},
	FlushInterval: -1,
	ErrorHandler: func(w http.ResponseWriter, r *http.Request, err error) {
		askRecheck()
		log.Printf("proxy %s: %v", r.URL.Path, err)
		if strings.Contains(r.Header.Get("Accept"), "text/html") {
			http.Redirect(w, r, "/_bridge?unreachable=1", http.StatusFound)
			return
		}
		writeJSON(w, http.StatusBadGateway, map[string]string{"detail": "Fatima Voice Studio can't be reached right now. " +
			"Is the PC on, with the app running? Open " + localURL() + "_bridge for details."})
	},
}

func proxyHTTP(w http.ResponseWriter, r *http.Request) {
	c := getConfig()
	if c.Addr == "" || c.Key == "" {
		if r.URL.Path == "/" || strings.Contains(r.Header.Get("Accept"), "text/html") {
			http.Redirect(w, r, "/_bridge", http.StatusFound)
			return
		}
		writeJSON(w, http.StatusServiceUnavailable, map[string]string{"detail": "FVS Bridge isn't connected to Fatima Voice Studio yet. Open " + localURL() + "_bridge"})
		return
	}
	proxy.ServeHTTP(w, r)
}

// ---- MCP -------------------------------------------------------------------------------------------------

func mcpHTTP(w http.ResponseWriter, r *http.Request) {
	if !ownOrigin(r) {
		writeJSON(w, http.StatusForbidden, map[string]string{"detail": "Web pages can't use MCP through the bridge."})
		return
	}
	c := getConfig()
	if c.Key == "" {
		writeJSON(w, http.StatusServiceUnavailable, map[string]string{"detail": "FVS Bridge isn't paired with Fatima Voice Studio yet. Open " + localURL() + "_bridge"})
		return
	}
	if r.Method != http.MethodPost {
		// stateless server: no event stream to open, no session to end
		w.Header().Set("Allow", "POST")
		writeJSON(w, http.StatusMethodNotAllowed, map[string]string{"detail": "Method Not Allowed"})
		return
	}
	body, err := io.ReadAll(io.LimitReader(r.Body, 20<<20))
	if err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"detail": err.Error()})
		return
	}
	extra := map[string]string{"Mcp-Protocol-Version": r.Header.Get("Mcp-Protocol-Version"),
		"Mcp-Session-Id": r.Header.Get("Mcp-Session-Id")}
	status, ct, out, err := handleMessage(body, extra)
	if err != nil {
		writeJSON(w, http.StatusBadGateway, map[string]string{"detail": "Fatima Voice Studio can't be reached: " + err.Error()})
		return
	}
	if ct != "" {
		w.Header().Set("Content-Type", ct)
	}
	w.WriteHeader(status)
	_, _ = w.Write(out)
}

// ---- the bridge's own page -------------------------------------------------------------------------------

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

func exePath() string {
	p, err := os.Executable()
	if err != nil {
		return "FVS-Bridge.exe"
	}
	if r, err := filepath.EvalSymlinks(p); err == nil {
		return r
	}
	return p
}

func status() map[string]any {
	c := getConfig()
	s := getState()
	return map[string]any{
		"app": "fvs-bridge", "version": version, "host_id": c.HostID, "host_name": c.HostName, "addr": c.Addr,
		"port": c.Port, "linked": c.Addr != "", "has_key": c.Key != "", "state": s, "url": localURL(),
		"mcp_url": localURL() + "mcp", "exe": exePath(), "files_dir": c.FilesDir,
		"autostart": autostartEnabled(), "autostart_supported": autostartSupported(),
	}
}

func pageAPI(w http.ResponseWriter, r *http.Request) {
	name := strings.TrimPrefix(r.URL.Path, "/_bridge/api/")
	if r.Method == http.MethodGet && name == "status" {
		writeJSON(w, 200, status())
		return
	}
	// changes come only from the bridge's own page (a website can't send this header without asking first)
	if r.Method != http.MethodPost || r.Header.Get("X-Bridge") != "1" || !ownOrigin(r) {
		writeJSON(w, http.StatusForbidden, map[string]string{"detail": "Forbidden"})
		return
	}
	var in map[string]any
	_ = json.NewDecoder(io.LimitReader(r.Body, 1<<16)).Decode(&in)
	str := func(k string) string { s, _ := in[k].(string); return s }
	var err error
	switch name {
	case "discover":
		found := discover(1500 * time.Millisecond)
		setState(func(s *State) { s.Found, s.Searched = found, true })
	case "link":
		port := 0
		if f, ok := in["port"].(float64); ok {
			port = int(f)
		}
		addr := str("addr")
		if id := str("host_id"); id != "" { // one of the PCs found: use an address of it that answers
			for _, f := range getState().Found {
				if f.HostID == id {
					if a, h := reachableAddr(f); a != "" {
						addr, port = a, h.Port
					}
				}
			}
		}
		err = link(addr, port)
	case "pair":
		err = startPairing()
	case "cancel":
		cancelPairing()
	case "unlink":
		unlink()
	case "check":
		check()
	case "files_dir":
		d := strings.TrimSpace(str("files_dir"))
		if d == "" || !filepath.IsAbs(d) {
			err = errors.New("type a full folder path, like C:\\Users\\you\\Downloads\\Fatima Voice Studio")
		} else if err = os.MkdirAll(d, 0o755); err == nil {
			err = updateConfig(func(c *Config) { c.FilesDir = d })
		}
	case "autostart":
		on, _ := in["on"].(bool)
		err = setAutostart(on)
	case "quit":
		writeJSON(w, 200, map[string]string{"status": "quitting"})
		go func() { time.Sleep(200 * time.Millisecond); quit() }()
		return
	case "open_files":
		d := getConfig().FilesDir
		_ = os.MkdirAll(d, 0o755)
		openPath(d)
	default:
		writeJSON(w, 404, map[string]string{"detail": "Not found"})
		return
	}
	if err != nil {
		writeJSON(w, 400, map[string]string{"detail": err.Error()})
		return
	}
	writeJSON(w, 200, status())
}
