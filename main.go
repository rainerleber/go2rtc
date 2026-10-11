package main

import (
	"fmt"
	"os"

	"github.com/rainerleber/go2rtc/internal/api"
	"github.com/rainerleber/go2rtc/internal/app"
	"github.com/rainerleber/go2rtc/internal/exec"
	"github.com/rainerleber/go2rtc/internal/ffmpeg"
	"github.com/rainerleber/go2rtc/internal/hassaddon"
	"github.com/rainerleber/go2rtc/internal/hls"
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

	// The app owns media; Home Assistant owns entities, public authentication
	// and its native Alexa interface. No HA Core implementation is replaced.
	app.Init()
	api.Init()
	streams.Init()
	rtsp.Init()
	exec.Init()
	ffmpeg.Init()
	hls.Init()
	defer hls.Close()

	shell.RunUntilSignal()
}
