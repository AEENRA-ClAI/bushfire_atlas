"""bushfire_atlas — the web app. Janet runs it; on a laptop: `python app.py`.

Routes:
  GET /healthz               always 200 while the process serves; says whether data is mounted
  GET /api/fires             fire events in a time window (end, hours, jurisdiction, level, kind)
  GET /api/fires/<event_id>  one event: every source record in it, with its agency id as
                             provenance, and the members' shapes from map_layers
  GET /                      the page: the offline map, the events table, the event detail

Read-only throughout: nothing here writes green, the map layers or the code checkout.
"""
from __future__ import annotations

import os

from flask import Flask, jsonify, render_template, request

from atlas.config import Settings, load_settings
from atlas.fires import BadQuery, FireService, parse_query
from atlas.layers import LayerReader
from atlas.vocabulary import JURISDICTIONS, RECORD_KINDS, WARNING_LEVELS


def create_app(settings: Settings | None = None) -> Flask:
    settings = settings or load_settings()
    app = Flask(__name__, static_folder="static", template_folder="templates")
    service = FireService(settings)
    layers = LayerReader(settings)

    @app.after_request
    def _headers(resp):
        # Everything the page loads is served from here: no CDN, no tiles, no external call.
        resp.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
            "connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'self'")
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        return resp

    @app.get("/healthz")
    def healthz():
        # Healthy means serving. Missing data is the honest-empty state the page explains,
        # not a crash: the app is safe to start before the hub's data lands.
        return jsonify(ok=True, app="bushfire_atlas",
                       data_root=settings.data_root,
                       data_mounted=os.path.isdir(settings.data_root),
                       green_present=os.path.isdir(settings.green_root))

    @app.get("/api/fires")
    def api_fires():
        try:
            q = parse_query(request.args, settings.window_hours)
        except BadQuery as exc:
            return jsonify(state="bad_query", message=str(exc)), 400
        return jsonify(service.fires(q))

    @app.get("/api/fires/<event_id>")
    def api_fire(event_id):
        try:
            q = parse_query(request.args, settings.window_hours)
        except BadQuery as exc:
            return jsonify(state="bad_query", message=str(exc)), 400
        status, body = service.event(event_id, q, layers)
        return jsonify(body), status

    @app.get("/")
    def index():
        return render_template("index.html", jurisdictions=JURISDICTIONS,
                               levels=WARNING_LEVELS, kinds=RECORD_KINDS,
                               window_hours=settings.window_hours)

    return app


if __name__ == "__main__":
    s = load_settings()
    create_app(s).run(host=s.host, port=s.port)
