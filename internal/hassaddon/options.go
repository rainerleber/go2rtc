package hassaddon

import (
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"net/url"
	"os"
	"strings"
)

const (
	optionsPath = "/data/options.json"
	configPath  = "/config/go2rtc.yaml"
)

type options struct {
	CameraAddress  string `json:"camera_address"`
	CameraUsername string `json:"camera_username"`
	CameraPassword string `json:"camera_password"`
	CameraStream   string `json:"camera_stream"`
}

// Prepare creates the app-private go2rtc configuration from Supervisor options.
// Outside a Home Assistant app it is a no-op.
func Prepare() error {
	b, err := os.ReadFile(optionsPath)
	if errors.Is(err, os.ErrNotExist) {
		return nil
	}
	if err != nil {
		return errors.New("cannot read private app options")
	}

	config, err := buildConfig(b)
	if err != nil {
		return err
	}
	if err = os.WriteFile(configPath, config, 0600); err != nil {
		return errors.New("cannot write private configuration")
	}
	return nil
}

func buildConfig(b []byte) ([]byte, error) {
	var opts options
	if err := json.Unmarshal(b, &opts); err != nil {
		return nil, errors.New("invalid private app options")
	}
	if opts.CameraAddress == "" || opts.CameraUsername == "" || opts.CameraPassword == "" {
		return nil, errors.New("camera_address, camera_username and camera_password are required")
	}
	if strings.ContainsAny(opts.CameraAddress, "/@") {
		return nil, errors.New("camera_address must be a hostname or IP address without a scheme or path")
	}

	var suffix string
	switch opts.CameraStream {
	case "main", "sub", "ext":
		suffix = opts.CameraStream
	default:
		return nil, errors.New("camera_stream must be main, sub or ext")
	}

	cameraURL := &url.URL{
		Scheme: "rtsp",
		User:   url.UserPassword(opts.CameraUsername, opts.CameraPassword),
		Host:   net.JoinHostPort(opts.CameraAddress, "554"),
		Path:   fmt.Sprintf("/h264Preview_01_%s", suffix),
	}
	config := map[string]any{
		"app":     map[string]any{"modules": []string{"api", "exec", "ffmpeg", "rtsp"}},
		"api":     map[string]string{"listen": "127.0.0.1:1984"},
		"preload": map[string]string{"reolink_haustuer_alexa": "video&audio"},
		"rtsp":    map[string]string{"listen": "127.0.0.1:8554"},
		"webrtc":  map[string]string{"listen": ""},
		"streams": map[string][]string{
			"reolink_haustuer":       {cameraURL.String()},
			"reolink_haustuer_alexa": {"ffmpeg:reolink_haustuer#video=h264#audio=aac#raw=-vf scale=960:720,pad=1280:720:160:0:black"},
		},
	}

	out, err := json.MarshalIndent(config, "", "  ")
	if err != nil {
		return nil, errors.New("cannot generate private configuration")
	}
	return append(out, '\n'), nil
}
