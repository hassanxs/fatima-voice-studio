package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"sync"
)

// Config is what the bridge remembers between runs (bridge.json in the user's config folder).
type Config struct {
	HostID     string `json:"host_id"`     // the Fatima Voice Studio PC, recognised by this even after its address changes
	HostName   string `json:"host_name"`   // its computer name, for the page and the tray
	Addr       string `json:"addr"`        // its last known address (IP or name)
	Port       int    `json:"port"`        // its web port
	Key        string `json:"key"`         // this computer's key, handed over once when the PC said Allow
	DeviceID   string `json:"device_id"`   // how that PC lists this computer
	ListenPort int    `json:"listen_port"` // http://localhost:<this> on this computer
	FilesDir   string `json:"files_dir"`   // where finished audio, subtitles and transcripts are copied to
	Installed  bool   `json:"installed"`   // set up once: Start menu, start with Windows (Windows only)
}

var (
	cfgMu sync.Mutex
	cfg   Config
)

func configDir() string {
	d, err := os.UserConfigDir()
	if err != nil {
		d = "."
	}
	return filepath.Join(d, "FVS Bridge")
}

func configPath() string { return filepath.Join(configDir(), "bridge.json") }

func defaultFilesDir() string {
	home, err := os.UserHomeDir()
	if err != nil {
		return filepath.Join(configDir(), "Files")
	}
	return filepath.Join(home, "Music", "FVS Bridge") // not the app's own folder: the app may be installed here too
}

func loadConfig() {
	cfgMu.Lock()
	defer cfgMu.Unlock()
	cfg = Config{ListenPort: 9830, Port: 9830, FilesDir: defaultFilesDir()}
	if b, err := os.ReadFile(configPath()); err == nil {
		_ = json.Unmarshal(b, &cfg)
	}
	if cfg.ListenPort == 0 {
		cfg.ListenPort = 9830
	}
	if cfg.Port == 0 {
		cfg.Port = 9830
	}
	if cfg.FilesDir == "" {
		cfg.FilesDir = defaultFilesDir()
	}
}

// getConfig returns a copy, safe to read without the lock.
func getConfig() Config {
	cfgMu.Lock()
	defer cfgMu.Unlock()
	return cfg
}

// updateConfig changes the settings and writes them to disk.
func updateConfig(fn func(c *Config)) error {
	cfgMu.Lock()
	defer cfgMu.Unlock()
	fn(&cfg)
	if err := os.MkdirAll(configDir(), 0o700); err != nil {
		return err
	}
	b, _ := json.MarshalIndent(cfg, "", "  ")
	tmp := configPath() + ".tmp"
	if err := os.WriteFile(tmp, b, 0o600); err != nil {
		return err
	}
	return os.Rename(tmp, configPath())
}
