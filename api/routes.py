"""REST routes: serve pages, list/create games, proxy categories."""

from flask import Blueprint, jsonify, render_template, request

from game.manager import GameManager
from api.opentdb import opentdb

bp = Blueprint("main", __name__)

# Will be set by app.py
game_manager: GameManager = None  # type: ignore


def init_routes(manager: GameManager):
    global game_manager
    game_manager = manager


@bp.route("/")
def index():
    return render_template("index.html")


@bp.route("/lobby/<game_id>")
def lobby(game_id):
    game = game_manager.get_game(game_id)
    if not game:
        return render_template("index.html"), 404
    return render_template("lobby.html", game_id=game_id, game_name=game.name)


@bp.route("/quiz/<game_id>")
def quiz(game_id):
    game = game_manager.get_game(game_id)
    if not game:
        return render_template("index.html"), 404
    return render_template("quiz.html", game_id=game_id, game_name=game.name)


@bp.route("/results/<game_id>")
def results(game_id):
    game = game_manager.get_game(game_id)
    if not game:
        return render_template("index.html"), 404
    return render_template("results.html", game_id=game_id, game_name=game.name)


@bp.route("/api/games", methods=["GET"])
def list_games():
    return jsonify(game_manager.list_joinable_games())


@bp.route("/api/games", methods=["POST"])
def create_game():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid request"}), 400

    game_name = data.get("game_name", "").strip()
    player_name = data.get("player_name", "").strip()
    if not game_name or not player_name:
        return jsonify({"error": "Game name and player name are required"}), 400

    # Create game without a socket SID yet; the host will join via socket
    game = game_manager.create_game(game_name, player_name, sid="pending")
    return jsonify({"game_id": game.id, "game_name": game.name})


@bp.route("/api/categories")
def categories():
    cats = opentdb.get_categories()
    return jsonify(cats)
