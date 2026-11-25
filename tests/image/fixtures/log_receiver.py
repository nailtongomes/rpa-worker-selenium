"""Recebe o POST do fim do container e os pings (cenários do portão).

Uso: python3 log_receiver.py <porta> <arquivo.jsonl>

Cada requisição vira uma linha no .jsonl (gravada antes da resposta: o container
pode terminar logo depois): método, caminho, JSON do corpo ou campos/arquivos do multipart.
"""
import json
import os
import sys
from email.parser import BytesParser
from email.policy import HTTP
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

OUT = sys.argv[2]


def parse_body(content_type: str, body: bytes) -> dict:
    if content_type.startswith("application/json"):
        return {"json": json.loads(body)}
    if content_type.startswith("multipart/form-data"):
        message = BytesParser(policy=HTTP).parsebytes(
            f"Content-Type: {content_type}\r\n\r\n".encode() + body)
        fields, files = {}, {}
        for part in message.iter_parts():
            name = part.get_param("name", header="content-disposition")
            payload = part.get_payload(decode=True) or b""
            if part.get_filename():
                files[name] = {"nome": part.get_filename(), "tipo": part.get_content_type(),
                               "bytes": len(payload), "inicio": payload[:4].hex(),
                               "texto": payload.decode("utf-8", "replace") if name == "log" else ""}
            else:
                fields[name] = payload.decode("utf-8")
        return {"campos": fields, "arquivos": files}
    return {"bytes": len(body)}


class Handler(BaseHTTPRequestHandler):
    def _record(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        entry = {"metodo": self.command, "caminho": self.path,
                 **parse_body(self.headers.get("Content-Type", ""), body)}
        with open(OUT, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    do_GET = do_POST = _record

    def log_message(self, *args):
        pass


ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()
