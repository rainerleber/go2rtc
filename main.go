package main

import (
	"fmt"
	"os"
	"slices"

	"github.com/rainerleber/go2rtc/internal/alsa"
	"github.com/rainerleber/go2rtc/internal/api"
	"github.com/rainerleber/go2rtc/internal/api/ws"
	"github.com/rainerleber/go2rtc/internal/app"
	"github.com/rainerleber/go2rtc/internal/bubble"
	"github.com/rainerleber/go2rtc/internal/debug"
	"github.com/rainerleber/go2rtc/internal/doorbird"
	"github.com/rainerleber/go2rtc/internal/dvrip"
	"github.com/rainerleber/go2rtc/internal/echo"
	"github.com/rainerleber/go2rtc/internal/eseecloud"
	"github.com/rainerleber/go2rtc/internal/exec"
	"github.com/rainerleber/go2rtc/internal/expr"
	"github.com/rainerleber/go2rtc/internal/ffmpeg"
	"github.com/rainerleber/go2rtc/internal/flussonic"
	"github.com/rainerleber/go2rtc/internal/gopro"
	"github.com/rainerleber/go2rtc/internal/hass"
	"github.com/rainerleber/go2rtc/internal/hassaddon"
	"github.com/rainerleber/go2rtc/internal/hls"
	"github.com/rainerleber/go2rtc/internal/homekit"
	"github.com/rainerleber/go2rtc/internal/http"
	"github.com/rainerleber/go2rtc/internal/isapi"
	"github.com/rainerleber/go2rtc/internal/ivideon"
	"github.com/rainerleber/go2rtc/internal/kasa"
	"github.com/rainerleber/go2rtc/internal/mjpeg"
	"github.com/rainerleber/go2rtc/internal/mp4"
	"github.com/rainerleber/go2rtc/internal/mpeg"
	"github.com/rainerleber/go2rtc/internal/multitrans"
	"github.com/rainerleber/go2rtc/internal/nest"
	"github.com/rainerleber/go2rtc/internal/ngrok"
	"github.com/rainerleber/go2rtc/internal/onvif"
	"github.com/rainerleber/go2rtc/internal/pinggy"
	"github.com/rainerleber/go2rtc/internal/ring"
	"github.com/rainerleber/go2rtc/internal/roborock"
	"github.com/rainerleber/go2rtc/internal/rtmp"
	"github.com/rainerleber/go2rtc/internal/rtsp"
	"github.com/rainerleber/go2rtc/internal/srtp"
	"github.com/rainerleber/go2rtc/internal/streams"
	"github.com/rainerleber/go2rtc/internal/tapo"
	"github.com/rainerleber/go2rtc/internal/tuya"
	"github.com/rainerleber/go2rtc/internal/v4l2"
	"github.com/rainerleber/go2rtc/internal/webrtc"
	"github.com/rainerleber/go2rtc/internal/webtorrent"
	"github.com/rainerleber/go2rtc/internal/wyoming"
	"github.com/rainerleber/go2rtc/internal/wyze"
	"github.com/rainerleber/go2rtc/internal/xiaomi"
	"github.com/rainerleber/go2rtc/internal/yandex"
	"github.com/rainerleber/go2rtc/pkg/shell"
)

func main() {
	if err := hassaddon.Prepare(); err != nil {
		_, _ = fmt.Fprintln(os.Stderr, "Home Assistant app configuration error:", err)
		os.Exit(1)
	}

	// version will be set later from -buildvcs info, this used only as fallback
	app.Version = "1.9.14"

	type module struct {
		name string
		init func()
	}

	modules := []module{
		{"", app.Init},    // init config and logs
		{"api", api.Init}, // init API before all others
		{"ws", ws.Init},   // init WS API endpoint
		{"", streams.Init},
		// Main sources and servers
		{"http", http.Init},     // rtsp source, HTTP server
		{"rtsp", rtsp.Init},     // rtsp source, RTSP server
		{"webrtc", webrtc.Init}, // webrtc source, WebRTC server
		// Main API
		{"mp4", mp4.Init},     // MP4 API
		{"hls", hls.Init},     // HLS API
		{"mjpeg", mjpeg.Init}, // MJPEG API
		// Other sources and servers
		{"hass", hass.Init},             // hass source, Hass API server
		{"homekit", homekit.Init},       // homekit source, HomeKit server
		{"onvif", onvif.Init},           // onvif source, ONVIF API server
		{"rtmp", rtmp.Init},             // rtmp source, RTMP server
		{"webtorrent", webtorrent.Init}, // webtorrent source, WebTorrent module
		{"wyoming", wyoming.Init},
		// Exec and script sources
		{"echo", echo.Init},
		{"exec", exec.Init},
		{"expr", expr.Init},
		{"ffmpeg", ffmpeg.Init},
		// Hardware sources
		{"alsa", alsa.Init},
		{"v4l2", v4l2.Init},
		// Other sources
		{"bubble", bubble.Init},
		{"doorbird", doorbird.Init},
		{"dvrip", dvrip.Init},
		{"eseecloud", eseecloud.Init},
		{"flussonic", flussonic.Init},
		{"gopro", gopro.Init},
		{"isapi", isapi.Init},
		{"ivideon", ivideon.Init},
		{"kasa", kasa.Init},
		{"mpegts", mpeg.Init},
		{"multitrans", multitrans.Init},
		{"nest", nest.Init},
		{"ring", ring.Init},
		{"roborock", roborock.Init},
		{"tapo", tapo.Init},
		{"tuya", tuya.Init},
		{"wyze", wyze.Init},
		{"xiaomi", xiaomi.Init},
		{"yandex", yandex.Init},
		// Helper modules
		{"debug", debug.Init},
		{"ngrok", ngrok.Init},
		{"pinggy", pinggy.Init},
		{"srtp", srtp.Init},
	}

	for _, m := range modules {
		if app.Modules == nil || m.name == "" || slices.Contains(app.Modules, m.name) {
			m.init()
		}
	}

	shell.RunUntilSignal()
}
