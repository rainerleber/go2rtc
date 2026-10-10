package flussonic

import (
	"github.com/rainerleber/go2rtc/internal/streams"
	"github.com/rainerleber/go2rtc/pkg/flussonic"
)

func Init() {
	streams.HandleFunc("flussonic", flussonic.Dial)
}
