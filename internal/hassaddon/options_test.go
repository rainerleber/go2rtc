package hassaddon

import (
	"encoding/json"
	"strings"
	"testing"
)

type generated struct {
	Streams map[string][]string `json:"streams"`
	Preload map[string]string   `json:"preload"`
	FFmpeg  map[string]string   `json:"ffmpeg"`
	RTSP    map[string]string   `json:"rtsp"`
	API     map[string]string   `json:"api"`
	WebRTC  map[string]string   `json:"webrtc"`
	App     struct {
		Modules []string `json:"modules"`
	} `json:"app"`
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
	if c.API["listen"] != "127.0.0.1:1984" || c.RTSP["listen"] != "127.0.0.1:8554" || c.WebRTC["listen"] != "" {
		t.Fatal("listener isolation changed")
	}
	if strings.Join(c.App.Modules, ",") != "api,exec,ffmpeg,rtsp" {
		t.Fatal("wrong modules")
	}
	if !strings.Contains(c.FFmpeg["h264"], "-g:v 15") || !strings.Contains(c.FFmpeg["h264"], "-bf 0") {
		t.Fatal("low-latency encoder missing")
	}
	if strings.Contains(c.Streams["reolink_haustuer_alexa"][0], "p@ss") {
		t.Fatal("secret passed to FFmpeg")
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
