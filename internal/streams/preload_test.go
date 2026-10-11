package streams

import (
	"errors"
	"sync/atomic"
	"testing"
	"time"

	"github.com/rainerleber/go2rtc/pkg/core"
)

type preloadTestProducer struct {
	core.Connection
	done chan struct{}
}

func (p *preloadTestProducer) Start() error { <-p.done; return nil }
func (p *preloadTestProducer) Stop() error  { close(p.done); return p.Connection.Stop() }

func awaitPreload(t *testing.T, name, status string) {
	t.Helper()
	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		if p := GetPreloads()[name]; p != nil && p.Status == status {
			return
		}
		time.Sleep(10 * time.Millisecond)
	}
	t.Fatalf("preload did not reach %s", status)
}

func TestPreloadRetriesAndCancels(t *testing.T) {
	var attempts atomic.Int32
	HandleFunc("preloadtest", func(string) (core.Producer, error) {
		if attempts.Add(1) == 1 {
			return nil, errors.New("camera temporarily offline")
		}
		return &preloadTestProducer{Connection: core.Connection{Medias: []*core.Media{{Kind: core.KindVideo, Direction: core.DirectionRecvonly, Codecs: []*core.Codec{{Name: core.CodecH264}}}}}, done: make(chan struct{})}, nil
	})
	name := "preload_retry_test"
	if _, err := New(name, "preloadtest:camera"); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = DelPreload(name); Delete(name); delete(handlers, "preloadtest") })
	if err := AddPreload(name, "video"); err != nil {
		t.Fatal(err)
	}
	awaitPreload(t, name, "retrying")
	awaitPreload(t, name, "active")
	if attempts.Load() != 2 {
		t.Fatal("expected a retry")
	}
	if err := AddPreload(name, "video"); err != nil {
		t.Fatal(err)
	}
	if attempts.Load() != 2 {
		t.Fatal("same preload must be idempotent")
	}
	if err := DelPreload(name); err != nil {
		t.Fatal(err)
	}
	if GetPreloads()[name] != nil {
		t.Fatal("preload still registered")
	}
}

func TestPreloadCancelPending(t *testing.T) {
	var attempts atomic.Int32
	HandleFunc("preloadoffline", func(string) (core.Producer, error) {
		attempts.Add(1)
		return nil, errors.New("offline")
	})
	name := "preload_cancel_test"
	if _, err := New(name, "preloadoffline:camera"); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = DelPreload(name); Delete(name); delete(handlers, "preloadoffline") })
	if err := AddPreload(name, "video"); err != nil {
		t.Fatal(err)
	}
	awaitPreload(t, name, "retrying")
	if err := DelPreload(name); err != nil {
		t.Fatal(err)
	}
	if GetPreloads()[name] != nil || attempts.Load() != 1 {
		t.Fatal("pending preload not cancelled")
	}
	if err := AddPreload("missing", "video"); err == nil {
		t.Fatal("missing stream accepted")
	}
	if err := AddPreload(name, "%invalid"); err == nil {
		t.Fatal("invalid query accepted")
	}
}
