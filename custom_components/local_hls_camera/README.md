# Local HLS Camera: thin Home Assistant bridge

The **go2rtc app owns media**: local RTSP camera access, optional H.264/AAC
encoding, MPEG-TS HLS packaging, bounded RAM buffering, reconnects and JPEG
previews. This integration creates a HA camera, checks read access, signs every
media URL and forwards the app's media through HA's existing server.
It has no PyAV remuxer, media worker thread, segment ring or second encoder.

```text
Local camera → go2rtc app (H.264/AAC, RAM-only MPEG-TS HLS, JPEG)
             → thin HA camera (permissions, signed HTTPS routes)
             → existing HA Cloud / native Alexa → Echo Show
```

No Generic Camera, extra app, browser workaround, Reolink cloud, new user,
additional password, Supervisor/HA token or Core patch is required. Native
Alexa still uses Amazon and the existing HA Cloud connection; it is not fully
cloud-free. Keep the original camera for recording.

## Install from GitHub

1. Add `https://github.com/rainerleber/go2rtc` to the App store. Install **go2rtc**,
   configure its camera and enable `preload` for fast playback.
2. In HACS Custom repositories, add `rainerleber/go2rtc`, category **Integration**.
   Download **Local HLS Camera** from `master`. HACS installs only the custom
   component; the App store downloads the image built by GitHub Actions.
   Do not upload a local uncommitted worktree to production.
3. Restart HA Core to load changed Python modules. A config-entry reload does
   not reliably replace cached code.
4. Add **Local HLS Camera** under Devices & services. Enter its camera name
   and the app's `output_name`, default `camera_compatible`.
5. Expose only this camera to Alexa. Verify a real Echo picture without gong.

The integration accepts a stream **name**, not a URL/address/password. Its
options change that output. Encoding, HLS duration/count and boot-time warmup
belong to the app. HA's normal camera preload preference can send keepalives;
app preload warms media even before HA has loaded.

Baseline: **HA 2026.10.1**. The adapter uses HA's **internal**
`async_create_stream()` contract, not a stable public HLS-provider API.
No global camera helper, Alexa handler, stream worker, provider registry or
compression implementation is replaced. Baseline/latest-HA CI guards that contract.

## Migration from 2026.10.1 / 2026.10.2

Take a **usable HA backup** including HA configuration, integration files and
the App/data; keep restore credentials/emergency kit available.

1. Record the old integration's segment duration/count and source camera.
2. **Update the app first**, and match `hls_segment_seconds` / `hls_segment_count`
   to those old values (defaults 1 / 6). Wait for HLS API v1 readiness.
3. Update the integration through HACS and restart Core. Migration accepts only
   `rtsp://127.0.0.1:8554/<output_name>` without credentials/query. A Generic
   source need not be loaded: its config entry can be read through HA in RAM.
4. Migration keeps entry ID, camera unique ID, entity ID, name, exposure and
   preload preference. It replaces the source reference with the output name;
   no credential is copied and no other camera/integration is removed.
5. Check diagnostics, snapshot, signed media access, actual Echo playback
   **without gong**, and unchanged doorbell/recording automation configuration.
6. Only then check **all consumers** of the obsolete Generic source and remove
   that exact Generic integration through HA with operator approval and a
   usable backup. Never remove the original recording camera.

An unavailable/old app, non-app source or mismatched HLS settings stops migration
without modifying the entry. Fix the app/settings, then retry. There are no
`.storage` edits, Core modifications or automatic registry deletions.

## Media and resources

The app packet-copies prepared loopback RTSP using FFmpeg `-c copy`: no second
video encoder or direct additional camera connection. HLS requires H.264 +
AAC-LC; video-only/H.265 passthrough can still be used as RTSP, but this HLS
backend rejects it. For HA Alexa's current advertisement use 1280×720 H.264/AAC
and one-second keyframes.

- HLS v3 `.ts` segments: no fMP4 initialization, `EXT-X-MAP`, LL-HLS parts,
  extra web UI or forced gzip. Actual SPS codec/profile/level, dimensions and
  measured bandwidth populate the master. FFmpeg owns the continuous TS muxer.
- Ready requires fresh media and a window of at least three target durations.
  Long GOPs/durations increase cold start; preload is recommended for Echo's
  startup deadline, not a guarantee of end-to-end latency.
- At most 4 MiB per segment and 16 MiB in the ring. One serialized upload/probe
  can hold another 4 MiB, the JPEG cache another 2 MiB; FFmpeg also has process
  memory. **16 MiB is not a total app RSS limit.** No media files are created.
- Removed segments remain available for their duration plus the playlist
  window. Hard RAM limits reject excessive bitrate/GOP/window combinations
  rather than evicting promised URLs. Reduce those settings if
  `buffer_limit_exceeded` persists.
- Five-second I/O/probe/snapshot deadlines, stale-worker detection and 1–15
  second reconnect backoff. FFmpeg handles ordinary packet timing; stalled or
  incompatible media is not advertised as ready.
- Worker/App restart changes the playback generation. Old sessions cannot
  fetch new-generation media under previous URLs; request playback again.
- Without app preload or HA/playback keepalives, workers stop after about
  60 seconds idle. HA unload revokes its sessions/polling, **not** the shared
  preloaded App backend.
- JPEGs come from current HLS segments, cached for at most three seconds and
  forwarded at app resolution. No snapshot source entity/credential is needed.
  The bridge is playback-only; recording uses the original camera.

The [private v1 API](../../internal/hls/README.md) permits only configured output
names/known filenames on fixed loopback port 1984. Redirects are rejected.
Private FFmpeg PUT uploads use an ephemeral RAM capability, distinct from the
playback generation; it is not a user/password and is never returned in status.

## Access and trust

App API/RTSP stay loopback-only; no forwarding or additional App privilege is
needed. Normal HA authentication validates path-specific expiring signatures
on **every** master, child and segment URL, followed by entity read checks.
Sessions last at most 10 minutes with at most eight per camera. These URLs
are bearer capabilities: never publish/log them. The existing read-only HA
Content system user is reused; no account/token/password is created.

Within a session, a published playlist/segment keeps the **same complete URI**,
including its signature, across playlist reloads. Re-signing every reload
changes HA's issued-at claim and can make strict HLS players stop after the
initial buffer ([RFC 8216 section 6.3.4](https://www.rfc-editor.org/rfc/rfc8216.html#section-6.3.4)).
The bridge caches only two playlist URL strings and at most 32 segment URL
strings per session, matching the App's maximum retained segment count. It
does not cache media. Signatures still expire, access checks remain per request,
and expired/restarted sessions cannot use cached links to bypass validation.

Configuration is admin-only; playback is **not inherently admin-only**:
authorized HA users and holders of valid media capabilities can view it.
Custom integrations run with HA process privileges and are not sandboxed.
Minimal code is not an OS-enforced access boundary. HA/Supervisor admins and
host-network apps remain trusted. Masking does not encrypt secrets from admins.
Diagnostics expose counters/fixed error codes, never credentials, camera URLs,
upload capabilities or signed playback links. This is not an open URL/file proxy.

## Tests, status and maintenance

```sh
go test ./...
go test -race ./internal/hls ./internal/hassaddon
go build -o /tmp/local-hls-go2rtc .
python3.14 -m venv .venv
.venv/bin/pip install -r requirements-extension-test.txt
GO2RTC_TEST_BINARY=/tmp/local-hls-go2rtc .venv/bin/python -m pytest -q
```

FFmpeg/ffprobe generate synthetic fixtures. Go tests cover bounds, private
uploads, playlists, shutdown/failure and real HLS/JPEG output. Python tests
cover HA auth/ACL/signatures, expiry/generations, migration, redirect/size
rejection, setup/unload and the native Alexa handler. End-to-end tests exercise
RTSP → app → signed HA → independent decoder, repeated live-window rotations
and App restart. They also require identical complete segment URIs for every
repeated media sequence, across real signing seconds and moving windows, and
exercise bounded URL-cache eviction and unchanged playlist URLs. Container
tests also verify generated settings for landscape,
wide/portrait inputs and an initially offline camera. No personal media is committed.

The preceding HA-owned remuxer had a user-confirmed Echo Show 15 (first
generation) picture on 2026-10-11. The new App backend is tested synthetically;
actual Echo playback after migration must be checked separately. CI/readiness
alone do not prove that the Echo displays video.

Expected warm diagnostics: `running: true`, `ready: true`, `media_owner: app`,
bounded counters and no error. Unsigned/tampered requests return 401, denied
entity reads 403, missing media 404, expired session/generation 410, unavailable
media 503. For discovery, expose one camera per name and sync Alexa; stale
Amazon entries may need separate cleanup. Do not patch Core or expose App ports.

## Versions and rollback

**2026.10.4:** bounded per-session signed-URL reuse fixes changing media URIs
on playlist reloads. This is a bridge-only update: App 2026.10.29 stays installed,
with no settings/config-entry migration, Core patch or additional permission.
Download through HACS and restart Core to activate the Python fix. Rolling
back this fix uses the preceding 2026.10.3 GitHub commit through HACS plus a
Core restart; it does not require reverting the version-2 config entry.
Actual sustained Echo playback still requires an operator test.

**2026.10.3:** App-owned HLS/buffering/reconnect/snapshots; version-2 config
migration preserves entity identity and removes the Generic-camera dependency.
Old Python PyAV worker/ring and its timestamp-specific options/code are removed.
App FFmpeg and freshness checks replace that implementation; old fixed Python
timestamp limits are not misleadingly presented as current functionality.

**2026.10.2:** previous HA-owned remuxer with per-track timestamp-jitter guard.

App and integration have separate CalVer versions; HACS default-branch updates
track commits, not image tags. Weekly container builds refresh base packages.
Baseline/latest integration CI is read-only and does not deploy to live HA.

Before migration, rollback uses the App backup and previous GitHub/HACS code.
**After migration**, old 2026.10.2 code cannot read the new config entry:
restore a usable pre-migration HA backup as well as App/code through HA's
supported restore flow, with explicit operator approval. Never edit `.storage`.
Keeping the Generic source until actual Echo verification preserves that fallback.
