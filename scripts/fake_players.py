"""Spawn fake players against a running pub_quiz server.

Connects N socket.io clients to an already-running server, has them join a game
and answer each question after a random delay. Useful for poking the multiplayer
UX without opening a dozen browser tabs.

Requires `python-socketio[client]` and `requests` (already in dev deps).

Examples:

    # Boot a fresh server on :5099. Open the printed URL in your browser,
    # create a game from the home page, and the script will detect it and
    # drop 5 bots into the lobby. Server is torn down when this script exits.
    python scripts/fake_players.py --count 5

    # Same flow against an already-running server
    python scripts/fake_players.py --url http://localhost:5000

    # Join a specific game by id (skip the waiting step)
    python scripts/fake_players.py --url http://localhost:5000 --game-id ABC123 --count 3

    # Slower replies
    python scripts/fake_players.py --count 4 --min-delay 2 --max-delay 8
"""

import argparse
import pathlib
import random
import subprocess
import sys
import threading
import time

try:
    import requests
    import socketio
except ImportError:
    sys.stderr.write(
        "Missing deps. Install with:\n"
        "    pip install 'python-socketio[client]' requests\n"
    )
    sys.exit(1)


NAME_POOL = [
    "Ada", "Boris", "Cleo", "Dax", "Esme", "Finn", "Greta", "Hugo",
    "Iris", "Juno", "Kai", "Luna", "Milo", "Nia", "Otto", "Pip",
    "Quill", "Rex", "Sage", "Tess",
]


class FakeBot:
    def __init__(self, url, game_id, name, min_delay, max_delay, verbose=False):
        self.url = url
        self.game_id = game_id
        self.name = name
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.verbose = verbose
        self.sio = socketio.Client(reconnection=False, logger=False,
                                   engineio_logger=False)
        self.finished = threading.Event()
        self._register_handlers()

    def _log(self, msg):
        if self.verbose:
            print(f"[{self.name}] {msg}", flush=True)

    def _register_handlers(self):
        sio = self.sio

        @sio.event
        def connect():
            self._log("connected")
            sio.emit("join_game", {
                "game_id": self.game_id,
                "player_name": self.name,
                "is_host": False,
            })

        @sio.event
        def disconnect():
            self._log("disconnected")

        @sio.on("error")
        def on_error(data):
            print(f"[{self.name}] ERROR: {data.get('message')}", flush=True)
            self.finished.set()

        @sio.on("game_state")
        def on_game_state(data):
            self._log(f"joined ({data.get('state')})")

        @sio.on("new_question")
        def on_new_question(data):
            answers = data.get("answers", [])
            qnum = data.get("question_number")
            time_limit = data.get("time_limit", 30)
            delay = random.uniform(
                self.min_delay,
                min(self.max_delay, max(self.min_delay, time_limit - 1)),
            )

            choice = random.choice(answers) if answers else ""

            def _submit():
                if self.finished.is_set() or not self.sio.connected:
                    return
                self._log(f"Q{qnum} answering after {delay:.1f}s: {choice!r}")
                try:
                    self.sio.emit("submit_answer", {"answer": choice})
                except Exception as e:
                    self._log(f"submit failed: {e}")

            t = threading.Timer(delay, _submit)
            t.daemon = True
            t.start()

        @sio.on("question_results")
        def on_question_results(data):
            self._log(f"correct was {data.get('correct_answer')!r}")

        @sio.on("game_finished")
        def on_game_finished(data):
            ranks = data.get("rankings", [])
            mine = next((r for r in ranks if r.get("name") == self.name), None)
            self._log(f"finished, my rank: {mine}")
            self.finished.set()

        @sio.on("game_deleted")
        def on_game_deleted(_data):
            self._log("game deleted")
            self.finished.set()

    def run(self):
        try:
            self.sio.connect(self.url)
        except Exception as e:
            print(f"[{self.name}] connect failed: {e}", flush=True)
            return
        # Block until game ends, then disconnect cleanly.
        self.finished.wait()
        try:
            self.sio.disconnect()
        except Exception:
            pass


def boot_server(port, ready_timeout=15.0):
    """Spawn `app.py` as a subprocess on `port`. Returns (proc, base_url).

    Raises RuntimeError if the server doesn't accept connections within
    `ready_timeout` seconds, or if the subprocess exits early.
    """
    repo_root = pathlib.Path(__file__).resolve().parent.parent
    code = (
        "from gevent import monkey; monkey.patch_all()\n"
        "from app import app, socketio\n"
        f"socketio.run(app, host='127.0.0.1', port={port})\n"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", code],
        cwd=str(repo_root),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )

    url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + ready_timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(
                f"Server subprocess exited early (code {proc.returncode}). "
                f"Is port {port} already in use?"
            )
        try:
            requests.get(f"{url}/api/games", timeout=0.5)
            return proc, url
        except requests.exceptions.RequestException:
            time.sleep(0.3)

    proc.terminate()
    raise RuntimeError(f"Server didn't become ready within {ready_timeout:.0f}s")


def wait_for_new_game(url, poll_interval=1.0):
    """Block until a game appears that wasn't there when this call started.

    Returns the new game's id. Polls `/api/games` indefinitely; Ctrl-C to abort.
    """
    def _snapshot():
        try:
            resp = requests.get(f"{url}/api/games", timeout=2)
            return {g["id"] for g in resp.json()}
        except requests.exceptions.RequestException:
            return None

    baseline = _snapshot()
    while baseline is None:
        time.sleep(poll_interval)
        baseline = _snapshot()

    while True:
        time.sleep(poll_interval)
        current = _snapshot()
        if current is None:
            continue
        new = current - baseline
        if new:
            # Pick deterministically if more than one appeared in the same poll
            return sorted(new)[0]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default=None,
                    help="Base URL of an already-running server. If omitted, "
                         "a fresh server is started on --port and torn down on exit.")
    ap.add_argument("--port", type=int, default=5099,
                    help="Port for the auto-started server (ignored if --url is set)")
    ap.add_argument("--game-id", help="Game id to join (omit to wait for a new "
                                      "game to be created at the home page)")
    ap.add_argument("--count", type=int, default=3,
                    help="Number of fake players to spawn")
    ap.add_argument("--name-prefix", default="",
                    help="Optional prefix for bot names (otherwise picked from a pool)")
    ap.add_argument("--min-delay", type=float, default=1.0,
                    help="Min seconds before a bot submits its answer")
    ap.add_argument("--max-delay", type=float, default=6.0,
                    help="Max seconds before a bot submits its answer")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="Per-bot logging")
    args = ap.parse_args()

    if args.count < 1:
        ap.error("--count must be >= 1")
    if args.min_delay < 0 or args.max_delay < args.min_delay:
        ap.error("Need 0 <= --min-delay <= --max-delay")
    if args.url is None and args.game_id:
        ap.error("--game-id needs --url (the game must exist on a running server). "
                 "Without --url a fresh server is booted, which has no games yet.")

    server_proc = None
    try:
        if args.url is None:
            print(f"Starting server on port {args.port}…")
            server_proc, args.url = boot_server(args.port)
            print(f"Server ready at {args.url}")

        game_id = args.game_id
        if not game_id:
            print(f"Open {args.url}/ in your browser and create a game.")
            print("Waiting for a new game to appear… (Ctrl-C to abort)")
            game_id = wait_for_new_game(args.url)
            print(f"Detected game {game_id}")

        names = []
        pool = list(NAME_POOL)
        random.shuffle(pool)
        for i in range(args.count):
            base = pool[i] if i < len(pool) else f"Bot{i+1}"
            names.append(f"{args.name_prefix}{base}" if args.name_prefix else base)

        bots = [FakeBot(args.url, game_id, n,
                        args.min_delay, args.max_delay, args.verbose)
                for n in names]

        threads = []
        for b in bots:
            t = threading.Thread(target=b.run, daemon=True)
            t.start()
            threads.append(t)
            # Small stagger so the server logs are easier to read.
            time.sleep(0.2)

        print(f"Spawned {len(bots)} bots in game {game_id}: {', '.join(names)}")
        print("Ctrl-C to stop.")

        try:
            while any(t.is_alive() for t in threads):
                for t in threads:
                    t.join(timeout=0.5)
        except KeyboardInterrupt:
            print("\nStopping bots…")
            for b in bots:
                b.finished.set()
                try:
                    b.sio.disconnect()
                except Exception:
                    pass
    finally:
        if server_proc is not None:
            print("Shutting down server…")
            server_proc.terminate()
            try:
                server_proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                server_proc.kill()


if __name__ == "__main__":
    main()
