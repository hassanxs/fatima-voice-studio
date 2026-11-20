package main

import (
	"bufio"
	"encoding/json"
	"io"
	"log"
	"os"
	"sync"
)

// runStdio is `FVS-Bridge mcp`: MCP over stdin/stdout for agents that only start programs. Each line is one
// JSON-RPC message; it goes to the PC the same way as http://localhost:<port>/mcp, files and all.
func runStdio() {
	c := getConfig()
	if c.Key == "" {
		log.Print("not paired yet: tool calls will be refused until FVS Bridge is connected")
	}
	go func() { // its address may have changed since the bridge last ran
		check()
	}()
	var outMu sync.Mutex
	write := func(b []byte) {
		outMu.Lock()
		defer outMu.Unlock()
		_, _ = os.Stdout.Write(append(b, '\n'))
	}
	in := bufio.NewReaderSize(os.Stdin, 1<<20)
	var wg sync.WaitGroup
	for {
		line, err := in.ReadBytes('\n')
		if len(line) > 0 {
			msg := append([]byte(nil), line...)
			wg.Add(1)
			go func() { // tool calls can run long (wait_for_batch); others keep going meanwhile
				defer wg.Done()
				status, _, out, err := handleMessage(msg, nil)
				if err != nil {
					write(stdioError(idOf(msg), "Fatima Voice Studio can't be reached: "+err.Error()))
					return
				}
				if len(out) == 0 || status == 202 {
					return // a notification: nothing to answer
				}
				if status >= 400 {
					var d struct {
						Detail string `json:"detail"`
					}
					if json.Unmarshal(out, &d) == nil && d.Detail != "" {
						write(stdioError(idOf(msg), d.Detail))
						return
					}
				}
				write(out)
			}()
		}
		if err == io.EOF {
			break
		}
		if err != nil {
			log.Printf("stdin: %v", err)
			break
		}
	}
	wg.Wait()
}

func idOf(msg []byte) any {
	var m struct {
		ID any `json:"id"`
	}
	_ = json.Unmarshal(msg, &m)
	return m.ID
}

func stdioError(id any, text string) []byte {
	b, _ := json.Marshal(map[string]any{"jsonrpc": "2.0", "id": id, "error": map[string]any{"code": -32000, "message": text}})
	return b
}
