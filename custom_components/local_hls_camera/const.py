"""Limits and configuration for the optional Home Assistant integration."""

DOMAIN = "local_hls_camera"
CONF_STREAM_NAME = "stream_name"
DEFAULT_STREAM_NAME = "camera_compatible"
CONF_SOURCE_ENTITY = "source_entity_id"
CONF_SEGMENT_SECONDS = "segment_seconds"
CONF_SEGMENT_COUNT = "segment_count"
DEFAULT_SEGMENT_SECONDS = 1
DEFAULT_SEGMENT_COUNT = 6
MAX_SEGMENT_BYTES = 4 * 1024 * 1024
MAX_IMAGE_BYTES = 2 * 1024 * 1024
MAX_SESSIONS = 8
# The App retains at most 32 segments. Only URL strings are cached here.
MAX_SIGNED_SEGMENT_URLS = 32
SESSION_SECONDS = 600
STARTUP_SECONDS = 6
IO_TIMEOUT_SECONDS = 5
