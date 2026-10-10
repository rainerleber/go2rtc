package bubble

import (
	"github.com/rainerleber/go2rtc/internal/streams"
	"github.com/rainerleber/go2rtc/pkg/bubble"
	"github.com/rainerleber/go2rtc/pkg/core"
)

func Init() {
	streams.HandleFunc("bubble", func(source string) (core.Producer, error) {
		return bubble.Dial(source)
	})
}
