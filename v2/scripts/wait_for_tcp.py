from __future__ import annotations

import argparse
import socket
import time


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Wait for a TCP endpoint to accept connections.")
    parser.add_argument("host")
    parser.add_argument("port", type=int)
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--interval-seconds", type=float, default=0.5)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    deadline = time.monotonic() + float(args.timeout_seconds)
    last_error = ""
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((args.host, int(args.port)), timeout=2.0):
                print(f"{args.host}:{args.port} is ready")
                return
        except OSError as exc:
            last_error = str(exc)
            time.sleep(float(args.interval_seconds))
    raise SystemExit(f"Timed out waiting for {args.host}:{args.port}: {last_error}")


if __name__ == "__main__":
    main()
