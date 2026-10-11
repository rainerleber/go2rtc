package hassaddon

import (
	"strings"
	"testing"
)

func TestBuildConfig(t *testing.T) {
	b := []byte(`{"camera_address":"192.0.2.10","camera_username":"viewer","camera_password":"p@ss:word","camera_stream":"sub"}`)
	config, err := buildConfig(b)
	if err != nil {
		t.Fatal(err)
	}

	want := "rtsp://viewer:p%40ss%3Aword@192.0.2.10:554/h264Preview_01_sub"
	if !strings.Contains(string(config), want) {
		t.Fatalf("generated config does not contain escaped camera URL: %s", config)
	}
	if !strings.Contains(string(config), `"listen": "127.0.0.1:8554"`) {
		t.Fatalf("RTSP listener is not loopback-only: %s", config)
	}
	if !strings.Contains(string(config), `"exec"`) {
		t.Fatalf("FFmpeg sources require the exec module: %s", config)
	}
	if !strings.Contains(string(config), "ffmpeg:"+want+"#video=h264#audio=aac") {
		t.Fatalf("Alexa stream must transcode directly from the camera URL: %s", config)
	}
}

func TestBuildConfigRejectsInvalidOptions(t *testing.T) {
	tests := []string{
		`{}`,
		`{"camera_address":"rtsp://camera","camera_username":"viewer","camera_password":"secret","camera_stream":"sub"}`,
		`{"camera_address":"camera","camera_username":"viewer","camera_password":"secret","camera_stream":"invalid"}`,
	}
	for _, input := range tests {
		if _, err := buildConfig([]byte(input)); err == nil {
			t.Fatalf("expected error for %s", input)
		}
	}
}
