package hassaddon

import (
	"encoding/json"
	"errors"
	"net"
	"net/url"
	"os"
)

const (
	optionsPath = "/data/options.json"
	configPath  = "/config/go2rtc.yaml"
)

type options struct {
	CameraHost     string `json:"camera_host"`
	CameraUsername string `json:"camera_username"`
	CameraPassword string `json:"camera_password"`
}

// Prepare creates the app-private go2rtc configuration from Supervisor options.
// Outside a Home Assistant app, or when a manual config already exists, it is a no-op.
func Prepare() error {
	if _, err := os.Stat(configPath); err == nil {
		return nil
	} else if !errors.Is(err, os.ErrNotExist) {
		return errors.New("cannot inspect private configuration")
	}

	b, err := os.ReadFile(optionsPath)
	if errors.Is(err, os.ErrNotExist) {
		return nil
	}
	if err != nil {
		return errors.New("cannot read private app options")
	}

	var opts options
	if err = json.Unmarshal(b, &opts); err != nil {
		return errors.New("invalid private app options")
	}
	if opts.CameraHost == "" || opts.CameraUsername == "" || opts.CameraPassword == "" {
		return errors.New("camera_host, camera_username and camera_password are required")
	}

	source := (&url.URL{
		Scheme: "rtsp",
		User:   url.UserPassword(opts.CameraUsername, opts.CameraPassword),
		Host:   net.JoinHostPort(opts.CameraHost, "554"),
		Path:   "/h264Preview_01_sub",
	}).String()

	config := map[string]any{
		"app": map[string]any{"modules": []string{"api", "ffmpeg", "rtsp"}},
		"api": map[string]any{"listen": "127.0.0.1:1984"},
		"rtsp": map[string]any{"listen": "127.0.0.1:8554"},
		"webrtc": map[string]any{"listen": ""},
		"streams": map[string]any{
			"reolink_haustuer": source,
			"reolink_haustuer_alexa": "ffmpeg:reolink_haustuer#video=h264#audio=aac#raw=-vf scale=960:720,pad=1280:720:160:0:black",
		},
	}

	b, err = json.MarshalIndent(config, "", "  ")
	if err != nil {
		return errors.New("cannot build private configuration")
	}
	if err = os.WriteFile(configPath, b, 0600); err != nil {
		return errors.New("cannot write private configuration")
	}
	return nil
}
