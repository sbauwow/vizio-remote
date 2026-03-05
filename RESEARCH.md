# Vizio D24h-G9 Research Notes

## Device Info
- **Model**: D24h-G9, 24" Series D
- **Firmware**: 3.22.15 (build 322150)
- **Cast firmware**: 1.27.96538 (stable-channel)
- **Serial**: 05LINIXSCV05334
- **ESN**: LINIXSCV0505334
- **WiFi MAC**: A0:6A:44:EE:7F:DF
- **Ethernet MAC**: A0:6A:44:E9:F1:CB
- **IP**: 10.26.209.142 (DHCP, WiFi)
- **Cast UUID**: c20cecaa-fa75-a4fc-9c91-5b83174cd1c0
- **Cloud Device ID**: 8DE99D8612E15499E41047BF72CCF006
- **UMA Client ID**: 0a4e6a91-0425-4754-be7b-5f3816cc9eff

## Open Ports
| Port | Service | Auth | Notes |
|------|---------|------|-------|
| 7345 | SmartCast REST API | `AUTH: Z6a2sannbw` | Full TV control |
| 8005 | Unknown | ? | Empty reply, binary protocol |
| 8008 | Google Cast / DIAL | **None** | Device info, app discovery, config writes |
| 8009 | Cast v2 (protobuf/TLS) | Client cert | Self-signed cert, CN=device UUID, rotates every 2 days |
| 9000 | Cast v2 (TLS) | Client cert | Same as 8009, handshake failure without cert |

## SmartCast API (port 7345)

Base: `https://10.26.209.142:7345`
Auth header: `AUTH: Z6a2sannbw`
All settings use one-time hashvals (anti-replay) — must GET fresh hash before each PUT.

### Readable Endpoints
| Endpoint | Returns |
|----------|---------|
| `/state/device/power_mode` | Power state (1=on, 0=standby) |
| `/state/device/deviceinfo` | Full device info, capabilities, inputs |
| `/menu_native/dynamic/tv_settings/picture` | Picture mode, backlight, brightness, contrast, color, tint, sharpness |
| `/menu_native/dynamic/tv_settings/picture/color_calibration` | Color calibration settings |
| `/menu_native/dynamic/tv_settings/picture/more_picture` | Advanced picture settings |
| `/menu_native/dynamic/tv_settings/audio` | Volume, mute, speakers, surround |
| `/menu_native/dynamic/tv_settings/devices/current_input` | Current input name |
| `/menu_native/dynamic/tv_settings/devices/name_input` | All inputs with hashvals |
| `/menu_native/dynamic/tv_settings/network` | Connection type/status |
| `/menu_native/dynamic/tv_settings/network/manual_setup` | IP, gateway, DNS, MACs |
| `/menu_native/dynamic/tv_settings/timers` | Sleep timer, auto power off |
| `/menu_native/dynamic/tv_settings/closed_captions` | CC settings |
| `/menu_native/dynamic/tv_settings/system` | Language, power mode, aspect ratio, TV name, CEC |
| `/menu_native/dynamic/tv_settings/system/system_information/*` | TV/network/tuner/ULI info |
| `/menu_native/dynamic/tv_settings/system/reset_and_admin` | Factory reset, soft power cycle, system PIN, store demo |
| `/menu_native/dynamic/tv_settings/system/mobile_devices` | Paired devices list |
| `/menu_native/dynamic/tv_settings/system/cec` | CEC enable, device discovery |
| `/menu_native/dynamic/tv_settings/system/accessibility` | Accessibility settings |
| `/app/current` | Currently running app (null when idle) |

### Writable Settings (confirmed)
- **Current input** — switch via PUT with fresh hashval
- **Sleep timer** — Off, 30/60/90/120/180 minutes
- **Network config** — DHCP mode, IP, gateway, DNS, subnet
- **Picture mode** — Standard, Calibrated, Calibrated Dark, Vivid, Game, Computer
- **All picture values** — backlight, brightness, contrast, color, tint, sharpness
- **Audio settings** — surround sound, speakers, volume display
- **TV name** — via cast_name field
- **Store demo mode** — can enable/disable
- **System PIN** — readable/writable (currently empty)
- **Factory reset** — T_ACTION_V1 (triggerable)
- **Soft power cycle** — T_ACTION_V1 (triggerable)

## Cast/DIAL API (port 8008, NO AUTH)

### Confirmed Working
- `GET /ssdp/device-desc.xml` — UPnP device description
- `GET /setup/eureka_info` — Full device info (name, MAC, build, keys, etc.)
- `POST /setup/set_eureka_info` — **Rename TV** (confirmed: renamed to "pwn3d-tv")
- `GET /setup/supported_timezones` — All timezone options
- `GET /setup/configured_networks` — WiFi networks (currently empty)
- `GET /setup/offer` — OAuth-style token
- `GET /apps/YouTube` — DIAL app status (stopped/running)
- `GET /apps/ChromeCast` — Cast app status

### Interesting Fields from eureka_info
- `public_key` — RSA 2048-bit public key (for Cast pairing?)
- `uma_client_id` — Google analytics client ID
- `cast_build_revision` — 1.27.96538
- `cloud_device_id` — 8DE99D8612E15499E41047BF72CCF006
- `ssdp_udn` — c20cecaa-fa75-a4fc-9c91-5b83174cd1c0

## Escalation Findings

### What We Can Do Now
1. **Full remote control** — all buttons, inputs, settings via SmartCast API
2. **Rename TV** — unauthenticated via Cast endpoint
3. **Read all network config** — IPs, MACs, DNS, gateway
4. **Write network config** — change DNS, gateway, IP settings
5. **Trigger factory reset / soft reboot** — via SmartCast API actions
6. **Enable store demo mode** — loop demo content
7. **Set/read system PIN** — parental controls bypass
8. **Control HDMI-CEC** — send commands to connected HDMI devices

### DNS Hijack Vector
The TV's DNS is writable via API. Point `PREF_DNS` to our IP, intercept all DNS queries, spoof responses to redirect OTA updates, telemetry, and app traffic.

**Blocked by**: No root/sudo access. Cannot bind port 53 (`ip_unprivileged_port_start=1024`), create TUN interfaces, use raw sockets, or run tshark (not in `wireshark` group).

### Cast v2 MITM Vector
Port 9000 uses self-signed TLS cert (CN=device UUID, 2-day expiry). Could MITM cast sessions if we can get on the network path.

**Blocked by**: Same network capture limitations.

## Next Steps (require one of the following)

### Option A: Join `wireshark` group (recommended)
```bash
sudo gpasswd -a stathis wireshark
# Then log out and back in
```
- Enables tshark/dumpcap packet capture
- Can sniff all TV DNS queries, HTTP/HTTPS connections
- See exactly what domains the TV phones home to
- Capture OTA update URLs and certificate chains

### Option B: One-time sudo for DNS proxy
```bash
sudo ~/vizio-remote/.venv/bin/python dns_proxy.py --port 53 --bind 10.26.209.115
```
Then point TV DNS to 10.26.209.115 via API:
```bash
# Fetch fresh hash, set DNS
HASH=$(curl -sk -H "AUTH: Z6a2sannbw" \
  "https://10.26.209.142:7345/menu_native/dynamic/tv_settings/network/manual_setup" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['ITEMS'][0]['HASHVAL'])")
curl -sk -X PUT -H "AUTH: Z6a2sannbw" \
  "https://10.26.209.142:7345/menu_native/dynamic/tv_settings/network/manual_setup" \
  -d "{\"REQUEST\":\"MODIFY\",\"HASHVAL\":$HASH,\"VALUE\":{\"DHCP_MODE\":\"Off\",\"IP_ADDRESS\":\"10.26.209.142\",\"SUBNET_MASK\":\"255.255.255.0\",\"DEFAULT_GATEWAY\":\"10.26.209.106\",\"PREF_DNS\":\"10.26.209.115\",\"ALT_DNS\":\"8.8.8.8\"}}"
```

### Option C: Cloud VPS
- Run dns_proxy.py on port 53 of a public VPS
- Point TV DNS to VPS IP
- All queries logged remotely

### After DNS Capture
- Map all domains the TV contacts (telemetry, OTA, SmartCast cloud, ads)
- Identify OTA update server and protocol
- Spoof OTA endpoint to serve custom firmware
- Block ad/tracking domains
- Redirect SmartCast API calls

### Other Ideas (no root needed)
- **DIAL app injection** — craft POST to launch apps with custom parameters
- **CEC bus exploration** — enumerate and control HDMI-connected devices
- **Picture preset automation** — one-click "Movie Night" / "Gaming" profiles
- **Firmware analysis** — download OTA update package and analyze offline
- **Port 8005 reverse engineering** — binary protocol analysis
