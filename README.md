# BarnScope for Raspberry Pi Zero 2 W

A camera-provider-based optic with a lightweight browser view. `--mode simulator`
runs without hardware; `--mode pi` uses real Picamera2 frames. This directory
runs **on your Pi**, not in the Replit container. No desktop display, OpenCV,
Node.js, Flask, or cloud service is needed on the Pi.

## Architecture

- `main.py` chooses the camera provider and starts/stops the server. Real
  camera capture is the default; a failure never silently selects a simulator.
- `camera.py` provides the `CameraProvider` contract, a procedural
  `SimulatorCameraProvider`, and a lazy-imported `PiCameraProvider`.
  Camera frames contain **only imagery**, no labels, boxes or overlay pixels.
- `reticle.py` produces the reticle shapes. `hud.py` produces a transparent SVG
  showing reticle, compass when a sensor is present, battery if available,
  zoom and recording indicator. It requires **no image or camera provider**.
- `settings.py` validates display inputs and defines `Action` and the
  thread-safe `ControlDispatcher` for future GPIO button callbacks.
- `gpio.py` defines the hardware-independent `ButtonInput` contract and
  `ButtonController`. The default input is disabled: no GPIO libraries, pin
  assignments, electrical configuration, threads or hardware access are used.
- `app.py` serves frames, status, HUD and control events via HTTP; it remains
  a backwards-compatible launcher for older setups.
- `web/index.html` combines the selected source frame and independent HUD
  on one browser canvas, so screenshots and browser recordings contain both.

Touch, keyboard and future physical inputs share one browser action handler.
For a future GPIO adapter, implement `start(on_edge)` and `stop()`, then inject
it as `ButtonController(controls, source=adapter)` in `main.py`.
The adapter reports logical edges such as `on_edge("zoom_in", True)` on press
and `on_edge("zoom_in", False)` on release, not raw pin voltage levels.
The controller maps logical names to the existing `Action` values, filters
contact bounce (150 ms per button), and emits one action per press with no
hold-to-repeat. Release re-arms the button. All actions have lowercase logical
names by default; custom mappings can be supplied, for example
`mappings={"primary": Action.MENU}`. Start/stop belong to the main application
thread; stop disables dispatch before adapter cleanup. The monotonic clock is
injectable so debounce can be tested without sleeping or hardware.
The web view polls `/api/controls` and executes the same actions as its own
buttons. **No GPIO pins, electrical pull-ups, or button wiring are assumed or
activated yet.** Client-side recording requires an open browser; without a
viewer a GPIO `RECORD` event cannot save footage to the Pi.

## Hardware

- Raspberry Pi Zero 2 W, a suitable power supply, and microSD card.
- A supported CSI Pi Camera and the correct **Pi Zero camera ribbon cable**.
- A NoIR camera and suitable infrared illumination if you want to observe in
  darkness. Software alone does not make a normal camera see in total darkness.
- A phone/computer browser on the same trusted Wi-Fi network.

The camera is captured on the Pi; the browser displays and records the stream.
This is not yet an application for a directly attached SPI/HDMI eyepiece display.

## Set up Raspberry Pi OS

Use a current Raspberry Pi OS Lite installation with the modern libcamera stack.
With the Pi powered off, attach the camera cable. Start the Pi and run these
commands **on the Pi**, not inside Replit:

```sh
sudo apt update
sudo apt install --no-install-recommends python3-picamera2 rpicam-apps-lite
rpicam-hello --list-cameras
```

On older Raspberry Pi OS versions the camera tools may be named
`libcamera-hello` / `libcamera-still`. Prefer a current Raspberry Pi OS release
and its supplied Picamera2 package; do not use the old `picamera` library or
enable the legacy camera stack.

## Copy and run

Copy this entire directory to the Pi, preserving `web/index.html`. For example,
from a computer with this project downloaded:

```sh
scp -r devices/raspberry-pi <pi-user>@<pi-ip>:~/barnscope
ssh <pi-user>@<pi-ip>
cd ~/barnscope
python3 main.py --mode pi --host 0.0.0.0
```

Replace the angle-bracket placeholders with your Pi's actual account/IP.
Open `http://<pi-ip>:8000` in a browser on the same Wi-Fi network.
Use Ctrl+C to stop the server.

The default bind address is localhost; `--host 0.0.0.0` explicitly enables LAN
access. There is **no authentication or encryption**. Do not use on untrusted
Wi-Fi, expose it to the internet, or configure router port forwarding.
For remote access, use an authenticated VPN; this code does not configure one.

### Try Simulator Mode without camera hardware

With this package on a computer or Pi, using system Python 3.10 or newer:

```sh
python3 main.py --mode simulator
```

Open `http://127.0.0.1:8000`. The menu clearly identifies **SIMULATOR MODE**;
its scenery is generated. It does not fabricate compass or battery readings.
Select `--mode pi` explicitly when the camera is attached. A failing Pi Camera
never falls back to the generated scene.

## Performance

Defaults: **640×360 at 10 fps**, one shared latest JPEG, four camera buffers.
These conservative settings suit the Zero 2 W's CPU, 512 MB memory and Wi-Fi.
Actual frame rate/latency depends on camera, OS, signal and browser; it has not
been measured on physical hardware here.

```sh
python3 main.py --mode pi --host 0.0.0.0 --width 960 --height 540 --fps 10
```

Supported dimensions are even, 16:9, and at most 1280×720; maximum configured
rate is 30 fps, **not a performance guarantee**. Lower resolution/rate if frames
stutter. Start with one viewer. Digital zoom crops pixels; it is not optical zoom.
Use a modern browser. Recordings and image compositing run on the viewing device.
The server computes transparent HUD SVG when settings/telemetry change.

## Controls and recording

Optic Mode hides all persistent controls. Tap the camera image or press **M**
to open the menu; press **Esc** or Return to restore the clean optic view.
Keyboard Tab reveals an accessible Menu button. Future GPIO `MENU` actions
open the same overlay. Camera-failure warnings remain visible.

The menu opens operation controls and display settings. Reticle style/color/
brightness, compass/battery visibility, and zoom are saved in the browser.
The interface has no simulated barnyard, fixed landmark labels, or fake telemetry.

Keyboard: **M** menu, **Esc** close menu, **1/2/4** zoom, **R** recording.
Snapshots and recordings include the displayed optic overlays.
Recording uses browser `captureStream` and `MediaRecorder`, only when available.
Clips are kept in browser memory, limited to two minutes each, and must be
downloaded before closing/reloading the page. They are **not saved on the Pi's
SD card**. No audio is recorded.

The UI reports camera loss explicitly. Check the physical camera and server
before recording important footage. This is not a surveillance or safety system.

## Real compass and battery readings

The Zero 2 W and Pi Camera do not supply a magnetic heading or a battery
percentage by themselves. With no sensors, the compass is hidden and battery is
unavailable rather than displaying simulated values.

Battery capacity is read automatically only if a battery driver exposes a Linux
`/sys/class/power_supply/*` entry of type `Battery` with a `capacity` value.
A USB power bank usually does **not** expose this information.

Alternatively, run your own calibrated sensor process that atomically replaces
a small JSON file at least once every ten seconds:

```json
{"heading": 72.0, "battery": 89}
```

Then launch:

```sh
python3 main.py --mode pi --host 0.0.0.0 --telemetry-file /run/user/1000/barnscope-telemetry.json
```

Use an actual path writable by your sensor process; the example UID may differ.
Heading must be a real measurement in degrees [0, 360], battery 0–100.
Missing, malformed or stale measurements are reported as unavailable. Compass
sensor drivers, magnetic calibration, and battery hardware are not included.

## Endpoints

- `/` — local Optic interface, no external assets or internet needed.
- `/camera/frame` — source image only: JPEG in Pi Mode, SVG in Simulator Mode.
  HTTP 503 if absent/stale. `/camera/frame.jpg` is a Pi Mode compatibility alias.
- `/hud.svg` — transparent provider-independent overlay. Validated URL
  parameters for zoom, reticle, compass/battery visibility and recording state.
- `/camera/stream.mjpg` — optional Pi Mode MJPEG feed (two stream slots); not
  supported by the SVG simulator.
- `/api/status` — camera health, frame age, configured dimensions/rate and nullable
  real sensor readings; includes the selected camera mode.
- `/api/controls?after=0` — pending physical-control events. Only local Python
  callbacks can publish; this unauthenticated server has no network write API.

Frame freshness means the encoder produced data recently; it is not a guarantee
that the scene or sensor is correct.

## Troubleshooting

- **No cameras available:** check the ribbon orientation/cable and
  `rpicam-hello --list-cameras`. Stop other applications using the camera.
- **ImportError:** use the Raspberry Pi OS system Python (`/usr/bin/python3`)
  and OS-provided `python3-picamera2`; avoid an isolated Python environment.
- **Cannot connect:** confirm the Pi IP, same Wi-Fi, `--host 0.0.0.0`, and firewall.
- **Dark image:** check lighting, exposure and whether the camera has an IR-cut
  filter. Night-vision hardware/illumination is required for dark scenes.
- **Recording unsupported:** use a browser exposing MediaRecorder/canvas capture;
  snapshots still work. Browser support and available recording formats vary.

## Verification

```sh
python3 -m unittest discover -s tests -v
```

These tests validate HTTP responses, frame freshness and sensor parsing using
in-memory fixtures. **They do not test a real Pi Camera.** Physical camera
capture, encoding speed and image quality must be verified on your Pi.
