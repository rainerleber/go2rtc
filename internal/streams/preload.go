package streams

import (
	"fmt"
	"net/url"
	"sync"
	"time"

	"github.com/rainerleber/go2rtc/pkg/probe"
)

type Preload struct {
	stream *Stream      // Don't include the stream in JSON to avoid leaking secrets.
	Cons   *probe.Probe `json:"consumer"`
	Query  string       `json:"query"`
	Status string       `json:"status"`
	mu     sync.Mutex
	stop   chan struct{}
	done   chan struct{}
}

var preloads = map[string]*Preload{}
var preloadsMu sync.Mutex

func AddPreload(name, rawQuery string) error {
	if rawQuery == "" {
		rawQuery = "video&audio"
	}

	query, err := url.ParseQuery(rawQuery)
	if err != nil {
		return err
	}

	preloadsMu.Lock()
	defer preloadsMu.Unlock()

	stream := Get(name)
	if stream == nil {
		return fmt.Errorf("streams: stream not found: %s", name)
	}
	if p := preloads[name]; p != nil {
		if p.Query == rawQuery && p.stream == stream {
			return nil
		}
		p.close()
	}

	p := &Preload{stream: stream, Query: rawQuery, Status: "starting", stop: make(chan struct{}), done: make(chan struct{})}
	preloads[name] = p
	// Register intent immediately. Each preload connects independently so one
	// offline camera cannot block others or permanently defeat warm startup.
	go p.run(name, query)
	return nil
}

func (p *Preload) run(name string, query url.Values) {
	defer close(p.done)
	delay := time.Second
	for {
		select {
		case <-p.stop:
			return
		default:
		}
		cons := probe.Create("preload", query)
		if err := p.stream.AddConsumer(cons); err == nil {
			p.mu.Lock()
			p.Cons, p.Status = cons, "active"
			p.mu.Unlock()
			<-p.stop
			p.stream.RemoveConsumer(cons)
			return
		}
		p.stream.RemoveConsumer(cons)
		p.mu.Lock()
		p.Status = "retrying"
		p.mu.Unlock()
		// Underlying producers log diagnostics. Do not repeat source URLs or
		// credential-bearing errors in this retry message.
		log.Warn().Str("stream", name).Dur("retry_in", delay).Msg("preload unavailable; retrying")
		timer := time.NewTimer(delay)
		select {
		case <-p.stop:
			timer.Stop()
			return
		case <-timer.C:
		}
		delay = min(delay*2, 30*time.Second)
	}
}

func (p *Preload) close() {
	close(p.stop)
	<-p.done // Also removes a consumer connected while cancellation was pending.
}

func DelPreload(name string) error {
	preloadsMu.Lock()
	defer preloadsMu.Unlock()

	if p := preloads[name]; p != nil {
		p.close()
		delete(preloads, name)
		return nil
	}

	return fmt.Errorf("streams: preload not found: %s", name)
}

func GetPreloads() map[string]*Preload {
	preloadsMu.Lock()
	defer preloadsMu.Unlock()
	result := make(map[string]*Preload, len(preloads))
	for name, p := range preloads {
		p.mu.Lock()
		result[name] = &Preload{Cons: p.Cons, Query: p.Query, Status: p.Status}
		p.mu.Unlock()
	}
	return result
}
