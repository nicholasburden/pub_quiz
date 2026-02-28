"""Entry point: Flask + SocketIO initialization."""

from gevent import monkey
monkey.patch_all()

import logging

from flask import Flask, Response
from flask_socketio import SocketIO
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

from config import HOST, PORT, SECRET_KEY
from game.manager import GameManager
from api.routes import bp, init_routes
from api.socket_events import register_events
from metrics import update_live_gauges

logging.basicConfig(level=logging.INFO)

app = Flask(__name__)
app.config["SECRET_KEY"] = SECRET_KEY

socketio = SocketIO(app, async_mode="gevent", cors_allowed_origins="*")

game_manager = GameManager()

init_routes(game_manager)
app.register_blueprint(bp)

register_events(socketio, game_manager)


@app.route("/metrics")
def metrics():
    update_live_gauges(game_manager)
    return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)


if __name__ == "__main__":
    socketio.run(app, host=HOST, port=PORT)
