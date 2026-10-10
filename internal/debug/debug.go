package debug

import (
	"github.com/rainerleber/go2rtc/internal/api"
)

func Init() {
	api.HandleFunc("api/stack", stackHandler)
}
