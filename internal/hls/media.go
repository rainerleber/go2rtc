package hls

import (
	"bytes"
	"context"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"os/exec"
	"regexp"
	"strings"
	"time"
)

var dumpLine = regexp.MustCompile(`(?m)^[0-9a-f]{8}: ([0-9a-f ]+?)  `)

type boundedOutput struct {
	bytes.Buffer
	limit int
}

func (b *boundedOutput) Write(p []byte) (int, error) {
	if b.Len()+len(p) > b.limit {
		return 0, errors.New("media output limit")
	}
	return b.Buffer.Write(p)
}

func command(ctx context.Context, binary string, data []byte, limit int, args ...string) ([]byte, error) {
	ctx, cancel := context.WithTimeout(ctx, 5*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, binary, args...)
	cmd.WaitDelay = time.Second
	cmd.Stdin = bytes.NewReader(data)
	output := &boundedOutput{limit: limit}
	cmd.Stdout = output
	if err := cmd.Run(); err != nil {
		return nil, errors.New("media command failed")
	}
	return output.Bytes(), nil
}

func probe(ctx context.Context, binary string, data []byte) (mediaInfo, error) {
	var info mediaInfo
	b, err := command(ctx, binary, data, MaxPlaylistBytes, "-v", "error", "-f", "mpegts", "-show_entries", "stream=codec_type,codec_name,width,height,profile,sample_rate,extradata", "-show_data", "-of", "json", "pipe:0")
	if err != nil {
		return info, err
	}
	var result struct {
		Streams []struct {
			CodecType  string `json:"codec_type"`
			CodecName  string `json:"codec_name"`
			Width      int    `json:"width"`
			Height     int    `json:"height"`
			Profile    string `json:"profile"`
			SampleRate string `json:"sample_rate"`
			ExtraData  string `json:"extradata"`
		} `json:"streams"`
	}
	if json.Unmarshal(b, &result) != nil {
		return info, errors.New("invalid media metadata")
	}
	video, audio := 0, 0
	for _, stream := range result.Streams {
		switch stream.CodecType {
		case "video":
			video++
			if stream.CodecName != "h264" || stream.Width < 1 || stream.Width > 1920 || stream.Height < 1 || stream.Height > 1080 || (stream.Profile != "Main" && stream.Profile != "High" && stream.Profile != "Constrained Baseline" && stream.Profile != "Baseline") {
				return info, errors.New("incompatible video")
			}
			info.Width, info.Height = stream.Width, stream.Height
			hexData := ""
			for _, match := range dumpLine.FindAllStringSubmatch(stream.ExtraData, -1) {
				hexData += strings.ReplaceAll(match[1], " ", "")
			}
			extra, _ := hex.DecodeString(hexData)
			for i := 0; i+6 < len(extra); i++ {
				if extra[i] == 0 && extra[i+1] == 0 && extra[i+2] == 1 && extra[i+3]&31 == 7 {
					info.Codecs = fmt.Sprintf("avc1.%02x%02x%02x,mp4a.40.2", extra[i+4], extra[i+5], extra[i+6])
					break
				}
			}
		case "audio":
			audio++
			if stream.CodecName != "aac" || stream.Profile != "LC" {
				return info, errors.New("incompatible audio")
			}
		}
	}
	if video != 1 || audio != 1 || info.Codecs == "" {
		return info, errors.New("missing compatible media")
	}
	return info, nil
}

func (s *Server) image(ctx context.Context) ([]byte, error) {
	s.snapshotMu.Lock()
	defer s.snapshotMu.Unlock()
	s.mu.Lock()
	generation := s.generation
	if !s.readyLocked() {
		s.mu.Unlock()
		return nil, errors.New("stream not ready")
	}
	data := s.segments[s.list.items[len(s.list.items)-1].name]
	s.mu.Unlock()
	if s.snapshotGeneration == generation && time.Since(s.snapshotAt) < 3*time.Second {
		return s.snapshot, nil
	}
	image, err := command(ctx, s.ffmpeg, data, MaxImageBytes, "-hide_banner", "-loglevel", "error", "-nostdin", "-f", "mpegts", "-i", "pipe:0", "-map", "0:v:0", "-frames:v", "1", "-f", "image2pipe", "-c:v", "mjpeg", "pipe:1")
	if err != nil || len(image) < 4 || image[0] != 0xff || image[1] != 0xd8 {
		return nil, errors.New("snapshot unavailable")
	}
	s.mu.Lock()
	current := s.generation
	s.mu.Unlock()
	if current != generation {
		return nil, errors.New("generation expired")
	}
	s.snapshot, s.snapshotGeneration, s.snapshotAt = image, generation, time.Now()
	return image, nil
}
