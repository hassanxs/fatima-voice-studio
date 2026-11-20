package main

import (
	"encoding/json"
	"errors"
	"log"
	"net/url"
	"os"
	"path/filepath"
	"sync"
	"time"
)

// Batches whose folder the bridge mirrors here. Deleting such a folder on this computer deletes the batch on the
// PC too (it goes to the PC's Recycle Bin), the way it would if the app ran here, and the bridge never brings
// it back. Only for batches the bridge mirrored itself, and only once the PC has finished them.

type batchMirror struct {
	ID          string `json:"id"`
	Name        string `json:"name"`
	Status      string `json:"status"`
	HostFolder  string `json:"host_folder"`
	LocalFolder string `json:"local_folder"`
}

type syncState struct {
	Batches map[string]batchMirror `json:"batches"` // by batch id
	Deleted map[string]string      `json:"deleted"` // batch id -> its folder on the PC
}

var syncMu sync.Mutex

func syncPath() string { return filepath.Join(configDir(), "batches.json") }

// loadSync reads the list from disk each time: the MCP program (FVS-Bridge.exe mcp) and the bridge itself both
// write it.
func loadSync() syncState {
	s := syncState{Batches: map[string]batchMirror{}, Deleted: map[string]string{}}
	if b, err := os.ReadFile(syncPath()); err == nil {
		_ = json.Unmarshal(b, &s)
	}
	if s.Batches == nil {
		s.Batches = map[string]batchMirror{}
	}
	if s.Deleted == nil {
		s.Deleted = map[string]string{}
	}
	return s
}

func saveSync(s syncState) {
	_ = os.MkdirAll(configDir(), 0o700)
	b, _ := json.MarshalIndent(s, "", "  ")
	tmp := syncPath() + ".tmp"
	if os.WriteFile(tmp, b, 0o600) == nil {
		_ = os.Rename(tmp, syncPath())
	}
}

// noteBatch remembers a batch whose folder now exists here.
func noteBatch(b batchMirror) {
	syncMu.Lock()
	defer syncMu.Unlock()
	s := loadSync()
	if _, gone := s.Deleted[b.ID]; gone {
		return
	}
	if old, ok := s.Batches[b.ID]; ok && old == b {
		return
	}
	s.Batches[b.ID] = b
	saveSync(s)
}

// wasDeleted: was this batch deleted from this computer? (By id: a new batch may get the same folder name.)
func wasDeleted(id string) bool {
	syncMu.Lock()
	defer syncMu.Unlock()
	_, ok := loadSync().Deleted[id]
	return ok
}

// syncDeletes runs in the bridge (not in the MCP program): every few seconds it looks for mirrored batch folders
// that were deleted here.
func syncDeletes() {
	for {
		time.Sleep(4 * time.Second)
		if c := getConfig(); c.Key != "" && c.syncDeletes() {
			syncOnce(c)
		}
	}
}

func syncOnce(c Config) {
	syncMu.Lock()
	s := loadSync()
	syncMu.Unlock()
	batchesHere := filepath.Join(c.FilesDir, "Batches")
	if fi, err := os.Stat(batchesHere); err != nil || !fi.IsDir() {
		return // the whole folder is missing (a drive not connected, or moved): that's not deleting batches
	}
	for id, b := range s.Batches {
		if !insideAny(b.LocalFolder, []string{batchesHere}) {
			forgetBatch(id, false) // the files folder was changed since: not ours to judge any more
			continue
		}
		if _, err := os.Stat(b.LocalFolder); !errors.Is(err, os.ErrNotExist) {
			continue
		}
		var now struct {
			Status string `json:"status"`
			Folder string `json:"folder"`
		}
		err := hostJSON("GET", "/api/batches/"+url.PathEscape(id), nil, &now)
		var he *HTTPError
		switch {
		case errors.As(err, &he) && he.Code == 404:
			log.Printf("batch %q: folder deleted here, already gone on the PC", b.Name)
			forgetBatch(id, true)
		case err != nil:
			// the PC can't be reached: try again later
		case !finished(now.Status):
			// still running there: leave it; the next answer about it brings the folder back
		default:
			if err := hostJSON("DELETE", "/api/batches/"+url.PathEscape(id), nil, nil); err != nil {
				log.Printf("batch %q: folder deleted here, but the PC kept it: %v", b.Name, err)
				continue
			}
			log.Printf("batch %q (%s): folder deleted here, so it was deleted on the PC too (to its Recycle Bin)",
				b.Name, id)
			forgetBatch(id, true)
		}
	}
}

func forgetBatch(id string, deleted bool) {
	syncMu.Lock()
	defer syncMu.Unlock()
	s := loadSync()
	b, ok := s.Batches[id]
	delete(s.Batches, id)
	if deleted && ok {
		s.Deleted[id] = b.HostFolder
	}
	if len(s.Deleted) > 2000 { // keep the list small; old ids are never asked about again
		for k := range s.Deleted {
			delete(s.Deleted, k)
			if len(s.Deleted) <= 1000 {
				break
			}
		}
	}
	saveSync(s)
}
