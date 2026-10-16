# Bushfire atlas

One view of Australia's bushfire data. Each state's incidents and warnings, NASA FIRMS hotspots
and fire history are read from data_library's shared **green** layer and linked into **fire
events** by place and time, never by an agency's incident id. An event lists every source record
in it, with the agency's own id kept as provenance. It shows whether more than one state reports
the fire, when it was first and last seen, and the highest warning level any source gives it.

This is a read-only spoke of [data_library](https://github.com/AEENRA-ClAI/data_library). The app
never fetches a source and never writes green. Janet runs it on the box.

## Run it on a laptop

```bash
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python scripts/make_fixture.py --root /tmp/atlas_fixture     # constructed data
EXTERNAL_DATA_ROOT=/tmp/atlas_fixture .venv/bin/python app.py           # http://127.0.0.1:8622
```

Point `EXTERNAL_DATA_ROOT` at a real data_library store (the folder that holds `ext_data/green`
and `map_layers`) to see real data. With no data there, the app still starts and says which
of these is true: no data is mounted, the store has no green layer, or green holds no bushfire
source yet.

## Routes

| route | answer |
|---|---|
| `GET /healthz` | `{"ok": true, "data_mounted": …}`. Always 200 while the app is serving. |
| `GET /api/fires` | events in a window: `end` (ISO, default now), `hours` (default 72), `jurisdiction`, `level`, `kind` (comma lists) |
| `GET /api/fires/<event_id>` | one event: every member record with its agency id, plus its shapes from `map_layers` |
| `GET /` | the page: the offline map, the events table, the event detail and the sources |

## Run it under Janet

Janet clones the repo into `/data/workspace/bushfire-atlas` and builds its `.venv` from
`requirements.txt`. She then starts it with the command in
[docs/janet_app_spec.json](docs/janet_app_spec.json).

**In Janet's Apps tab**, open **➕ Add an app** and fill in:

| field | value |
|---|---|
| Name | `Bushfire atlas` |
| Git URL | `https://github.com/AEENRA-ClAI/bushfire_atlas` |
| Path | leave empty: an empty path with a Git URL is what makes Janet clone the repo |
| Command | `.venv/bin/gunicorn "app:create_app()" --bind {host}:{port} --workers 1 --threads 4` |
| Port | `8622` |
| Health path | `/healthz` |
| Environment | `EXTERNAL_DATA_ROOT=/library` |
| Set it up automatically | ticked |

The same spec as JSON is what Janet's `POST /api/apps` takes (behind Janet's login). You can also
add it by hand to the live `apps.yaml`, where `health_path` is written `health: {path: /healthz}`.

- **Data.** `/library` is the data_library store, mounted read-only into Janet's container.
- **State.** Janet sets `APP_STATE_DIR=/data/app_state/bushfire-atlas` herself. This version
  writes nothing there.
- **HTTPS.** Caddy serves the app at its port + 100, which is `https://<box>:8722`.
- **Private repo.** The GitHub App must be installed on `AEENRA-ClAI/bushfire_atlas`, or the clone
  fails.
- **Worker count.** Keep one worker: the green read cache lives in the process.

## Tests

```bash
python scripts/gate.py           # compile, tests, real-Chromium check, kit drift
python -m pytest -q              # the tests alone
```
