// Package hls supplies the HA app's private, RAM-only MPEG-TS HLS backend.
// HA owns public authentication and signing; this API must remain loopback-only.
package hls

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math"
	"net"
	"net/http"
	"os/exec"
	"regexp"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/rainerleber/go2rtc/internal/api"
	"github.com/rainerleber/go2rtc/internal/app"
	"github.com/rainerleber/go2rtc/internal/rtsp"
)

const (
	MaxSegmentBytes  = 4 << 20
	MaxBufferBytes   = 16 << 20
	MaxImageBytes    = 2 << 20
	MaxPlaylistBytes = 64 << 10
	staleTimeout     = 8 * time.Second
	idleTimeout      = 60 * time.Second
)

var (
	streamName  = regexp.MustCompile(`^[A-Za-z0-9_-]{1,64}$`)
	segmentName = regexp.MustCompile(`^segment-([0-9]{1,20})\.ts$`)
	active      *Server
)

type Config struct {
	Stream         string `yaml:"stream"`
	SegmentSeconds int    `yaml:"segment_seconds"`
	SegmentCount   int    `yaml:"segment_count"`
	Preload        bool   `yaml:"preload"`
}

type item struct {
	name     string
	duration float64
}
type playlist struct {
	target   int
	sequence uint64
	items    []item
}
type mediaInfo struct {
	Width  int    `json:"width"`
	Height int    `json:"height"`
	Codecs string `json:"codecs"`
}

// Server owns a single configured output, never a caller-provided source URL.
type Server struct {
	config                              Config
	callbackURL, input, ffmpeg, ffprobe string
	mu                                  sync.Mutex
	ingestMu                            sync.Mutex
	cancel                              context.CancelFunc
	done                                chan struct{}
	generation                          string
	uploadToken                         string
	segments                            map[string][]byte
	expires                             map[string]time.Time
	maxWindow                           map[string]float64
	list                                playlist
	info                                mediaInfo
	lastRequest, lastSegment            time.Time
	lastError                           string
	snapshotMu                          sync.Mutex
	snapshot                            []byte
	snapshotGeneration                  string
	snapshotAt                          time.Time
}

// Init is intentionally disabled in RTSP-only native test configurations.
func Init() {
	var cfg struct {
		HLS Config `yaml:"hls"`
	}
	app.LoadConfig(&cfg)
	if cfg.HLS.Stream == "" {
		return
	}
	port, _ := strconv.Atoi(rtsp.Port)
	s, err := New(cfg.HLS, fmt.Sprintf("http://127.0.0.1:%d", api.Port), port)
	if err != nil {
		log := app.GetLogger("hls")
		log.Error().Msg("invalid private HLS configuration")
		return
	}
	active = s
	api.HandleFunc("api/hls/v1/", s.ServeHTTP)
	api.HandleFunc("internal/hls/", s.ServeHTTP)
	if cfg.HLS.Preload {
		s.Start()
	}
}

func Close() {
	if active != nil {
		active.Close()
	}
}

func New(cfg Config, callbackURL string, rtspPort int) (*Server, error) {
	if !streamName.MatchString(cfg.Stream) || cfg.SegmentSeconds < 1 || cfg.SegmentSeconds > 3 || cfg.SegmentCount < 3 || cfg.SegmentCount > 10 || rtspPort < 1 || rtspPort > 65535 {
		return nil, errors.New("invalid private HLS configuration")
	}
	return &Server{config: cfg, callbackURL: callbackURL, input: fmt.Sprintf("rtsp://127.0.0.1:%d/%s", rtspPort, cfg.Stream), ffmpeg: "ffmpeg", ffprobe: "ffprobe", segments: make(map[string][]byte), expires: make(map[string]time.Time), maxWindow: make(map[string]float64)}, nil
}

func token() string {
	var b [16]byte
	if _, err := rand.Read(b[:]); err != nil {
		panic("cannot create private media generation")
	}
	return hex.EncodeToString(b[:])
}

func (s *Server) Start() {
	s.mu.Lock()
	s.lastRequest = time.Now()
	if s.cancel != nil {
		s.mu.Unlock()
		return
	}
	ctx, cancel := context.WithCancel(context.Background())
	s.cancel, s.done = cancel, make(chan struct{})
	done := s.done
	s.mu.Unlock()
	go s.run(ctx, done)
}

func (s *Server) Close() {
	s.mu.Lock()
	cancel, done := s.cancel, s.done
	s.mu.Unlock()
	if cancel != nil {
		cancel()
		<-done
	}
}

func (s *Server) resetLocked(generation string) {
	s.generation = generation
	s.uploadToken = ""
	if generation != "" {
		s.uploadToken = token()
	}
	s.segments = make(map[string][]byte)
	s.expires = make(map[string]time.Time)
	s.maxWindow = make(map[string]float64)
	s.list = playlist{}
	s.info = mediaInfo{}
	s.lastSegment = time.Time{}
}

func (s *Server) run(ctx context.Context, done chan struct{}) {
	defer func() { s.mu.Lock(); s.cancel = nil; s.resetLocked(""); close(done); s.mu.Unlock() }()
	backoff := time.Second
	for ctx.Err() == nil {
		s.mu.Lock()
		if !s.config.Preload && time.Since(s.lastRequest) > idleTimeout {
			s.mu.Unlock()
			return
		}
		s.resetLocked(token())
		uploadToken := s.uploadToken
		s.lastError = "starting"
		s.mu.Unlock()
		workerCtx, cancel := context.WithCancel(ctx)
		cmd := exec.CommandContext(workerCtx, s.ffmpeg, s.args(uploadToken)...)
		// FFmpeg errors can contain its input URL or private upload capability.
		// Neither arguments, stderr nor arbitrary exception text are exported.
		cmd.Stdout, cmd.Stderr = io.Discard, io.Discard
		cmd.WaitDelay = 2 * time.Second
		started := time.Now()
		finished := make(chan error, 1)
		if err := cmd.Start(); err != nil {
			finished <- err
		} else {
			go func() { finished <- cmd.Wait() }()
		}
		ticker := time.NewTicker(time.Second)
		waiting := true
		for waiting {
			select {
			case <-finished:
				waiting = false
			case <-ctx.Done():
				cancel()
			case <-ticker.C:
				s.mu.Lock()
				last := s.lastSegment
				if last.IsZero() {
					last = started
				}
				idle := !s.config.Preload && time.Since(s.lastRequest) > idleTimeout
				stale := time.Since(last) > staleTimeout+time.Duration(s.config.SegmentSeconds)*time.Second
				s.mu.Unlock()
				if idle || stale {
					cancel()
				}
			}
		}
		ticker.Stop()
		cancel()
		s.mu.Lock()
		s.resetLocked("")
		s.lastError = "source_unavailable"
		s.mu.Unlock()
		if time.Since(started) > 60*time.Second {
			backoff = time.Second
		}
		timer := time.NewTimer(backoff)
		select {
		case <-ctx.Done():
			timer.Stop()
			return
		case <-timer.C:
		}
		backoff = min(backoff*2, 15*time.Second)
	}
}

func (s *Server) args(uploadToken string) []string {
	base := s.callbackURL + "/internal/hls/" + uploadToken + "/"
	return []string{"-hide_banner", "-loglevel", "error", "-nostdin", "-rtsp_transport", "tcp", "-timeout", "5000000", "-analyzeduration", "250000", "-probesize", "262144", "-i", s.input,
		"-map", "0:v:0", "-map", "0:a:0", "-c", "copy", "-avoid_negative_ts", "make_zero", "-f", "hls", "-hls_segment_type", "mpegts",
		"-hls_time", strconv.Itoa(s.config.SegmentSeconds), "-hls_list_size", strconv.Itoa(s.config.SegmentCount),
		"-hls_flags", "independent_segments+omit_endlist", "-start_number", strconv.FormatInt(time.Now().UnixMicro(), 10),
		"-method", "PUT", "-http_persistent", "0", "-hls_segment_filename", base + "segment-%d.ts", base + "index.m3u8"}
}

func loopback(r *http.Request) bool {
	host, _, err := net.SplitHostPort(r.RemoteAddr)
	return err == nil && net.ParseIP(host).IsLoopback()
}

func (s *Server) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	_ = http.NewResponseController(w).SetWriteDeadline(time.Now().Add(5 * time.Second))
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("X-Content-Type-Options", "nosniff")
	if !loopback(r) {
		http.Error(w, "forbidden", http.StatusForbidden)
		return
	}
	if strings.HasPrefix(r.URL.Path, "/internal/hls/") {
		s.ingest(w, r)
		return
	}
	base := "/api/hls/v1/" + s.config.Stream + "/"
	if !strings.HasPrefix(r.URL.Path, base) {
		http.NotFound(w, r)
		return
	}
	name := strings.TrimPrefix(r.URL.Path, base)
	if name == "start" && r.Method == http.MethodPost {
		s.Start()
		w.WriteHeader(http.StatusNoContent)
		return
	}
	if r.Method != http.MethodGet && r.Method != http.MethodHead {
		w.Header().Set("Allow", "GET, HEAD")
		http.Error(w, "method not allowed", 405)
		return
	}
	if name == "snapshot.jpg" {
		s.Start()
		image, err := s.image(r.Context())
		if err != nil {
			http.Error(w, "snapshot unavailable", 503)
			return
		}
		w.Header().Set("Content-Type", "image/jpeg")
		_, _ = w.Write(image)
		return
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	ready := s.readyLocked()
	if name == "status" {
		w.Header().Set("Content-Type", "application/json")
		bytes := 0
		for _, data := range s.segments {
			bytes += len(data)
		}
		_ = json.NewEncoder(w).Encode(map[string]any{"api_version": 1, "generation": s.generation, "ready": ready, "running": s.cancel != nil, "segment_seconds": s.config.SegmentSeconds, "segment_count": s.config.SegmentCount, "buffer_segments": len(s.segments), "buffer_bytes": bytes, "last_error": s.lastError, "media": s.info})
		return
	}
	if r.URL.Query().Get("generation") != s.generation || s.generation == "" {
		http.Error(w, "generation expired", 410)
		return
	}
	s.lastRequest = time.Now()
	if !ready {
		w.Header().Set("Retry-After", "1")
		http.Error(w, "stream not ready", 503)
		return
	}
	w.Header().Set("X-HLS-Generation", s.generation)
	switch name {
	case "master.m3u8":
		w.Header().Set("Content-Type", "application/vnd.apple.mpegurl")
		bytes, seconds := 0, 0.0
		for _, entry := range s.list.items {
			bytes += len(s.segments[entry.name])
			seconds += entry.duration
		}
		bandwidth := max(400000, int(math.Ceil(float64(bytes)*8/seconds*1.5)))
		_, _ = fmt.Fprintf(w, "#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-STREAM-INF:BANDWIDTH=%d,CODECS=\"%s\",RESOLUTION=%dx%d\nstream.m3u8\n", bandwidth, s.info.Codecs, s.info.Width, s.info.Height)
	case "stream.m3u8":
		w.Header().Set("Content-Type", "application/vnd.apple.mpegurl")
		_, _ = fmt.Fprintf(w, "#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:%d\n#EXT-X-MEDIA-SEQUENCE:%d\n", s.list.target, s.list.sequence)
		for _, entry := range s.list.items {
			_, _ = fmt.Fprintf(w, "#EXTINF:%.6f,\n%s\n", entry.duration, entry.name)
		}
	default:
		if !segmentName.MatchString(name) {
			http.NotFound(w, r)
			return
		}
		data := s.segments[name]
		if data == nil {
			http.NotFound(w, r)
			return
		}
		w.Header().Set("Content-Type", "video/mp2t")
		_, _ = w.Write(data)
	}
}

func (s *Server) readyLocked() bool {
	if s.info.Codecs == "" || s.list.target < 1 || time.Since(s.lastSegment) > staleTimeout+time.Duration(s.config.SegmentSeconds)*time.Second {
		return false
	}
	duration := 0.0
	for _, entry := range s.list.items {
		if s.segments[entry.name] == nil {
			return false
		}
		duration += entry.duration
	}
	return duration >= float64(s.list.target*3)-0.01
}

func (s *Server) ingest(w http.ResponseWriter, r *http.Request) {
	parts := strings.Split(strings.TrimPrefix(r.URL.Path, "/internal/hls/"), "/")
	if len(parts) != 2 {
		http.NotFound(w, r)
		return
	}
	s.mu.Lock()
	valid := parts[0] == s.uploadToken && s.uploadToken != ""
	s.mu.Unlock()
	if !valid {
		http.NotFound(w, r)
		return
	}
	if r.Method != http.MethodPut {
		http.Error(w, "method not allowed", 405)
		return
	}
	// At most one upload body/probe is held outside the bounded media ring.
	s.ingestMu.Lock()
	defer s.ingestMu.Unlock()
	s.mu.Lock()
	valid = parts[0] == s.uploadToken && s.uploadToken != ""
	s.mu.Unlock()
	if !valid {
		http.Error(w, "generation expired", 410)
		return
	}
	name := parts[1]
	limit := MaxSegmentBytes
	if name == "index.m3u8" {
		limit = MaxPlaylistBytes
	} else if !segmentName.MatchString(name) {
		http.NotFound(w, r)
		return
	}
	_ = http.NewResponseController(w).SetReadDeadline(time.Now().Add(5 * time.Second))
	data, err := io.ReadAll(http.MaxBytesReader(w, r.Body, int64(limit)))
	if err != nil {
		s.uploadFailed(parts[0], "segment_too_large")
		http.Error(w, "media too large or incomplete", 413)
		return
	}
	if name == "index.m3u8" {
		list, err := parsePlaylist(string(data), s.config.SegmentCount)
		if err != nil {
			http.Error(w, "invalid playlist", 400)
			return
		}
		s.mu.Lock()
		defer s.mu.Unlock()
		if parts[0] != s.uploadToken {
			http.Error(w, "generation expired", 410)
			return
		}
		// Uploads can finish out of order. Publication waits for every segment;
		// an older playlist must never move the live window backwards.
		if list.sequence+uint64(len(list.items)) >= s.list.sequence+uint64(len(s.list.items)) {
			window := 0.0
			for _, entry := range s.list.items {
				window += entry.duration
			}
			current := make(map[string]bool, len(list.items))
			for _, entry := range list.items {
				current[entry.name] = true
			}
			// RFC 8216: removed segments remain available for their duration plus
			// the longest playlist that contained them. Never silently evict a
			// promised URL to meet the memory cap; reject the new upload instead.
			for _, entry := range s.list.items {
				if !current[entry.name] && s.segments[entry.name] != nil {
					s.expires[entry.name] = time.Now().Add(time.Duration((max(window, s.maxWindow[entry.name]) + entry.duration) * float64(time.Second)))
				}
			}
			window = 0
			for _, entry := range list.items {
				window += entry.duration
			}
			for _, entry := range list.items {
				if s.segments[entry.name] != nil {
					s.expires[entry.name] = time.Time{}
					s.maxWindow[entry.name] = max(window, s.maxWindow[entry.name])
				}
			}
			s.list = list
		}
		if s.readyLocked() {
			s.lastError = ""
		}
		w.WriteHeader(204)
		return
	}
	if len(data) < 188*4 || len(data)%188 != 0 {
		http.Error(w, "invalid transport stream", 400)
		return
	}
	for i := 0; i < len(data); i += 188 {
		if data[i] != 0x47 {
			http.Error(w, "invalid transport stream", 400)
			return
		}
	}
	s.mu.Lock()
	needsInfo := s.info.Codecs == ""
	s.mu.Unlock()
	var info mediaInfo
	if needsInfo {
		// FFmpeg closes a non-persistent upload as soon as the body is sent;
		// its request context can already be cancelled before we probe it.
		// The probe has its own hard deadline and generation is rechecked below.
		info, err = probe(context.Background(), s.ffprobe, data)
		if err != nil {
			s.uploadFailed(parts[0], "incompatible_media")
			http.Error(w, "incompatible media", 422)
			return
		}
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if parts[0] != s.uploadToken {
		http.Error(w, "generation expired", 410)
		return
	}
	if needsInfo {
		s.info = info
	}
	bytes := 0
	for key, b := range s.segments {
		if expiry := s.expires[key]; !expiry.IsZero() && time.Now().After(expiry) {
			delete(s.segments, key)
			delete(s.expires, key)
			delete(s.maxWindow, key)
		} else {
			bytes += len(b)
		}
	}
	bytes += len(data) - len(s.segments[name])
	if bytes > MaxBufferBytes || (s.segments[name] == nil && len(s.segments) >= 3*s.config.SegmentCount+2) {
		s.lastError = "buffer_limit_exceeded"
		http.Error(w, "media buffer limit", 413)
		return
	}
	s.segments[name] = data
	if _, ok := s.expires[name]; !ok {
		s.expires[name] = time.Now().Add(time.Duration(3*s.config.SegmentCount*s.config.SegmentSeconds) * time.Second)
	}
	window, current := 0.0, false
	for _, entry := range s.list.items {
		window += entry.duration
		if entry.name == name {
			current = true
		}
	}
	if current {
		s.expires[name] = time.Time{}
		s.maxWindow[name] = max(window, s.maxWindow[name])
	}
	s.lastSegment = time.Now()
	if s.readyLocked() {
		s.lastError = ""
	}
	w.WriteHeader(204)
}

func (s *Server) uploadFailed(capability, code string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if capability == s.uploadToken {
		s.lastError = code
	}
}

func parsePlaylist(body string, maxCount int) (playlist, error) {
	var out playlist
	if !strings.HasPrefix(body, "#EXTM3U\n") || len(body) > MaxPlaylistBytes {
		return out, errors.New("invalid playlist")
	}
	pending := 0.0
	for _, line := range strings.Split(body, "\n") {
		var err error
		switch {
		case strings.HasPrefix(line, "#EXT-X-TARGETDURATION:"):
			out.target, err = strconv.Atoi(strings.TrimPrefix(line, "#EXT-X-TARGETDURATION:"))
		case strings.HasPrefix(line, "#EXT-X-MEDIA-SEQUENCE:"):
			out.sequence, err = strconv.ParseUint(strings.TrimPrefix(line, "#EXT-X-MEDIA-SEQUENCE:"), 10, 64)
		case strings.HasPrefix(line, "#EXTINF:"):
			if pending != 0 {
				return out, errors.New("invalid playlist")
			}
			pending, err = strconv.ParseFloat(strings.TrimSuffix(strings.TrimPrefix(line, "#EXTINF:"), ","), 64)
		case line == "" || line == "#EXTM3U" || line == "#EXT-X-VERSION:3" || line == "#EXT-X-VERSION:6" || line == "#EXT-X-INDEPENDENT-SEGMENTS" || line == "#EXT-X-ENDLIST":
		default:
			match := segmentName.FindStringSubmatch(line)
			if match == nil || pending <= 0 || math.IsNaN(pending) || math.IsInf(pending, 0) || pending > 10 || len(out.items) >= maxCount {
				return out, errors.New("invalid playlist")
			}
			seq, e := strconv.ParseUint(match[1], 10, 64)
			if e != nil || seq != out.sequence+uint64(len(out.items)) {
				return out, errors.New("invalid sequence")
			}
			out.items = append(out.items, item{line, pending})
			pending = 0
		}
		if err != nil {
			return out, errors.New("invalid playlist")
		}
	}
	if out.target < 1 || out.target > 10 || len(out.items) == 0 || pending != 0 || out.sequence > ^uint64(0)-uint64(maxCount) {
		return out, errors.New("invalid playlist")
	}
	for _, entry := range out.items {
		if math.Round(entry.duration) > float64(out.target) {
			return out, errors.New("invalid target duration")
		}
	}
	return out, nil
}
