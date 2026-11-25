"""Small server-rendered teaching UI. No directory serving, arbitrary upstream or generic RPC route."""
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from subprocess import SubprocessError
from urllib.parse import parse_qsl

HERE = Path(__file__).resolve().parent
LABS = HERE.parent.parent
HOST = '127.0.0.1'
DESK = f'http://{HOST}:18038'
PAYER = f'http://{HOST}:18039'


def text(value):
    return escape(str(value)) if value is not None else '尚未核出'


def fields(*rows):
    return '<dl>' + ''.join(f'<dt>{text(k)}</dt><dd>{text(v)}</dd>' for k, v in rows) + '</dl>'


def button(path, label, hidden=None):
    inputs = ''.join(f'<input type="hidden" name="{text(k)}" value="{text(v)}">' for k, v in (hidden or {}).items())
    return f'<form action="{path}" method="post">{inputs}<button>{text(label)}</button></form>'


class Handler(BaseHTTPRequestHandler):
    def send_body(self, body, kind='text/html', status=200):
        data = body.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', f'{kind}; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'same-origin')
        self.send_header('Content-Security-Policy', "default-src 'none'; style-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def document(self, title, content, status=200):
        self.send_body(f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{text(title)} · 本地对账实验</title>
<link rel="stylesheet" href="/desk.css"></head><body><main><h1>{text(title)}</h1>{content}</main></body></html>''', status=status)

    def json(self, value):
        self.send_body(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'application/json')

    def redirect(self, path):
        self.send_response(303)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Location', path)
        self.send_header('Content-Length', '0')
        self.end_headers()

    def dispatch(self, post):
        host = f'{HOST}:{self.server.server_port}'
        if self.headers.get('Host') != host or (post and self.headers.get('Origin') != 'http://' + host):
            self.send_error(403, 'Loopback host and same-origin forms only')
            return
        try:
            if not post:
                if self.path == '/desk.css':
                    self.send_body((HERE / 'desk.css').read_text(), 'text/css')
                else:
                    self.get()
                return
            size = int(self.headers.get('Content-Length', '0'))
            if self.headers.get_content_type() != 'application/x-www-form-urlencoded' or not 0 <= size <= 512:
                self.send_error(400, 'Invalid form')
                return
            pairs = parse_qsl(self.rfile.read(size).decode('ascii'), keep_blank_values=True, strict_parsing=True, max_num_fields=3)
            values = dict(pairs)
            if len(values) != len(pairs):
                raise ValueError('请重新打开表单，不要重复字段。')
            self.post(values)
        except (OSError, SubprocessError, RuntimeError, ValueError, KeyError) as exc:
            self.document('暂停操作，先核实', f'<p>{text(exc)}</p><p>未取得完整结果，不要自动重发交易或放行订单。检查本轮节点、订单服务和数据库，再回到工作台读取现状。</p><p><a href="/">返回工作台</a></p>', 409 if isinstance(exc, ValueError) else 503)

    def do_GET(self):
        self.dispatch(False)

    def do_POST(self):
        self.dispatch(True)


def serve(port, handler):
    with ThreadingHTTPServer((HOST, port), handler) as server:
        print(f'{handler.__name__} http://{HOST}:{port}/', flush=True)
        server.serve_forever()
