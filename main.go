package main

import (
	"fmt"
	"os"

	"github.com/rainerleber/go2rtc/internal/api"
	"github.com/rainerleber/go2rtc/internal/app"
	"github.com/rainerleber/go2rtc/internal/exec"
	"github.com/rainerleber/go2rtc/internal/ffmpeg"
	"github.com/rainerleber/go2rtc/internal/hassaddon"
	"github.com/rainerleber/go2rtc/internal/rtsp"
	"github.com/rainerleber/go2rtc/internal/streams"
	"github.com/rainerleber/go2rtc/pkg/shell"
)

func main() {
	if err := hassaddon.Prepare(); err != nil {
		_, _ = fmt.Fprintln(os.Stderr, "Home Assistant app configuration error:", err)
		os.Exit(1)
	}

	// The build metadata overrides this upstream compatibility fallback.
	app.Version = "1.9.14"

	// Only the HA app's local RTSP pipeline is compiled. Home Assistant owns
	// camera entities, HLS delivery and the Alexa interface.
	app.Init()
	api.Init()
	streams.Init()
	rtsp.Init()
	exec.Init()
	ffmpeg.Init()

	shell.RunUntilSignal()
}
