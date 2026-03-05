# Vizio Remote

PyQt5 desktop remote control for Vizio SmartCast TVs. Replaces the physical remote with a dark-themed GUI that talks directly to the TV's REST API over the local network.

![Python](https://img.shields.io/badge/python-3.10+-blue) ![PyQt5](https://img.shields.io/badge/GUI-PyQt5-green) ![License](https://img.shields.io/badge/license-MIT-lightgrey)

## Features

- Full d-pad navigation, volume, channel, media controls
- Input switching via dropdown (HDMI, SmartCast, Tuner, etc.)
- Sleep timer with preset durations
- Live status bar — power state, current input, volume level
- Keyboard shortcuts (arrows, Enter, Esc, +/-, Space, M, H)
- Dark theme styled like a real remote

## Tested On

- **TV**: Vizio D24h-G9 (firmware 3.22.15)
- **OS**: Manjaro Linux / Arch

## Setup

```bash
cd vizio-remote
python3 -m venv .venv
.venv/bin/pip install PyQt5 requests
```

### Pairing

Before first use, pair with your TV to get an auth token:

```bash
# Start pairing (TV will show a PIN)
curl -sk -X PUT -H "Content-Type: application/json" \
  "https://<TV_IP>:7345/pairing/start" \
  -d '{"DEVICE_ID":"my-remote","DEVICE_NAME":"my-pc"}'

# Complete pairing with the PIN shown on screen
curl -sk -X PUT -H "Content-Type: application/json" \
  "https://<TV_IP>:7345/pairing/pair" \
  -d '{"DEVICE_ID":"my-remote","CHALLENGE_TYPE":1,"RESPONSE_VALUE":"<PIN>","PAIRING_REQ_TOKEN":<TOKEN>}'
```

The response contains your `AUTH_TOKEN`. Edit the constants at the top of `vizio_remote.py`:

```python
TV_IP = "10.26.209.142"
TV_PORT = 7345
AUTH_TOKEN = "your_token_here"
```

## Usage

```bash
.venv/bin/python vizio_remote.py
```

### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| Arrow keys | D-pad navigation |
| Enter | OK / Select |
| Esc | Back |
| +/- | Volume up/down |
| M | Mute toggle |
| H | Home |
| Space | Play |

## Research

See [RESEARCH.md](RESEARCH.md) for detailed API documentation, all discovered endpoints, and security research notes.

## DNS Tools

`dns_proxy.py` and `dns_intercept.py` are experimental tools for intercepting and logging the TV's DNS traffic. See RESEARCH.md for details and requirements.
