package tapo

import (
	"github.com/rainerleber/go2rtc/internal/streams"
	"github.com/rainerleber/go2rtc/pkg/core"
	"github.com/rainerleber/go2rtc/pkg/kasa"
	"github.com/rainerleber/go2rtc/pkg/tapo"
)

func Init() {
	streams.HandleFunc("kasa", func(source string) (core.Producer, error) {
		return kasa.Dial(source)
	})

	streams.HandleFunc("tapo", func(source string) (core.Producer, error) {
		return tapo.Dial(source)
	})

	streams.HandleFunc("vigi", func(source string) (core.Producer, error) {
		return tapo.Dial(source)
	})
}
