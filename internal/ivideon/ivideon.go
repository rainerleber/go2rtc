package ivideon

import (
	"github.com/rainerleber/go2rtc/internal/streams"
	"github.com/rainerleber/go2rtc/pkg/ivideon"
)

func Init() {
	streams.HandleFunc("ivideon", ivideon.Dial)
}
