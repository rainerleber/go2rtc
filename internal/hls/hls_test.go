package hls

import (
	"bytes"
	"context"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os/exec"
	"strings"
	"testing"
	"time"
)

func testServer(t *testing.T) *Server {
	t.Helper()
	s, err := New(Config{Stream: "test", SegmentSeconds: 1, SegmentCount: 3}, "http://127.0.0.1:1984", 8554)
	if err != nil {
		t.Fatal(err)
	}
	s.generation = "synthetic"
	s.uploadToken = "synthetic"
	s.info = mediaInfo{320, 180, "avc1.4d401f,mp4a.40.2"}
	return s
}

func call(s *Server, method, path string, body []byte) *httptest.ResponseRecorder {
	r := httptest.NewRequest(method, path, bytes.NewReader(body))
	r.RemoteAddr = "127.0.0.1:12345"
	w := httptest.NewRecorder()
	s.ServeHTTP(w, r)
	return w
}

func transport() []byte {
	data := make([]byte, 188*4)
	for i := 0; i < len(data); i += 188 {
		data[i] = 0x47
	}
	return data
}

func TestWorkerUsesGenerationLocalSequence(t *testing.T) {
	s := testServer(t)
	args := s.args("synthetic")
	for i, arg := range args {
		if arg == "-start_number" {
			if i+1 >= len(args) || args[i+1] != "0" {
				t.Fatal("worker must start its generation at sequence zero for legacy HLS parsers")
			}
			return
		}
	}
	t.Fatal("explicit generation-local sequence missing")
}

func TestGenerationRevokesReusedSegmentNames(t *testing.T) {
	s := testServer(t)
	oldGeneration := s.generation
	oldUpload := s.uploadToken
	fill := func(marker byte) {
		data := transport()
		data[10] = marker
		for i := range 3 {
			path := fmt.Sprintf("/internal/hls/%s/segment-%d.ts", s.uploadToken, i)
			if call(s, "PUT", path, data).Code != 204 {
				t.Fatal("synthetic segment rejected")
			}
		}
		body := "#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:1\n#EXT-X-MEDIA-SEQUENCE:0\n#EXTINF:1.000000,\nsegment-0.ts\n#EXTINF:1.000000,\nsegment-1.ts\n#EXTINF:1.000000,\nsegment-2.ts\n"
		if call(s, "PUT", "/internal/hls/"+s.uploadToken+"/index.m3u8", []byte(body)).Code != 204 {
			t.Fatal("synthetic playlist rejected")
		}
	}
	fill(1)
	oldPath := "/api/hls/v1/test/segment-0.ts?generation=" + oldGeneration
	if response := call(s, "GET", oldPath, nil); response.Code != 200 || response.Body.Bytes()[10] != 1 {
		t.Fatal("first generation unavailable")
	}
	s.resetLocked(token())
	s.info = mediaInfo{320, 180, "avc1.4d401f,mp4a.40.2"}
	fill(2)
	for _, name := range []string{"master.m3u8", "stream.m3u8", "segment-0.ts"} {
		if call(s, "GET", "/api/hls/v1/test/"+name+"?generation="+oldGeneration, nil).Code != 410 {
			t.Fatal("old generation accepted after segment names were reused")
		}
	}
	if call(s, "PUT", "/internal/hls/"+oldUpload+"/segment-0.ts", transport()).Code != 404 {
		t.Fatal("old upload capability accepted")
	}
	response := call(s, "GET", "/api/hls/v1/test/segment-0.ts?generation="+s.generation, nil)
	if response.Code != 200 || response.Body.Bytes()[10] != 2 || response.Header().Get("X-HLS-Generation") != s.generation {
		t.Fatal("new generation did not serve its own media")
	}
}

func TestPrivateAPIAndCapabilities(t *testing.T) {
	s := testServer(t)
	for _, path := range []string{"/internal/hls/wrong/index.m3u8", "/api/hls/v1/other/status", "/internal/hls/synthetic/../../file"} {
		if call(s, "GET", path, nil).Code != 404 {
			t.Fatal("unconfigured route accepted")
		}
	}
	r := httptest.NewRequest("GET", "/api/hls/v1/test/status", nil)
	r.RemoteAddr = "192.0.2.1:123"
	w := httptest.NewRecorder()
	s.ServeHTTP(w, r)
	if w.Code != 403 {
		t.Fatal("non-loopback caller accepted")
	}
	if call(s, "POST", "/internal/hls/synthetic/segment-1.ts", transport()).Code != 405 {
		t.Fatal("wrong method accepted")
	}
	if call(s, "PUT", "/internal/hls/synthetic/segment-1.ts", []byte("invalid")).Code != 400 {
		t.Fatal("invalid TS accepted")
	}
	if call(s, "PUT", "/internal/hls/synthetic/segment-1.ts", make([]byte, MaxSegmentBytes+1)).Code != 413 {
		t.Fatal("oversize segment accepted")
	}
	if call(s, "GET", "/api/hls/v1/test/master.m3u8?generation=expired", nil).Code != 410 {
		t.Fatal("old generation accepted")
	}
}

func TestRAMBufferAndPlaylist(t *testing.T) {
	s := testServer(t)
	for i := 1; i <= 8; i++ {
		if w := call(s, "PUT", fmt.Sprintf("/internal/hls/synthetic/segment-%d.ts", i), transport()); w.Code != 204 {
			t.Fatal(w.Code, w.Body.String())
		}
	}
	if len(s.segments) != 8 {
		t.Fatal("pending upload retention changed")
	}
	body := "#EXTM3U\n#EXT-X-VERSION:6\n#EXT-X-TARGETDURATION:1\n#EXT-X-MEDIA-SEQUENCE:6\n#EXT-X-INDEPENDENT-SEGMENTS\n#EXTINF:1.000000,\nsegment-6.ts\n#EXTINF:1.000000,\nsegment-7.ts\n#EXTINF:1.000000,\nsegment-8.ts\n"
	if w := call(s, "PUT", "/internal/hls/synthetic/index.m3u8", []byte(body)); w.Code != 204 {
		t.Fatal(w.Code, w.Body.String())
	}
	if !s.readyLocked() {
		t.Fatal("valid window not ready")
	}
	for i := 1; i <= 5; i++ {
		s.expires[fmt.Sprintf("segment-%d.ts", i)] = time.Now().Add(-time.Second)
	}
	if w := call(s, "PUT", "/internal/hls/synthetic/segment-9.ts", transport()); w.Code != 204 {
		t.Fatal("cleanup upload rejected")
	}
	if len(s.segments) != 4 || s.segments["segment-1.ts"] != nil {
		t.Fatal("expired media not removed")
	}
	for _, name := range []string{"master.m3u8", "stream.m3u8", "segment-8.ts"} {
		w := call(s, "GET", "/api/hls/v1/test/"+name+"?generation=synthetic", nil)
		if w.Code != 200 || w.Header().Get("Cache-Control") != "no-store" {
			t.Fatal("media unavailable")
		}
	}
	s.lastSegment = time.Now().Add(-15 * time.Second)
	if s.readyLocked() {
		t.Fatal("stale media declared ready")
	}
}

func TestRejectUnsafePlaylists(t *testing.T) {
	valid := "#EXTM3U\n#EXT-X-TARGETDURATION:1\n#EXT-X-MEDIA-SEQUENCE:1\n#EXTINF:1.000000,\nsegment-1.ts\n"
	for _, body := range []string{strings.ReplaceAll(valid, "segment-1.ts", "http://camera/secret"), strings.ReplaceAll(valid, "segment-1.ts", "../file"), strings.ReplaceAll(valid, "1.000000", "NaN"), strings.ReplaceAll(valid, "segment-1.ts", "segment-2.ts"), valid + "#EXT-X-MAP:URI=\"file\"\n", strings.ReplaceAll(valid, "1.000000", "100.0"), valid + "#EXTINF:1.0,\n"} {
		if _, err := parsePlaylist(body, 3); err == nil {
			t.Fatal("unsafe playlist accepted")
		}
	}
}

func TestBufferLimitNeverEvictsPromisedMedia(t *testing.T) {
	s := testServer(t)
	data := make([]byte, MaxSegmentBytes/188*188)
	for i := 0; i < len(data); i += 188 {
		data[i] = 0x47
	}
	for i := 1; i <= 4; i++ {
		if call(s, "PUT", fmt.Sprintf("/internal/hls/synthetic/segment-%d.ts", i), data).Code != 204 {
			t.Fatal("valid buffer fill failed")
		}
	}
	if call(s, "PUT", "/internal/hls/synthetic/segment-5.ts", data).Code != 413 {
		t.Fatal("buffer limit not enforced")
	}
	if s.segments["segment-1.ts"] == nil || s.segments["segment-5.ts"] != nil || s.lastError != "buffer_limit_exceeded" {
		t.Fatal("promised segment evicted")
	}
}

func TestWorkerFailureAndBoundedShutdown(t *testing.T) {
	s := testServer(t)
	s.config.Preload = true
	s.ffmpeg = "/nonexistent/synthetic-test-ffmpeg"
	s.Start()
	deadline := time.Now().Add(time.Second)
	for {
		s.mu.Lock()
		failed := s.lastError == "source_unavailable"
		s.mu.Unlock()
		if failed {
			break
		}
		if time.Now().After(deadline) {
			t.Fatal("worker failure not reported")
		}
		time.Sleep(time.Millisecond)
	}
	started := time.Now()
	s.Close()
	if time.Since(started) > time.Second {
		t.Fatal("shutdown deadline exceeded")
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.cancel != nil || s.generation != "" || len(s.segments) != 0 {
		t.Fatal("worker state not released")
	}
}

// Real FFmpeg HTTP PUT packaging/probing/snapshot; synthetic input only.
func TestFFmpegRAMOutput(t *testing.T) {
	if _, err := exec.LookPath("ffmpeg"); err != nil {
		t.Skip("ffmpeg unavailable")
	}
	if _, err := exec.LookPath("ffprobe"); err != nil {
		t.Skip("ffprobe unavailable")
	}
	s := testServer(t)
	s.info = mediaInfo{}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		recorded := httptest.NewRecorder()
		s.ServeHTTP(recorded, r)
		if recorded.Code >= 400 {
			t.Logf("synthetic upload: %s %s %d %s", r.Method, r.URL.Path, recorded.Code, recorded.Body.String())
		}
		for k, v := range recorded.Header() {
			w.Header()[k] = v
		}
		w.WriteHeader(recorded.Code)
		_, _ = w.Write(recorded.Body.Bytes())
	}))
	defer server.Close()
	s.callbackURL = server.URL
	args := []string{"-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=15", "-f", "lavfi", "-i", "anullsrc=channel_layout=mono:sample_rate=16000", "-t", "8", "-c:v", "libx264", "-profile:v", "main", "-level:v", "3.1", "-g", "15", "-keyint_min", "15", "-sc_threshold", "0", "-bf", "0", "-c:a", "aac"}
	output := s.args("synthetic")
	for i, arg := range output {
		if arg == "-f" {
			args = append(args, output[i:]...)
			break
		}
	}
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, "ffmpeg", args...)
	stderr := &bytes.Buffer{}
	cmd.Stderr = stderr
	if err := cmd.Run(); err != nil {
		t.Fatal("synthetic HLS packaging failed:", err, stderr.String())
	}
	deadline := time.Now().Add(5 * time.Second)
	for {
		s.mu.Lock()
		ready := s.readyLocked()
		info := s.info
		s.mu.Unlock()
		if ready && info.Codecs == "avc1.4d401f,mp4a.40.2" {
			break
		}
		if time.Now().After(deadline) {
			t.Fatalf("invalid output: ready=%v metadata=%+v stderr=%s", ready, info, stderr.String())
		}
		time.Sleep(10 * time.Millisecond)
	}
	image, err := s.image(ctx)
	if err != nil || len(image) < 1000 {
		t.Fatal("snapshot failed", err)
	}
	response, err := http.Get(server.URL + "/api/hls/v1/test/stream.m3u8?generation=synthetic")
	if err != nil {
		t.Fatal(err)
	}
	defer response.Body.Close()
	body, _ := io.ReadAll(response.Body)
	if response.StatusCode != 200 || strings.Contains(string(body), "http:") || strings.Contains(string(body), "EXT-X-MAP") {
		t.Fatal("invalid HLS response")
	}
	list, err := parsePlaylist(string(body), s.config.SegmentCount)
	if err != nil || list.sequence+uint64(len(list.items)) > 1<<31 {
		t.Fatal("generated sequence exceeds legacy HLS parser range")
	}
}
