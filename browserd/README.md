# browserd — the shared browser lane

A browser Nelson and Sock can **both** drive, from anywhere. Chromium runs on
an always-on machine (Spine); this service wraps Chrome DevTools Protocol and
exposes a small HTTPS REST API plus a phone-first web UI.

Spec: [issue #11](https://github.com/savvautops/the-architect/issues/11) ·
Roadmap: project board "The Architect — roadmap"

## Why it exists

`saomusebrowser` (Muse's inbuilt browser) is polished but restricted: no
external URL, no shared session. Nelson's existing sao browser lacked the
controls. browserd is the better option both can use externally — and it
becomes The Architect's browser lane: the **A-tier (DOM)** + **C-tier
(vision)** substrate for the pixel-change verifier (#3) and tool registry
(#4).

## Quickstart (local)

```bash
cd browserd
export BROWSERD_TOKEN="$(openssl rand -hex 24)"
export CHROME_BIN=/path/to/chromium   # if chromium isn't on PATH
python3 browserd.py
# UI: http://localhost:8901/   (enter token when prompted)
# API: curl -H "Authorization: Bearer $BROWSERD_TOKEN" localhost:8901/api/status
```

Stdlib only — no pip install. Chromium must exist; browserd launches it
headless with `--remote-debugging-port` and a persistent profile dir
(`BROWSERD_PROFILE`, default `./profile`), so logins survive restarts. If
Chromium is already running with remote debugging on, browserd attaches to
it instead of launching.

## Deploy on Spine (via Nukbox)

```bash
cd browserd
cp .env.example .env   # then set a real BROWSERD_TOKEN
docker compose up -d --build
```

Then expose it exactly like the existing `saobrowser` tunnel:

```bash
cloudflared tunnel create browserd   # or reuse the saobrowser tunnel
cloudflared tunnel route dns <tunnel> browser.nelson-domain.tld
```

Point the tunnel at `http://localhost:8901`. Nelson opens the public URL on
his phone; Sock drives the same session over HTTPS from the sandbox (plain
HTTPS only — no websocket needed on the driver's side).

## API

All routes except `GET /healthz` require `Authorization: Bearer <token>`.
Every action returns JSON evidence (`before`/`after`, resolved points,
`loaded` flags) — the call is not the proof.

| Method | Route | Body | Returns |
|---|---|---|---|
| GET | `/healthz` | — | `{ok, browserd}` |
| GET | `/api/status` | — | browser version, url, viewport, tabs |
| POST | `/api/navigate` | `{url}` | `{before, after, loaded, navigated}` |
| POST | `/api/back` `…/forward` `…/reload` | — | `{before, after, loaded}` |
| GET | `/api/screenshot` | — | PNG bytes (viewport) |
| POST | `/api/click` | `{selector}` or `{x,y}` | `{ok, point, url_before, url_after}` / `not-found` |
| POST | `/api/type` | `{text, selector?}` | `{ok, chars}` / `not-found` |
| POST | `/api/key` | `{key: Enter\|Tab\|Escape\|…}` | `{ok, key, url}` |
| GET | `/api/dom` | `?limit=` | simplified accessibility tree |
| GET | `/api/tabs` | — | open page targets |
| POST | `/api/tabs` | `{url?}` | new tab |
| POST | `/api/tabs/activate` | `{id}` | attach driver to tab |
| DELETE | `/api/tabs?id=` | — | close tab |

Tier mapping: `selector` clicks are A-tier (DOM-resolved, then real input
events at the resolved point); `{x,y}` clicks are C-tier fallback;
`/api/screenshot` feeds the #3 pixel-change verifier; `/api/key` hosts the
#7 verified keyboard nodes.

## Verification checklist

- [ ] Sock drives navigate → screenshot → click → screenshot over HTTPS; the
      *expected* pixels changed (#3)
- [ ] Nelson opens the public URL on his phone, taps the page, types —
      both drivers stay in sync (one Chromium, two drivers)
- [ ] Restart container → session/profile persisted, still logged in

## Security

Fail-closed: refuses to start without `BROWSERD_TOKEN`; every route except
`/healthz` 401s without the bearer token. Keep it behind the tunnel —
never expose 8901 directly.
