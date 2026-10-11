# Private App HLS contract v1

This is a Home Assistant backend, not a public streaming service. Generated
App config selects a validated output name, not a caller-supplied URL/command.
API/RTSP bind loopback; FFmpeg/ffprobe read the shared H.264/AAC RTSP output.

| Request under `/api/hls/v1/<stream>/` | Result |
| --- | --- |
| `POST start` | 204: start/keepalive accepted; not proof of a frame |
| `GET status` | Version, generation, running/ready, settings, bounded counters, fixed error code, actual media metadata; no keepalive |
| `GET master.m3u8?generation=<id>` | HLS v3, actual SPS metadata/measured bandwidth, relative child |
| `GET stream.m3u8?generation=<id>` | Fresh keyframe-aligned window, relative `.ts` children |
| `GET segment-<sequence>.ts?generation=<id>` | Immutable complete TS; 404 outside retention |
| `GET snapshot.jpg` | Current output-resolution JPEG; bounded decode/cache, no camera request |

Media responses have `no-store`, `nosniff`, `X-HLS-Generation`. Old generations
return 410, not-ready media 503, unknown paths 404, non-loopback callers 403.
Backend routes have **no HA authentication** and must not be LAN/internet forwarded.

FFmpeg packet-copies local RTSP to a continuous HLS/TS muxer and PUTs to
`/internal/hls/<random-capability>/<filename>`. This upload capability differs
from playback generation, is never returned in status, and changes on restart.
Uploads/probes are serialized and bounded; bodies, codecs, playlist references,
freshness, live window, RAM limits and removed-segment retention are checked.
FFmpeg closes uploads without waiting for server processing, so readiness
checks every referenced segment, not upload arrival order. No `www`/media files.

HA rewrites every relative child to signed, permission-checked routes and pins
sessions to a generation. It rejects redirects and never forwards backend
addresses, upload capabilities or camera credentials publicly. Protocol version
is independent of App CalVer; breaking changes need a new API/migration.
