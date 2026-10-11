package hassaddon

import (
	"encoding/json"
	"os"
	"strings"
	"testing"

	"gopkg.in/yaml.v3"
)

type generated struct {
	Streams map[string][]string `json:"streams"`
	Preload map[string]string   `json:"preload"`
	FFmpeg  map[string]string   `json:"ffmpeg"`
	RTSP    map[string]string   `json:"rtsp"`
	API     map[string]string   `json:"api"`
}

func generate(t *testing.T, input string) generated {
	t.Helper()
	b, err := buildConfig([]byte(input))
	if err != nil {
		t.Fatal(err)
	}
	var c generated
	if err = json.Unmarshal(b, &c); err != nil {
		t.Fatal(err)
	}
	return c
}
func TestBuildConfigLegacyMigration(t *testing.T) {
	c := generate(t, `{"camera_address":"192.0.2.10","camera_username":"viewer","camera_password":"p@ss:word","camera_stream":"sub"}`)
	if c.Streams["reolink_haustuer"][0] != "rtsp://viewer:p%40ss%3Aword@192.0.2.10:554/h264Preview_01_sub" {
		t.Fatal("credential escaping or migration failed")
	}
	if c.Streams["reolink_haustuer_alexa"][0] != "ffmpeg:reolink_haustuer#input=app_rtsp#video=h264#audio=aac#raw=app_scale" {
		t.Fatal("shared local input missing")
	}
	if c.Preload["reolink_haustuer_alexa"] != "video&audio" {
		t.Fatal("preload missing")
	}
	if c.API["listen"] != "127.0.0.1:1984" || c.RTSP["listen"] != "127.0.0.1:8554" {
		t.Fatal("listener isolation changed")
	}
	if !strings.Contains(c.FFmpeg["h264"], "-g:v 15") || !strings.Contains(c.FFmpeg["h264"], "-bf 0") {
		t.Fatal("low-latency encoder missing")
	}
	if !strings.Contains(c.FFmpeg["app_scale"], "-map 0:v:0 -map 0:a:0?") {
		t.Fatal("video must be required, audio optional")
	}
	if strings.Contains(c.Streams["reolink_haustuer_alexa"][0], "p@ss") {
		t.Fatal("secret passed to FFmpeg")
	}
}

func TestSupervisorDefaultsPreserveLegacyConfiguration(t *testing.T) {
	// Supervisor merges new defaults into installed options before the binary
	// runs. Exercise the real schema defaults, not just a four-field fixture.
	b, err := os.ReadFile("../../home-assistant/config.yaml")
	if err != nil {
		t.Fatal(err)
	}
	var appConfig struct {
		Options map[string]any `yaml:"options"`
	}
	if err = yaml.Unmarshal(b, &appConfig); err != nil {
		t.Fatal(err)
	}
	for key, value := range map[string]any{"camera_address": "192.0.2.10", "camera_username": "viewer", "camera_password": "test-password", "camera_stream": "sub"} {
		appConfig.Options[key] = value
	}
	b, err = json.Marshal(appConfig.Options)
	if err != nil {
		t.Fatal(err)
	}
	c := generate(t, string(b))
	if len(c.Streams["reolink_haustuer_alexa"]) != 1 || !strings.HasSuffix(c.Streams["reolink_haustuer"][0], "/h264Preview_01_sub") {
		t.Fatal("Supervisor defaults broke legacy stream paths/names")
	}
}
func TestBuildConfigGeneric(t *testing.T) {
	c := generate(t, `{"camera_address":"2001:db8::1","camera_port":8554,"camera_path":"/live%20video?channel=2","source_name":"yard","output_name":"yard_ready","video_width":640,"video_height":480,"video_fps":20,"keyframe_seconds":2,"video_bitrate_kbps":700}`)
	if c.Streams["yard"][0] != "rtsp://[2001:db8::1]:8554/live%20video?channel=2" {
		t.Fatal("generic RTSP source failed")
	}
	if !strings.Contains(c.FFmpeg["h264"], "-g:v 40") || !strings.Contains(c.FFmpeg["h264"], "-b:v 700k") {
		t.Fatal("encoder options ignored")
	}
	if !strings.Contains(c.FFmpeg["app_scale"], "scale=640:480:force_original_aspect_ratio=decrease") {
		t.Fatal("generic scaling missing")
	}
}

func TestH264LevelMatchesValidatedOutput(t *testing.T) {
	for _, tc := range []struct {
		width, height, fps int
		level              string
	}{
		{640, 480, 30, "3.1"},
		{1280, 720, 15, "3.1"},
		{1280, 720, 30, "3.1"},
		{1280, 722, 30, "4.0"},
		{1920, 1080, 30, "4.0"},
	} {
		o := options{VideoWidth: tc.width, VideoHeight: tc.height, VideoFPS: tc.fps}
		if got := o.h264Level(); got != tc.level {
			t.Errorf("%dx%d@%d: level %s, want %s", tc.width, tc.height, tc.fps, got, tc.level)
		}
	}
	c := generate(t, `{"camera_address":"camera.test","camera_path":"/live"}`)
	if !strings.Contains(c.FFmpeg["h264"], "-level:v 3.1") {
		t.Fatal("default 720p output must not require a Level 4.1 decoder")
	}
}

func TestBuildConfigPassthrough(t *testing.T) {
	c := generate(t, `{"camera_address":"camera.test","camera_path":"/live","output_mode":"passthrough","preload":false}`)
	if len(c.FFmpeg) != 0 || len(c.Preload) != 0 || c.Streams["camera_compatible"][0] != "rtsp://127.0.0.1:8554/camera" {
		t.Fatal("passthrough must avoid encoder and share local source")
	}
}
func TestBuildConfigRejectsInvalidOptions(t *testing.T) {
	cases := []string{`{}`, `{"camera_address":"rtsp://secret","camera_path":"/live"}`, `{"camera_address":"camera","camera_stream":"invalid"}`, `{"camera_address":"camera","camera_path":"//secret"}`, `{"camera_address":"camera","camera_path":"/live#exec=secret"}`, `{"camera_address":"camera","camera_path":"/live","source_name":"secret #raw=exec"}`, `{"camera_address":"camera","camera_path":"/live","source_name":"same","output_name":"same"}`, `{"camera_address":"camera","camera_path":"/live","video_width":641}`, `{"camera_address":"camera","camera_path":"/live","video_fps":31}`, `{"camera_address":"camera","camera_path":"/live","camera_port":65536}`, `{"camera_address":"camera","camera_path":"/live","video_bitrate_kbps":1}`, `{"camera_address":"camera","camera_path":"/live","keyframe_seconds":6}`, `{"camera_address":"camera","camera_path":"/live","output_mode":"secret"}`, `{"camera_address":"camera","camera_path":"/live","camera_password":"secret"}`}
	for _, input := range cases {
		_, err := buildConfig([]byte(input))
		if err == nil {
			t.Fatal("invalid options accepted")
		}
		if strings.Contains(err.Error(), "secret") {
			t.Fatal("error leaked option values")
		}
	}
}
