package isapi

import (
	"github.com/rainerleber/go2rtc/internal/streams"
	"github.com/rainerleber/go2rtc/pkg/core"
	"github.com/rainerleber/go2rtc/pkg/isapi"
)

func Init() {
	streams.HandleFunc("isapi", func(source string) (core.Producer, error) {
		return isapi.Dial(source)
	})
}
