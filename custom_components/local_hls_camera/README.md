# Local HLS Camera (optional Home Assistant integration)

This integration creates a **separate compatibility camera** from an existing
Home Assistant RTSP camera. It leaves the go2rtc app, HA Core, the original camera,
and its consumers unchanged. It is not a browser workaround or a second app.

```text
Local camera → existing go2rtc app → local RTSP → Local HLS Camera
             → HA HTTPS / existing Nabu Casa remote access → Alexa / Echo
```

## Status and limitations

The first supported/tested baseline is **Home Assistant 2026.10.1, PyAV 19**.
On **2026-10-11**, a user confirmed a real live picture on an **Echo Show 15
(first generation)** through native Alexa, using a local RTSP input with
H.264/AAC, 1280×720, 15 fps and a one-second GOP. No gong was triggered for
that test. This is **not a confirmed fix for every Echo** or a long-term
stability guarantee.
The native HA Alexa handler still requests HLS. The camera implements a narrow
adapter for HA's **internal** `async_create_stream()` contract; it does not patch
HA's camera helpers, Alexa handler, Stream worker, provider registry or gzip code.
HA updates preserve the integration's files but can change that internal API.

No Reolink cloud is used. Native Alexa and existing Nabu Casa still involve
Amazon/HA Cloud; this is not a completely cloud-free Alexa solution.

## Why the container app is still needed

The two components have different jobs:

- **go2rtc app:** obtains local camera media and, when needed,
  produces a warm H.264/AAC RTSP compatibility stream with suitable keyframes.
- **Local HLS Camera integration:** copies that stream into self-contained
  MPEG-TS HLS segments and serves them through HA's authenticated HTTP routes.
- **HACS:** downloads and tracks the integration code; it does not process media.

Keep the app for this verified setup. It is only optional if another existing
HA camera already supplies a compatible RTSP stream. The integration itself
does not transcode, add AAC or repair a long input keyframe interval.

## Installation from GitHub through HACS

HACS must already be installed and configured. No upstream app catalog or new
service credentials are needed.

1. Open **HACS → menu → Custom repositories**.
2. Add **`rainerleber/go2rtc`**, category **Integration**.
3. Open **Local HLS Camera**, download the **default branch (`master`)**.
   HACS obtains the files from GitHub and installs only
   `custom_components/local_hls_camera`. The app is installed separately from
   the HA App store using the same repository URL.
4. Restart HA once for a first installation, then follow **Camera setup** below.

The HA manifest uses its own `YYYY.MM.BUILD` CalVer. The app image has an
independent CalVer. For a default-branch download, HACS displays/tracks a Git
commit rather than the app image version. Record the installed HACS commit
when troubleshooting. Old upstream tags/releases may not contain this
integration; do not select one just because its number resembles an app version.

To adopt an existing manual installation, back up only the existing integration
folder before downloading it through HACS. Keep its config entry and entity
registry identity. If the Python files and manifest are identical, a full HA
restart is not needed merely to replace their provenance with a GitHub download;
reload the integration after verification. Otherwise restart HA to load updated
Python modules; reloading a config entry does not reliably replace cached code.

### Manual GitHub installation (without HACS)

Download the repository archive at a reviewed full commit SHA from GitHub, then
copy **only** `custom_components/local_hls_camera` into the same folder under
`/config/custom_components`. Do not copy a local uncommitted development tree.
Do not overwrite an existing installation without reviewing its version and
backing up that exact folder. Restart HA after new or changed runtime code.

### Camera setup

1. Open **Settings → Devices & services → Add integration → Local HLS Camera**.
2. Choose a distinct test name and an existing RTSP source camera. Do not replace
   or rename the original camera yet.
3. Optionally enable **Preload stream** in the new camera's normal HA settings.
   This retains one local RTSP/remux worker; the go2rtc app has its own independent
   source/encoder preload setting.
4. Expose only the new test camera to Alexa, then verify a real Echo live picture
   **without triggering the doorbell/gong**. Only after that should existing
   consumers be migrated deliberately.

### Promote a verified camera

Check references to the test entity/name before renaming it. Give the integration
and camera a meaningful production name, keep the RTSP source entity unchanged,
and use a distinct stable entity ID for the HLS wrapper. Reapply/read back the
native camera preload preference for the new ID and reload **only this config
entry** so its adapter uses the renamed entity for permission checks. Review
voice names too: expose only one camera for each Alexa name, then synchronize
Alexa. An existing `Zeige <name>` action can remain unchanged if the new camera
takes over that same voice name. Verify without invoking the doorbell automation.

Keep camera credentials in the existing source app. No extra camera user,
HA login, Supervisor token, app privilege, HA configuration mount, additional
listening port or router forwarding is needed.

## Input and settings

Input must be **H.264 + AAC-LC**, transported over RTSP/TCP. Other camera vendors
and local RTSP-producing apps can be used. There are no Reolink names or paths
in the code. This integration does not transcode or add audio: use the source
app's compatibility encoder if the camera produces H.265 or another audio codec.
For HA's current native Alexa advertisement, use a 1280×720 H.264/AAC output.

| Setting | Default | Range / purpose |
| --- | --- | --- |
| Source camera | required | Existing HA camera with an RTSP/RTSPS source; recursive sources are rejected |
| Target segment duration | 1 second | 1–3; segments end at the next keyframe, never at arbitrary byte boundaries |
| Retained segments | 6 | Target 3–10; a jitter-compensation segment may be retained, bounded by 16 MiB total |
| Preload stream | standard HA preference | Keeps the remux worker warm; no duplicated integration-specific preference |

The input keyframe interval should be at most the target segment duration.
The HLS target duration is fixed at `ceil(segment_seconds)`; input GOPs that
cannot fit within it are rejected instead of publishing an invalid playlist.
Eviction preserves a live window of at least three target durations; a stream
that cannot satisfy this within the memory bound is rejected.
The default 1-second GOP is a good starting point, not a guaranteed end-to-end
Alexa startup time. Wider GOPs and extra buffered segments increase latency.

## Media and resource handling

- PyAV copies compressed packets into MPEG-TS; there is **no second encoder**.
- Complete segments contain PAT/PMT, H.264 decoder configuration and a starting
  keyframe. Transport continuity counters continue across segments; reconnects
  are represented with HLS discontinuities and monotonic media sequences.
- Legacy HLS v3: no `EXT-X-MAP`/separate initialization file, LL-HLS parts or
  forced gzip compression. The master reports the source's actual codec metadata.
- Media stays in RAM: at most 4 MiB per segment and 16 MiB in the published ring.
  Pending publication is also bounded. No camera recording or segment directory
  is created. The normal HA camera snapshot action remains subject to HA's own
  permissions and path allowlist; this integration does not make recordings.
- Network open/read timeouts are 5 seconds. Reconnect backoff is 1–15 seconds.
  Stale media is not advertised as a working live stream.
- Duplicate packets and decode-time regressions of up to 0.5 seconds are
  discarded per track before muxing, including across segment boundaries.
  Valid timestamps are preserved; no vendor-specific clock rewrite or second
  encoder is added. Small audio jitter can therefore cause a brief audio gap,
  rather than disconnecting the entire video stream. Larger backward resets,
  forward jumps above 30 seconds, or more than six consecutive packets without
  timestamps on a track trigger a clean reconnect and HLS discontinuity.
  These are fixed safety limits, not additional UI settings.
- Without preload, a worker stops after 60 seconds without playback requests.
  Unloading or stopping HA stops the worker and revokes all playback sessions.

## Access control and trust boundary

HTTP routes are registered **inside HA**, so existing HA HTTPS/remote access
serves them. The app's loopback RTSP and API are not exposed to Alexa or the
internet. The normal HA Alexa handler obtains the new camera's HLS URL.

All master playlists, child playlists and segments use HA's own **path-specific,
expiring signed URLs**. Signatures are validated by the normal HA authentication
middleware; entity read permission is also checked. Playback sessions are limited
to 10 minutes and eight concurrent sessions per camera. URLs act as temporary
bearer capabilities: possession allows viewing their corresponding resource;
do not publish or log them. HA's existing read-only Content system user is reused;
the integration does not create a user or store a new password/token.

Configuration is through HA's admin configuration UI. Playback is not inherently
admin-only: authorized HA users or holders of valid signed playback URLs can view
it. **Custom integrations are not sandboxed** and run with the HA process's
privileges. Minimal code access is not an OS-enforced read-only security boundary.

The route only serves its in-memory playlists/segments. It is not an arbitrary
URL proxy or file server and accepts no shell command or FFmpeg arguments.
Diagnostics contain counts and fixed error codes, never stream URLs or passwords.

## Testing and maintenance

```sh
python3.14 -m venv .venv
.venv/bin/pip install -r requirements-extension-test.txt
.venv/bin/ruff check custom_components tests/local_hls_camera
.venv/bin/python -m pytest tests/local_hls_camera
```

The test runner needs FFmpeg with `libx264` and AAC to generate synthetic media.
Tests remux and independently decode real synthetic segments, check counters,
playlists and memory bounds, and exercise the installed HA authentication
middleware (including missing, expired and tampered signatures on every URL).
An isolated HA config-flow/platform test verifies setup and unload. Setting
`GO2RTC_TEST_BINARY` to a locally built go2rtc executable additionally exercises
real loopback RTSP with synthetic media; CI always enables that test.
No personal camera images or credentials are committed as fixtures.

CI runs on integration changes and weekly with read-only repository permissions.
The baseline suite guards the current internal HA contract; a scheduled latest-HA
job detects upstream interface changes. Neither job publishes an app container or
installs anything into a live HA system.

### Operational checks and troubleshooting

- In the integration diagnostics, expect `running: true`, `ready: true`, a
  bounded `buffer_segments`/`buffer_bytes` count and `last_error: null` after
  warm-up. These are local worker checks, not proof of an Echo live picture.
- A brief `media_io_error` can occur on source interruption; the worker retries
  with bounded backoff. Persistent errors require checking the source app,
  RTSP reachability and the required input codecs/keyframe interval.
- `timestamp_discontinuity` means the source clock reset or jumped beyond the
  safety limits; `missing_packet_timestamps` means a track stopped providing
  usable packet timing. Duplicate/briefly late packets do not require reconnects.
- A request without valid HA authentication or a valid path signature must
  return HTTP **401**. Expired playback sessions return **410**; stale/not-yet-ready
  media returns **503**. Do not log or share signed playback URLs.
- If Alexa cannot find the renamed camera, check its exposure and synchronize
  devices before retesting the exact new voice name.
- If Alexa finds it but says the camera is unresponsive, check remote HTTPS
  access, diagnostics and logs. Do not change HA Core files or expose the app's
  loopback API/RTSP ports to the internet.
- Update through HACS from a reviewed GitHub revision. Review the baseline/latest
  CI results before upgrading HA because the stream adapter uses an internal API.
- Keep secrets and real camera recordings out of issues, commits and test fixtures.

## Changelog

### 2026.10.2

- Handle duplicate/late RTSP packets generically before MPEG-TS muxing, avoiding
  repeated reconnects caused by small audio decode-time regressions.
- Preserve valid source timing and reconnect on genuine clock discontinuities.
- Add real PyAV duplicate/regression tests and longer synthetic RTSP coverage.
- Runtime code changed: install through HACS from GitHub, then restart HA Core
  once to load the new modules. A config-entry reload alone is not sufficient.

### 2026.10.1

- First standalone HA compatibility camera: RTSP H.264/AAC to MPEG-TS HLS v3.
- UI configuration, native preload preference and source-camera snapshots.
- HA-signed, expiring, permission-checked playlists and segments; no extra user.
- RAM-only bounded buffers, reconnect backoff and unload/session cleanup.
- HA config-flow, native Alexa handler, HTTP auth and synthetic media/RTSP tests.
- Native Echo live picture confirmed on the baseline described above.
- HACS custom-repository installation and migration/update guidance.

## Rollback

First disable the **new** integration in HA and remove only its Alexa exposure.
Its worker stops and its playback URLs become invalid. The original camera and
automation keep working as before. To remove the installed code, move the exact
`/config/custom_components/local_hls_camera` folder out of `custom_components`
and restart HA. Do not delete or overwrite Core files or edit `.storage` manually.
Removing a config entry also removes its entities; take a usable HA backup before
such a deletion if preserving its registry identity matters.
