from __future__ import annotations

import argparse
import json
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from build_site_data import build_site_data, write_output_files
from chatbot_backend import BakeryChatbot, STORE_DATA_PATH


ROOT_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = ROOT_DIR.parent / "frontend"


def ensure_store_data() -> None:
    if STORE_DATA_PATH.exists():
        return
    write_output_files(build_site_data())


class BakeryRequestHandler(BaseHTTPRequestHandler):
    chatbot: BakeryChatbot

    def _chatbot(self) -> BakeryChatbot:
        # Reload from disk for each request so prompt/data edits show up immediately.
        return BakeryChatbot.from_default_store()

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(HTTPStatus.NO_CONTENT)
        self._send_common_headers("application/json; charset=utf-8")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/api/health":
            self._handle_health()
            return
        self._serve_static(path)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/api/chat":
            self._handle_chat()
            return
        self._send_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return

    def _send_common_headers(self, content_type: str) -> None:
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def _send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._send_common_headers("application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle_health(self) -> None:
        self._send_json(self._chatbot().health())

    def _handle_chat(self) -> None:
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_json({"error": "Invalid Content-Length"}, status=HTTPStatus.BAD_REQUEST)
            return

        raw_body = self.rfile.read(content_length)
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError:
            self._send_json({"error": "Body must be valid JSON"}, status=HTTPStatus.BAD_REQUEST)
            return

        message = str(payload.get("message", "")).strip()
        history = payload.get("history") or []
        if not message:
            self._send_json({"error": "Field 'message' is required"}, status=HTTPStatus.BAD_REQUEST)
            return

        sanitized_history = []
        for item in history[-8:]:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role", "")).strip()
            content = str(item.get("content", "")).strip()
            if role in {"user", "assistant"} and content:
                sanitized_history.append({"role": role, "content": content})

        result = self._chatbot().chat(message, sanitized_history)
        self._send_json(result)

    def _serve_static(self, raw_path: str) -> None:
        relative_path = raw_path.lstrip("/") or "index.html"
        target_path = (FRONTEND_DIR / relative_path).resolve()

        try:
            target_path.relative_to(FRONTEND_DIR.resolve())
        except ValueError:
            self._send_json({"error": "Invalid path"}, status=HTTPStatus.FORBIDDEN)
            return

        if target_path.is_dir():
            target_path = target_path / "index.html"

        if not target_path.exists() or not target_path.is_file():
            self.send_response(HTTPStatus.NOT_FOUND)
            self._send_common_headers("text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Not found")
            return

        mime_type, _ = mimetypes.guess_type(str(target_path))
        content_type = mime_type or "application/octet-stream"
        body = target_path.read_bytes()

        self.send_response(HTTPStatus.OK)
        self._send_common_headers(f"{content_type}; charset=utf-8" if content_type.startswith("text/") or content_type in {"application/javascript", "application/json"} else content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Local grounded chatbot server for the bakery site.")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind the local server.")
    parser.add_argument("--port", default=8000, type=int, help="Port to bind the local server.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    ensure_store_data()

    BakeryRequestHandler.chatbot = BakeryChatbot.from_default_store()
    server = ThreadingHTTPServer((args.host, args.port), BakeryRequestHandler)

    health = BakeryRequestHandler.chatbot.health()
    print(f"Serving frontend at http://{args.host}:{args.port}")
    print(f"Chat mode: {health['chatMode']}")
    print(f"Gemini model: {health['model']}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
