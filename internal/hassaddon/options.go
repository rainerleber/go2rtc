package hassaddon

import (
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"net/url"
	"os"
	"regexp"
	"strconv"
	"strings"
)

const (
	optionsPath = "/data/options.json"
	configPath  = "/config/go2rtc.yaml"
)

// Structured RTSP options deliberately exclude executable URLs and raw FFmpeg arguments.
type options struct {
	CameraAddress  string `json:"camera_address"`
	CameraPort     int    `json:"camera_port"`
	CameraPath     string `json:"camera_path"`
	CameraUsername string `json:"camera_username"`
	CameraPassword string `json:"camera_password"`
	SourceName     string `json:"source_name"`
	OutputName     string `json:"output_name"`
	OutputMode     string `json:"output_mode"`
	Preload        *bool  `json:"preload"`
	VideoWidth     int    `json:"video_width"`
	VideoHeight    int    `json:"video_height"`
	VideoFPS       int    `json:"video_fps"`
	KeyframeSecs   int    `json:"keyframe_seconds"`
	VideoBitrate   int    `json:"video_bitrate_kbps"`
	CameraStream   string `json:"camera_stream"` // legacy migration only
}

var streamName = regexp.MustCompile(`^[A-Za-z0-9_-]{1,64}$`)

// Prepare creates the app-private configuration. Without Supervisor options,
// explicit native config is still accepted for isolated runtime tests.
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
	if err = os.Chmod(configPath, 0600); err != nil {
		return errors.New("cannot restrict private configuration permissions")
	}
	return nil
}
func buildConfig(b []byte) ([]byte, error) {
	var o options
	if err := json.Unmarshal(b, &o); err != nil {
		return nil, errors.New("invalid private app options")
	}
	if err := o.defaults(); err != nil {
		return nil, err
	}
	if err := o.validate(); err != nil {
		return nil, err
	}
	path, _ := url.Parse(o.CameraPath)
	u := &url.URL{Scheme: "rtsp", Host: net.JoinHostPort(o.CameraAddress, strconv.Itoa(o.CameraPort)), Path: path.Path, RawPath: path.RawPath, RawQuery: path.RawQuery}
	if o.CameraUsername != "" {
		u.User = url.UserPassword(o.CameraUsername, o.CameraPassword)
	}
	config := map[string]any{
		"api":  map[string]string{"listen": "127.0.0.1:1984"},
		"rtsp": map[string]string{"listen": "127.0.0.1:8554"},
	}
	stream := "rtsp://127.0.0.1:8554/" + o.SourceName
	if o.OutputMode == "h264_aac" {
		gop := o.VideoFPS * o.KeyframeSecs
		// FFmpeg connects to the local shared source, keeping camera credentials out of its argv.
		config["ffmpeg"] = map[string]string{
			"app_rtsp": "-fflags nobuffer -flags low_delay -analyzeduration 250000 -probesize 262144 -timeout {timeout} -rtsp_transport tcp -i {input}",
			"h264":     fmt.Sprintf("-c:v libx264 -profile:v main -level:v %s -preset:v superfast -tune:v zerolatency -pix_fmt:v yuv420p -bf 0 -r:v %d -g:v %d -keyint_min:v %d -sc_threshold:v 0 -b:v %dk -maxrate:v %dk -bufsize:v %dk", o.h264Level(), o.VideoFPS, gop, gop, o.VideoBitrate, o.VideoBitrate, o.VideoBitrate),
			// Explicitly require video; automatic FFmpeg selection can silently
			// produce audio-only output when video metadata arrives late.
			"app_scale": fmt.Sprintf(`-map 0:v:0 -map 0:a:0? -vf "scale=%d:%d:force_original_aspect_ratio=decrease:force_divisible_by=2,pad=%d:%d:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1"`, o.VideoWidth, o.VideoHeight, o.VideoWidth, o.VideoHeight),
		}
		stream = "ffmpeg:" + o.SourceName + "#input=app_rtsp#video=h264#audio=aac#raw=app_scale"
	}
	config["streams"] = map[string][]string{o.SourceName: {u.String()}, o.OutputName: {stream}}
	if o.Preload == nil || *o.Preload {
		config["preload"] = map[string]string{o.OutputName: "video&audio"}
	}
	out, err := json.MarshalIndent(config, "", "  ")
	if err != nil {
		return nil, errors.New("cannot generate private configuration")
	}
	return append(out, '\n'), nil
}

func (o options) h264Level() string {
	// H.264 Annex A limits use 16x16 macroblocks, rounded up. At the
	// supported <=30 fps / <=8 Mbit/s, Level 3.1 covers up to 720p and
	// Level 4 covers all remaining validated sizes (up to 1080p30).
	// Do not unnecessarily advertise Level 4.1: some players reject it
	// even when the actual picture and bitrate fit a lower level.
	macroblocks := ((o.VideoWidth + 15) / 16) * ((o.VideoHeight + 15) / 16)
	if macroblocks <= 3600 && macroblocks*o.VideoFPS <= 108000 {
		return "3.1"
	}
	return "4.0"
}

func (o *options) defaults() error {
	// Isolated compatibility migration keeps existing HA URLs intact.
	if o.CameraPath == "" && o.CameraStream != "" {
		switch o.CameraStream {
		case "main", "sub", "ext":
			o.CameraPath = "/h264Preview_01_" + o.CameraStream
		default:
			return errors.New("legacy camera_stream must be main, sub or ext")
		}
		if o.SourceName == "" {
			o.SourceName = "reolink_haustuer"
		}
		if o.OutputName == "" {
			o.OutputName = "reolink_haustuer_alexa"
		}
	}
	if o.SourceName == "" {
		o.SourceName = "camera"
	}
	if o.OutputName == "" {
		o.OutputName = "camera_compatible"
	}
	if o.OutputMode == "" {
		o.OutputMode = "h264_aac"
	}
	if o.CameraPort == 0 {
		o.CameraPort = 554
	}
	if o.VideoWidth == 0 {
		o.VideoWidth = 1280
	}
	if o.VideoHeight == 0 {
		o.VideoHeight = 720
	}
	if o.VideoFPS == 0 {
		o.VideoFPS = 15
	}
	if o.KeyframeSecs == 0 {
		o.KeyframeSecs = 1
	}
	if o.VideoBitrate == 0 {
		o.VideoBitrate = 1500
	}
	return nil
}
func (o options) validate() error {
	// Errors must never contain option values: even paths may contain query secrets.
	if o.CameraAddress == "" || strings.ContainsAny(o.CameraAddress, "/@?#\\ \t\r\n\"'") || (strings.Contains(o.CameraAddress, ":") && net.ParseIP(o.CameraAddress) == nil) {
		return errors.New("camera_address must be a bare hostname or IP address")
	}
	if o.CameraPort < 1 || o.CameraPort > 65535 {
		return errors.New("camera_port must be 1..65535")
	}
	p, err := url.Parse(o.CameraPath)
	if err != nil || !strings.HasPrefix(o.CameraPath, "/") || strings.HasPrefix(o.CameraPath, "//") || p.IsAbs() || p.Host != "" || p.Fragment != "" || strings.ContainsAny(o.CameraPath, "\r\n") {
		return errors.New("camera_path must be an absolute RTSP path with optional query, not a URL")
	}
	if o.CameraPassword != "" && o.CameraUsername == "" {
		return errors.New("camera_password requires camera_username")
	}
	if !streamName.MatchString(o.SourceName) || !streamName.MatchString(o.OutputName) || o.SourceName == o.OutputName {
		return errors.New("source_name and output_name must be distinct names using letters, digits, underscore or hyphen")
	}
	if o.OutputMode != "h264_aac" && o.OutputMode != "passthrough" {
		return errors.New("output_mode must be h264_aac or passthrough")
	}
	if o.VideoWidth < 160 || o.VideoWidth > 1920 || o.VideoHeight < 120 || o.VideoHeight > 1080 || o.VideoWidth%2 != 0 || o.VideoHeight%2 != 0 {
		return errors.New("video dimensions must be even and within 160x120..1920x1080")
	}
	if o.VideoFPS < 1 || o.VideoFPS > 30 || o.KeyframeSecs < 1 || o.KeyframeSecs > 5 || o.VideoBitrate < 128 || o.VideoBitrate > 8000 {
		return errors.New("video_fps, keyframe_seconds or video_bitrate_kbps is outside its supported range")
	}
	return nil
}
