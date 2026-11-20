package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"mime/multipart"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"time"
)

// Files an agent on this computer passes go up to the PC's inbox; files the PC names in its answers come back
// to FilesDir, in the same layout (Batches, Exports, Transcripts), and the agent gets the local paths.

// mirror is one folder on the PC and where its copy lives here.
type mirror struct {
	host  string // the PC's folder
	local string // the copy on this computer
}

func mirrors(hi *HostInfo, filesDir string) []mirror {
	var out []mirror
	for _, m := range []struct{ host, name string }{
		{hi.BatchesDir, "Batches"}, {hi.ExportsDir, "Exports"}, {hi.TranscriptsDir, "Transcripts"},
	} {
		if m.host != "" {
			out = append(out, mirror{m.host, filepath.Join(filesDir, m.name)})
		}
	}
	return out
}

// hostSep is the PC's path separator, read from its folders (the PC may run Windows, Linux or macOS).
func hostSep(root string) string {
	if strings.Contains(root, `\`) {
		return `\`
	}
	return "/"
}

// underHost says whether p is inside the PC folder root, and returns the part after it ("" for root itself).
func underHost(p, root string) (string, bool) {
	sep := hostSep(root)
	norm := func(s string) string {
		s = strings.TrimRight(s, `\/`)
		if sep == `\` {
			return strings.ToLower(strings.ReplaceAll(s, "/", `\`))
		}
		return s
	}
	np, nr := norm(p), norm(root)
	if np == nr {
		return "", true
	}
	if strings.HasPrefix(np, nr+sep) {
		rest := strings.TrimRight(p, `\/`)[len(nr)+1:]
		return rest, true
	}
	return "", false
}

func hostToLocal(p string, ms []mirror) (string, bool) {
	for _, m := range ms {
		if rest, ok := underHost(p, m.host); ok {
			parts := strings.FieldsFunc(rest, func(r rune) bool { return r == '/' || r == '\\' })
			for _, s := range parts {
				if s == ".." {
					return "", false
				}
			}
			return filepath.Join(append([]string{m.local}, parts...)...), true
		}
	}
	return "", false
}

func localToHost(p string, ms []mirror) (string, bool) {
	abs, err := filepath.Abs(p)
	if err != nil {
		return "", false
	}
	for _, m := range ms {
		rel, err := filepath.Rel(m.local, abs)
		if err != nil || rel == ".." || strings.HasPrefix(rel, ".."+string(filepath.Separator)) {
			continue
		}
		sep := hostSep(m.host)
		if rel == "." {
			return m.host, true
		}
		return strings.TrimRight(m.host, `\/`) + sep + strings.Join(strings.Split(rel, string(filepath.Separator)), sep), true
	}
	return "", false
}

// ---- files in --------------------------------------------------------------------------------------------

// fileArgs are the tool arguments that name a file (studio/mcp_server.py).
func prepareArgs(tool string, args map[string]any) error {
	switch tool {
	case "add_voice", "transcribe":
		if s, ok := args["source"].(string); ok {
			v, err := sendFile(s)
			if err != nil {
				return err
			}
			args["source"] = v
		}
	case "create_batch":
		if scripts, ok := args["scripts"].([]any); ok {
			for _, it := range scripts {
				if sc, ok := it.(map[string]any); ok {
					if s, ok := sc["file"].(string); ok {
						v, err := sendFile(s)
						if err != nil {
							return err
						}
						sc["file"] = v
					}
				}
			}
		}
	}
	return nil
}

// sendFile turns a path on this computer into one the PC can read: a copy we downloaded earlier maps back to the
// PC's own file; anything else is uploaded to its inbox. Links and paths that aren't files here pass unchanged.
func sendFile(p string) (string, error) {
	s := strings.TrimSpace(p)
	if strings.HasPrefix(s, "http://") || strings.HasPrefix(s, "https://") || !filepath.IsAbs(s) {
		return p, nil
	}
	hi, hiErr := getHostInfo()
	st, err := os.Stat(s)
	if err != nil || st.IsDir() {
		if hiErr == nil {
			for _, m := range mirrors(hi, getConfig().FilesDir) {
				if _, ok := underHost(s, m.host); ok {
					return p, nil // a path on the PC itself (from get_settings or an earlier answer)
				}
			}
		}
		if err != nil {
			return "", fmt.Errorf("no file at %s on this computer", s)
		}
		return "", fmt.Errorf("%s is a folder: pass a file", s)
	}
	if hiErr == nil {
		if hp, ok := localToHost(s, mirrors(hi, getConfig().FilesDir)); ok {
			return hp, nil
		}
	}
	if !insideAny(s, readDirs()) {
		return "", fmt.Errorf("%s isn't in a folder agents may read on this computer (%s). Move the file into one "+
			"of them, or add its folder to local_read_dirs in %s", s, strings.Join(readDirs(), ", "), configPath())
	}
	f, err := os.Open(s)
	if err != nil {
		return "", fmt.Errorf("can't read %s: %v", s, err)
	}
	defer f.Close()
	pr, pw := io.Pipe()
	mw := multipart.NewWriter(pw)
	go func() {
		part, err := mw.CreateFormFile("file", filepath.Base(s))
		if err == nil {
			_, err = io.Copy(part, f)
		}
		if err == nil {
			err = mw.Close()
		}
		pw.CloseWithError(err)
	}()
	resp, err := hostRequest(longClient, "POST", "/api/bridge/host/inbox", pr, mw.FormDataContentType())
	if err != nil {
		return "", fmt.Errorf("couldn't send %s to the PC: %v", filepath.Base(s), err)
	}
	defer resp.Body.Close()
	var r struct {
		Path   string `json:"path"`
		Detail string `json:"detail"`
	}
	_ = json.NewDecoder(resp.Body).Decode(&r)
	if resp.StatusCode >= 400 || r.Path == "" {
		return "", fmt.Errorf("the PC didn't take %s: %s", filepath.Base(s), r.Detail)
	}
	log.Printf("sent %s (%d bytes)", s, st.Size())
	return r.Path, nil
}

// readDirs are the folders on this computer agents may pass files from: the ones in the settings, plus the folder
// with the copies the bridge brought over (those map back to the PC's own files).
func readDirs() []string {
	c := getConfig()
	out := []string{}
	for _, d := range append(append([]string{}, c.LocalReadDirs...), c.FilesDir) {
		if d = strings.TrimSpace(d); d != "" && filepath.IsAbs(d) && !contains(out, filepath.Clean(d)) {
			out = append(out, filepath.Clean(d))
		}
	}
	return out
}

// insideAny says whether path p is in one of the folders (links and junctions followed, so they can't lead out).
func insideAny(p string, dirs []string) bool {
	real := func(s string) string {
		if r, err := filepath.EvalSymlinks(s); err == nil {
			s = r
		}
		if a, err := filepath.Abs(s); err == nil {
			s = a
		}
		return filepath.Clean(s)
	}
	rp := real(p)
	for _, d := range dirs {
		rel, err := filepath.Rel(real(d), rp) // on Windows this ignores upper and lower case
		if err == nil && rel != ".." && !strings.HasPrefix(rel, ".."+string(filepath.Separator)) && !filepath.IsAbs(rel) {
			return true
		}
	}
	return false
}

// ---- files out -------------------------------------------------------------------------------------------

type hostStat struct {
	Path  string     `json:"path"`
	Kind  string     `json:"kind"`
	Size  int64      `json:"size"`
	Mtime float64    `json:"mtime"`
	Files []hostStat `json:"files"`
}

// collect finds every string in a tool's answer that is a path in one of the PC's folders.
func collect(v any, ms []mirror, out map[string]bool) {
	switch x := v.(type) {
	case string:
		if _, ok := hostToLocal(x, ms); ok {
			out[x] = true
		}
	case map[string]any:
		for _, e := range x {
			collect(e, ms, out)
		}
	case []any:
		for _, e := range x {
			collect(e, ms, out)
		}
	}
}

func replacePaths(v any, repl map[string]string) any {
	switch x := v.(type) {
	case string:
		if r, ok := repl[x]; ok {
			return r
		}
		return x
	case map[string]any:
		for k, e := range x {
			x[k] = replacePaths(e, repl)
		}
		return x
	case []any:
		for i, e := range x {
			x[i] = replacePaths(e, repl)
		}
		return x
	}
	return v
}

// bringBack copies the files a tool's answer names to this computer and swaps in the local paths. Folders are
// copied whole only for exports (a batch folder holds every part); other folders just get their local path.
func bringBack(tool string, v any) any {
	hi, err := getHostInfo()
	if err != nil {
		return v
	}
	ms := mirrors(hi, getConfig().FilesDir)
	found := map[string]bool{}
	collect(v, ms, found)
	// a batch this answer describes: its folder here is a mirror of the PC's (batch.json too, once it's finished)
	batchTool := tool == "create_batch" || tool == "get_batch" || tool == "wait_for_batch"
	var batches []batchMirror
	if batchTool {
		batches = batchesIn(v, hi.BatchesDir)
		for _, b := range batches {
			if wasDeleted(b.ID) { // deleted from this computer: never brought back
				for p := range found {
					if _, ok := underHost(p, b.HostFolder); ok {
						delete(found, p)
					}
				}
				batches = nil
				break
			}
			if finished(b.Status) {
				found[strings.TrimRight(b.HostFolder, `\/`)+hostSep(b.HostFolder)+"batch.json"] = true
			}
		}
	}
	if len(found) == 0 {
		return v
	}
	paths := make([]string, 0, len(found))
	for p := range found {
		paths = append(paths, p)
	}
	var stats []hostStat
	if err := hostJSON("POST", "/api/bridge/host/stat", map[string]any{"paths": paths}, &stats); err != nil {
		log.Printf("stat: %v", err)
		return v
	}
	repl := map[string]string{}
	for _, st := range stats {
		local, ok := hostToLocal(st.Path, ms)
		if !ok {
			continue
		}
		switch st.Kind {
		case "file":
			if err := fetch(st, local); err != nil {
				log.Printf("download %s: %v", st.Path, err)
				continue
			}
			repl[st.Path] = local
		case "dir":
			if tool == "export_batch" || batchTool {
				_ = os.MkdirAll(local, 0o755)
			}
			if tool == "export_batch" {
				for _, f := range st.Files {
					if lf, ok := hostToLocal(f.Path, ms); ok {
						if err := fetch(f, lf); err != nil {
							log.Printf("download %s: %v", f.Path, err)
						}
					}
				}
			}
			repl[st.Path] = local
		}
	}
	for _, b := range batches {
		if local, ok := hostToLocal(b.HostFolder, ms); ok {
			if fi, err := os.Stat(local); err == nil && fi.IsDir() {
				b.LocalFolder = local
				noteBatch(b)
			}
		}
	}
	return replacePaths(v, repl)
}

// batchesIn finds the batches a tool's answer describes (id, name, status and a folder among the PC's batches).
func batchesIn(v any, batchesDir string) []batchMirror {
	m, ok := v.(map[string]any)
	if !ok || batchesDir == "" {
		return nil
	}
	id, _ := m["id"].(string)
	folder, _ := m["folder"].(string)
	if id == "" || folder == "" {
		return nil
	}
	if rest, ok := underHost(folder, batchesDir); !ok || rest == "" {
		return nil
	}
	name, _ := m["name"].(string)
	status, _ := m["status"].(string)
	if status == "" {
		status = "queued" // create_batch: just queued
	}
	return []batchMirror{{ID: id, Name: name, Status: status, HostFolder: folder}}
}

// finished: the PC is done with the batch (nothing running, queued or being joined).
func finished(status string) bool {
	return status == "done" || status == "failed" || status == "cancelled"
}

// postProcess adjusts answers that describe the PC's own setup: through the bridge, agents pass files from this
// computer's folders, not the PC's.
func postProcess(tool string, v any) any {
	if tool == "get_settings" {
		if m, ok := v.(map[string]any); ok {
			dirs := make([]any, 0)
			for _, d := range readDirs() {
				dirs = append(dirs, d)
			}
			m["agents_may_read"] = dirs
		}
	}
	return v
}

// fetch downloads one file unless the copy here is already the same (size and time).
func fetch(st hostStat, local string) error {
	mt := time.Unix(0, int64(st.Mtime*1e9))
	if fi, err := os.Stat(local); err == nil && fi.Size() == st.Size && fi.ModTime().Unix() == mt.Unix() {
		return nil
	}
	if err := os.MkdirAll(filepath.Dir(local), 0o755); err != nil {
		return err
	}
	resp, err := hostRequest(longClient, "GET", "/api/bridge/host/file?path="+url.QueryEscape(st.Path), nil, "")
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return errors.New(resp.Status)
	}
	tmp := local + ".part"
	f, err := os.Create(tmp)
	if err != nil {
		return err
	}
	if _, err := io.Copy(f, resp.Body); err != nil {
		f.Close()
		os.Remove(tmp)
		return err
	}
	f.Close()
	if err := os.Rename(tmp, local); err != nil {
		os.Remove(tmp)
		return err
	}
	_ = os.Chtimes(local, mt, mt)
	return nil
}

// ---- the MCP messages ------------------------------------------------------------------------------------

func bridgeNote() string {
	s := "Through the bridge on this computer: pass files from this computer's folders that get_settings lists " +
		"under agents_may_read (they are sent over), and file paths in results are copies on this computer. "
	if getConfig().syncDeletes() {
		s += "Deleting a finished batch's folder here also deletes that batch on the PC. "
	}
	return s + "The copies are in "
}

// rewriteText adjusts what the PC tells agents about folders, since through the bridge they work differently.
func rewriteText(s, filesDir string) string {
	s = strings.ReplaceAll(s, "Files you pass must be inside the folders allowed on the\nConnect page (see get_settings).",
		bridgeNote()+filesDir+".")
	s = strings.ReplaceAll(s, "Files you pass must be inside the folders allowed on the Connect page (see get_settings).",
		bridgeNote()+filesDir+".")
	s = strings.ReplaceAll(s, "absolute path inside an allowed folder", "absolute path on this computer, in an allowed folder")
	s = strings.ReplaceAll(s, "absolute path in an allowed folder", "absolute path on this computer, in an allowed folder")
	s = strings.ReplaceAll(s, "a .txt/.md path in an allowed folder", "a .txt/.md path on this computer, in an allowed folder")
	return s
}

// handleMessage takes one JSON-RPC message from an agent, sends it to the PC and returns the PC's answer
// (empty for notifications), with files carried both ways.
func handleMessage(body []byte, extra map[string]string) (status int, contentType string, out []byte, err error) {
	var msg map[string]any
	isObj := json.Unmarshal(body, &msg) == nil
	method, tool := "", ""
	if isObj {
		method, _ = msg["method"].(string)
		if method == "tools/call" {
			if params, ok := msg["params"].(map[string]any); ok {
				tool, _ = params["name"].(string)
				if args, ok := params["arguments"].(map[string]any); ok {
					if err := prepareArgs(tool, args); err != nil {
						return 200, "application/json", toolError(msg["id"], err.Error()), nil
					}
				}
				body, _ = json.Marshal(msg)
			}
		}
	}
	resp, err := hostRequestHeaders(longClient, "POST", "/mcp", bytes.NewReader(body), map[string]string{
		"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
	}, extra)
	if err != nil {
		askRecheck()
		return 0, "", nil, err
	}
	defer resp.Body.Close()
	data, err := io.ReadAll(resp.Body)
	if err != nil {
		return 0, "", nil, err
	}
	ct := resp.Header.Get("Content-Type")
	if resp.StatusCode == 401 {
		askRecheck()
	}
	if resp.StatusCode != 200 || !strings.HasPrefix(ct, "application/json") || method == "" {
		return resp.StatusCode, ct, data, nil
	}
	var r map[string]any
	if json.Unmarshal(data, &r) != nil {
		return resp.StatusCode, ct, data, nil
	}
	result, _ := r["result"].(map[string]any)
	if result == nil {
		return resp.StatusCode, ct, data, nil
	}
	filesDir := getConfig().FilesDir
	switch method {
	case "initialize":
		if s, ok := result["instructions"].(string); ok {
			result["instructions"] = rewriteText(s, filesDir)
		}
	case "tools/list":
		if tools, ok := result["tools"].([]any); ok {
			for _, t := range tools {
				if tm, ok := t.(map[string]any); ok {
					if d, ok := tm["description"].(string); ok {
						tm["description"] = rewriteText(d, filesDir)
					}
				}
			}
		}
	case "tools/call":
		if content, ok := result["content"].([]any); ok {
			for _, c := range content {
				cm, ok := c.(map[string]any)
				if !ok || cm["type"] != "text" {
					continue
				}
				text, _ := cm["text"].(string)
				var inner any
				if json.Unmarshal([]byte(text), &inner) == nil {
					inner = postProcess(tool, bringBack(tool, inner))
					b, _ := json.Marshal(inner)
					cm["text"] = string(b)
				}
			}
		}
		if sc, ok := result["structuredContent"]; ok {
			result["structuredContent"] = postProcess(tool, bringBack(tool, sc))
		}
	}
	out, _ = json.Marshal(r)
	return resp.StatusCode, ct, out, nil
}

func toolError(id any, text string) []byte {
	b, _ := json.Marshal(map[string]any{"jsonrpc": "2.0", "id": id, "result": map[string]any{
		"content": []any{map[string]any{"type": "text", "text": text}}, "isError": true}})
	return b
}
