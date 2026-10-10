package hassaddon

import (
	"encoding/json"
	"errors"
	"os"
	"strings"
)

const (
	optionsPath = "/data/options.json"
	configPath  = "/config/go2rtc.yaml"
)

type options struct {
	Config         string `json:"config"`
	CameraPassword string `json:"camera_password"`
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

	var opts options
	if err = json.Unmarshal(b, &opts); err != nil {
		return errors.New("invalid private app options")
	}
	if opts.Config == "" || opts.CameraPassword == "" {
		return errors.New("config and camera_password are required")
	}
	if !strings.Contains(opts.Config, "${CAMERA_PASSWORD}") {
		return errors.New("config must reference ${CAMERA_PASSWORD}")
	}
	if err = os.Setenv("CAMERA_PASSWORD", opts.CameraPassword); err != nil {
		return errors.New("cannot prepare masked camera password")
	}
	if err = os.WriteFile(configPath, []byte(opts.Config), 0600); err != nil {
		return errors.New("cannot write private configuration")
	}
	return nil
}
