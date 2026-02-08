"""Entry point: Flask + SocketIO initialization."""

import eventlet
eventlet.monkey_patch()

import logging

from flask import Flask
from flask_socketio import SocketIO

from config import HOST, PORT, SECRET_KEY
from game.manager import GameManager
from api.routes import bp, init_routes
from api.socket_events import register_events

logging.basicConfig(level=logging.INFO)

app = Flask(__name__)
app.config["SECRET_KEY"] = SECRET_KEY

socketio = SocketIO(app, async_mode="eventlet", cors_allowed_origins="*")

game_manager = GameManager()

init_routes(game_manager)
app.register_blueprint(bp)

register_events(socketio, game_manager)

if __name__ == "__main__":
    socketio.run(app, host=HOST, port=PORT)
