"""Start the web app on 127.0.0.1 only:  python -m app  [--port 8765]"""
import argparse
import sys
import threading

import uvicorn

from .paths import UnsafeLocation
from .store import Damaged, StoreTooNew
from .web import create_app

HOST = "127.0.0.1"


def serve(app, port: int) -> int:
    """Run the server and return the exit code. The address is announced only once the port is really bound, so a
    second copy that cannot start never claims to be running."""
    server = uvicorn.Server(uvicorn.Config(app, host=HOST, port=port, access_log=False, log_level="warning"))
    finished = threading.Event()

    def announce():
        while not finished.wait(0.1):
            if server.started:
                print(f"Matter Workbench on http://{HOST}:{port}  (Ctrl+C to stop)", flush=True)
                return

    threading.Thread(target=announce, daemon=True).start()
    try:
        server.run()
    except SystemExit as e:                     # uvicorn exits this way when it cannot bind
        code = e.code if isinstance(e.code, int) else int(bool(e.code))
    else:
        code = 0
    finally:
        finished.set()
    if not server.started and code:
        print(f"Cannot start: the server did not start. Is port {port} already in use? Close the other copy or "
              "pass --port.", file=sys.stderr)
    return code


def main() -> int:
    ap = argparse.ArgumentParser(prog="python -m app")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--demo", action="store_true", help="throwaway data, synthetic clients")
    args = ap.parse_args()
    try:
        if args.demo:
            from .demo import create_demo_app
            app = create_demo_app()
        else:
            app = create_app()
    except FileNotFoundError:
        print("Cannot start: the demo needs the test fixtures, which only the source project has.", file=sys.stderr)
        return 2
    except (UnsafeLocation, Damaged, StoreTooNew) as e:
        print(f"Cannot start: {e}", file=sys.stderr)
        return 2
    return serve(app, args.port)


if __name__ == "__main__":
    sys.exit(main())
