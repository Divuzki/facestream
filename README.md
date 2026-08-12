# FaceStream

This is a web app that let's you swap your face in real-time without having a powerful
machine. You can try it out live [here](https://facestream.phileisen.com).

See the gif below for a demo:

[![Demo](assets/demo.gif)](https://facestream.phileisen.com)

## Motivation

I discovered the [Deep Live Cam](https://github.com/hacksider/Deep-Live-Cam) project and tried to run it on my M1 MacBook, but only got 0.5 FPS. So I wanted to explore how fast and at what latency you could get this to run on a remote server via WebRTC.

## How to run this yourself

### Prerequisites

To run this yourself you wil need:

- [uv](https://docs.astral.sh/uv/)
- A [modal](https://modal.com/) account as well configured credentials

Modal is the only account involved — there are no API keys to paste anywhere and
no model to download by hand. The face swap weights are pulled from Hugging Face
on first boot and cached in a Modal volume, so only the first container start
pays for it.

Set the credentials up once with:

```
uv run modal setup
```

Optional extras, depending on what you want:

- A **source photo** of the face you want to wear. Any clear, front-facing
  JPEG/PNG works; six presets are built in if you just want to try it.
- A **webcam**, and Chrome or OBS to view the result.
- A **Cloudflare TURN app** — only if you need this to work over a cellular
  network. See the section further down.

Then you can run the following command to start the server:

```
uv run modal serve facestream.main
```

Or this command to deploy it:

```
uv run modal deploy -m facestream.main
```

## Choosing compute

Every knob below is an environment variable read when you deploy, so you can
change hardware without touching code:

```
FACESTREAM_GPU=L40S uv run modal deploy -m facestream.main
```

### Which GPU

The pipeline runs two small models per frame — SCRFD face detection at 640x640
and inswapper_128 at 128x128. It is bound by kernel launch latency, not by
memory bandwidth, so the fastest card is **not** the biggest card. Past roughly
an L40S you are paying for capacity this workload never touches.

| `FACESTREAM_GPU` | Notes |
| --- | --- |
| `T4` | The old default. Works, and is the cheapest thing that does. |
| `L4` | Solidly faster than T4 for not much more. Good value pick. |
| `A10G` | Similar tier to L4, sometimes better availability. |
| `L40S` | **Default.** Best latency per dollar for this workload. |
| `A100-40GB`, `A100-80GB` | More expensive than L40S with no gain here. |
| `H100`, `H200`, `B200` | Overkill. You are renting HBM you will not use. |

See [Modal's pricing page](https://modal.com/pricing) for current rates.

If the stream still isn't smooth after switching cards, the bottleneck is
probably not the GPU:

- **The network.** WebRTC latency is mostly round trips. Pin the deployment near
  yourself with `FACESTREAM_REGION=us-east-1` (or `eu-west-1`, etc.). This
  usually helps more than the GPU does.
- **Your upstream bandwidth.** 720p30 needs roughly 2.5 Mbit/s upstream. Lower
  it with `?bitrate=1500` on the page URL, or drop to `?res=480`.
- **Cold starts.** The first connection waits ~20s for a container. Set
  `FACESTREAM_MIN_CONTAINERS=1` to keep one warm — that bills GPU time while
  idle, so it is off by default.

### All settings

| Variable | Default | What it does |
| --- | --- | --- |
| `FACESTREAM_GPU` | `L40S` | GPU type, any string Modal accepts. |
| `FACESTREAM_CPU` | `8` | Cores per container. WebRTC decode/encode is CPU work, so don't go too low. |
| `FACESTREAM_TIMEOUT` | `3600` | Hard cap on a single session, in seconds. |
| `FACESTREAM_WS_IDLE_TIMEOUT` | `120` | Hang up on a peer that has stopped talking. |
| `FACESTREAM_SCALEDOWN_WINDOW` | `300` | How long an idle container is kept. Longer means OBS scene switches reconnect instantly. |
| `FACESTREAM_MIN_CONTAINERS` | `0` | Containers kept warm. `1` removes cold starts, and bills for it. |
| `FACESTREAM_MAX_CONTAINERS` | unset | Ceiling on concurrent containers, i.e. on spend. |
| `FACESTREAM_MAX_CONCURRENT_INPUTS` | `4` | Requests per container. Must stay above 1 — a live websocket holds one slot for the whole session. Extra streams share the same GPU. |
| `FACESTREAM_REGION` | unset | Modal region, e.g. `us-east-1`. |
| `FACESTREAM_DET_SIZE` | `640` | Detector input size. `320` is much cheaper but misses small faces. |
| `FACESTREAM_TRACK_DET_SIZE` | `320` | Detector input size while tracking a face already found. |
| `FACESTREAM_FACE_TRACKING` | `1` | Search a crop around the last known face instead of the whole frame. |
| `FACESTREAM_FAST_PASTE_BACK` | `1` | Composite the face inside its bounding box rather than over the whole frame. |
| `FACESTREAM_STATS_INTERVAL` | `150` | Log a timing summary every N frames. `0` disables. |

The session timeout deserves a note. The upstream default was 120 seconds, which
protects the public demo's GPU budget but cuts a stream off after two minutes.
It is an hour here, and the client heartbeats every 15s so a browser that dies
without closing its socket gets dropped after `FACESTREAM_WS_IDLE_TIMEOUT`
rather than holding a GPU open. Set `FACESTREAM_TIMEOUT` back down if you would
rather have the hard cap.

`GET /healthz` on the deployment reports the configuration a container is
actually running with.

## Use it as a camera in OBS

Add `?obs=1` to the URL for a chromeless, full-bleed version of the page: no
title, no upload panel, no preview thumbnail, nothing but the swapped video. It
picks its face from the URL, so nothing needs clicking, and it reconnects on its
own instead of putting up a dialog no one is there to answer.

```
https://<your-app>.modal.run/?obs=1&face=rock
```

### Option A: Browser Source

The cleanest route — OBS composites the video directly, no second window.

1. **Launch OBS with camera access enabled.** Its embedded browser blocks
   webcams unless you ask for them, and it cannot show a permission prompt:

   - Windows — edit your shortcut's Target:
     `"C:\Program Files\obs-studio\bin\64bit\obs64.exe" --enable-media-stream --use-fake-ui-for-media-stream`
   - macOS: `/Applications/OBS.app/Contents/MacOS/OBS --enable-media-stream --use-fake-ui-for-media-stream`
   - Linux: `obs --enable-media-stream --use-fake-ui-for-media-stream`

   Without `--enable-media-stream` the source stays black and the page reports
   that the MediaDevices API is missing.

2. **Add a Browser source** with your `?obs=1&face=...` URL, Width `1280`,
   Height `720` (match `?res=`, so the page renders 1:1).

3. **Tick "Shutdown source when not visible"** and **"Refresh browser when scene
   becomes active"**. The stream — and the GPU bill — then only runs while the
   scene is live.

4. If OBS grabs the wrong webcam, name the one you want with
   `&camera=logitech` (any part of the device label, case insensitive).

### Option B: Window Capture

No launch flags needed, at the cost of a browser window on screen and a little
more CPU.

1. Open the `?obs=1&face=...` URL in Chrome, ideally with `--kiosk`.
2. Add a **Window Capture** source in OBS and pick that window.

### Sending it to Zoom, Meet or Discord

Once the source looks right in OBS, hit **Start Virtual Camera**. FaceStream
then shows up as a webcam in any other app.

### URL options

| Option | Default | What it does |
| --- | --- | --- |
| `obs=1` | off | Chromeless output, auto-reconnect, no dialogs. |
| `face=<key\|url>` | none | Start immediately with this face. Keys: `rock`, `michelle`, `adam`, `selena`, `lebron`, `lucy`. A URL has to allow cross-origin fetches. |
| `res=` | `720` | Camera resolution: `480`, `540`, `720` or `1080`. |
| `fps=` | `30` | Camera frame rate. |
| `bitrate=` | `3000` | Max video bitrate in kbit/s. Lower it on a thin uplink. |
| `mirror=0` | mirrored | Stop flipping the image, so text reads correctly on stream. |
| `fit=contain` | `cover` | Letterbox instead of filling the canvas. |
| `camera=<text>` | none | Pick a webcam by label substring or deviceId. |
| `stats=1` | off | Overlay live resolution, fps, round trip time and packet loss. |
| `degradation=` | `maintain-resolution` in OBS mode | How the encoder gives up under pressure: `maintain-resolution`, `maintain-framerate` or `balanced`. |
| `retries=` | `20` | Reconnect attempts before giving up. |
| `server=<host>` | this host | Point the page at a different deployment. |

Start with `&stats=1` while you tune. If it reports a resolution below what you
asked for, you are bandwidth limited, not GPU limited — lower `bitrate` or
`res`.

### Optional: TURN Server for Cellular Networks

On most cellular networks you need a TURN server for WebRTC to work. You can create a TURN app on [Cloudflare](https://developers.cloudflare.com/calls/turn/). To use those with this app you need to:

1. Create a secret called `facestream` in modal with the following values:

```
TURN_TOKEN_ID=your-turn-token-id
TURN_API_TOKEN=your-turn-api-token
```

2.  Comment out the following line in [src/facestream/main.py](src/facestream/main.py):

```
...
secrets=[
    modal.Secret.from_name(
        "facestream",
        required_keys=[SECRET_KEY_TURN_TOKEN_ID, SECRET_KEY_TURN_API_TOKEN],
    )
]
...
```

## Credits

- This project was inspired by and uses the model of [Deep Live Cam](https://github.com/hacksider/Deep-Live-Cam). Go check out their project. They have some extra features that I didn't implement here. Note that the model used in that project (and therefore also this one) is only for non-commercial use.

- [Modal](https://modal.com) made this easy to build and deploy. They are generously providing free credits to host the live demo.
