"""Bounded, local-only WSGI server for the demo."""

from waitress import serve

from .app import app


def main():
    serve(app, host="127.0.0.1", port=8765, threads=8, connection_limit=100,
          max_request_body_size=16 * 1024)


if __name__ == "__main__":
    main()
