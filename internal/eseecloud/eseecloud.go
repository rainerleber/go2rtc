package eseecloud

import (
	"github.com/rainerleber/go2rtc/internal/streams"
	"github.com/rainerleber/go2rtc/pkg/eseecloud"
)

func Init() {
	streams.HandleFunc("eseecloud", eseecloud.Dial)
}
