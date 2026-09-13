#!/usr/bin/env python3
import io, json, os, secrets, socket, threading, time, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MOBILE = ROOT / 'mobile'
DATA = ROOT / 'data'
DATA.mkdir(exist_ok=True)
MAX_FILE = 25 * 1024 * 1024
PAIR_TTL = 30 * 60
FILE_TTL = 10 * 60
CLEAN_INTERVAL = 60
MIME = {
    '.html': 'text/html; charset=utf-8',
    '.js': 'application/javascript; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.json': 'application/json; charset=utf-8',
    '.svg': 'image/svg+xml',
}
lock = threading.Lock()
# code -> {'created': epoch, 'last_used': epoch}
pairs = {}


def now():
    return time.time()


def new_code():
    alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
    while True:
        code = ''.join(secrets.choice(alphabet) for _ in range(6))
        if code not in pairs:
            return code


def pair_dir(code):
    return DATA / code


def valid_code(code):
    if not code or len(code) != 6 or any(c not in 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789' for c in code):
        return False
    with lock:
        item = pairs.get(code)
        if not item:
            return False
        if now() - item['created'] > PAIR_TTL:
            return False
        item['last_used'] = now()
        return True


def touch_pair(code):
    with lock:
        if code in pairs:
            pairs[code]['last_used'] = now()


def cleanup_loop():
    while True:
        time.sleep(CLEAN_INTERVAL)
        cutoff_file = now() - FILE_TTL
        cutoff_pair = now() - PAIR_TTL
        with lock:
            expired = [c for c, v in pairs.items() if v['created'] < cutoff_pair]
            for c in expired:
                pairs.pop(c, None)
                d = pair_dir(c)
                if d.exists():
                    for p in d.iterdir():
                        try:
                            p.unlink()
                        except Exception:
                            pass
                    try:
                        d.rmdir()
                    except Exception:
                        pass
        for d in DATA.iterdir():
            if not d.is_dir():
                continue
            for p in d.iterdir():
                try:
                    if p.is_file() and p.stat().st_mtime < cutoff_file:
                        p.unlink()
                except Exception:
                    pass

threading.Thread(target=cleanup_loop, daemon=True).start()


class Handler(BaseHTTPRequestHandler):
    server_version = 'AISnapCloud/0.2'

    def cors(self):
        # Mobile web app needs cross-origin API calls only when hosted separately.
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')

    def send_bytes(self, data, status=200, content_type='application/octet-stream', extra=None):
        self.send_response(status)
        self.cors()
        self.send_header('Content-Type', content_type)
        if extra:
            for k, v in extra.items():
                self.send_header(k, v)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, obj, status=200):
        data = json.dumps(obj).encode('utf-8')
        self.send_bytes(data, status, 'application/json; charset=utf-8')

    def q(self):
        return urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)

    def code(self):
        q = self.q()
        code = (q.get('code', [''])[0] or '').strip().upper()
        return code

    def do_OPTIONS(self):
        self.send_response(204)
        self.cors()
        self.end_headers()

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path

        if path == '/health':
            return self.send_json({'ok': True, 'name': 'AI Snap Cloud', 'version': '0.3.0'})

        if path == '/':
            return self.send_json({
                'ok': True,
                'name': 'AI Snap Cloud',
                'version': '0.3.0',
                'mobile': f'{public_base(self)}/mobile/'
            })

        if path == '/api/pair/create':
            with lock:
                code = new_code()
                pairs[code] = {'created': now(), 'last_used': now()}
            (pair_dir(code)).mkdir(exist_ok=True)
            base = public_base(self)
            return self.send_json({
                'ok': True,
                'code': code,
                'expiresIn': PAIR_TTL,
                'mobileUrl': f'{base}/mobile/?code={code}'
            })

        if path == '/api/pair/qr':
            code = self.code()
            if not valid_code(code):
                return self.send_json({'ok': False, 'error': 'invalid_or_expired_pair'}, 401)
            try:
                import qrcode
                img = qrcode.make(f'{public_base(self)}/mobile/?code={code}')
                out = io.BytesIO()
                img.save(out, format='PNG')
                return self.send_bytes(out.getvalue(), 200, 'image/png')
            except Exception:
                return self.send_json({'ok': False, 'error': 'qr_unavailable'}, 500)

        if path == '/api/pair/status':
            code = self.code()
            if not valid_code(code):
                return self.send_json({'ok': False, 'error': 'invalid_or_expired_pair'}, 401)
            return self.send_json({'ok': True, 'code': code, 'connected': True})

        if path == '/mobile/' or path == '/mobile':
            return self.serve_file(MOBILE / 'index.html')

        if path.startswith('/mobile/'):
            rel = path[len('/mobile/'):]
            if rel in ('', '.'):
                rel = 'index.html'
            target = (MOBILE / rel).resolve()
            if not str(target).startswith(str(MOBILE.resolve())) or not target.exists() or not target.is_file():
                return self.send_json({'error': 'not found'}, 404)
            return self.serve_file(target)

        if path == '/api/pending':
            code = self.code()
            if not valid_code(code):
                return self.send_json({'error': 'invalid_or_expired_pair'}, 401)
            d = pair_dir(code)
            files = []
            if d.exists():
                for f in sorted(d.iterdir(), key=lambda p: p.stat().st_mtime):
                    if f.is_file():
                        files.append({'name': f.name, 'size': f.stat().st_size, 'age': round(now() - f.stat().st_mtime, 1)})
            return self.send_json({'files': files})

        if path.startswith('/api/file/'):
            code = self.code()
            if not valid_code(code):
                return self.send_json({'error': 'invalid_or_expired_pair'}, 401)
            name = Path(urllib.parse.unquote(path[len('/api/file/'):])).name
            f = pair_dir(code) / name
            if not f.exists() or not f.is_file():
                return self.send_json({'error': 'not found'}, 404)
            data = f.read_bytes()
            ext = f.suffix.lower()
            ct = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.webp': 'image/webp'}.get(ext, 'application/octet-stream')
            return self.send_bytes(data, 200, ct, {'Content-Disposition': f'inline; filename="{f.name}"'})

        return self.send_json({'error': 'not found'}, 404)

    def serve_file(self, target):
        data = target.read_bytes()
        self.send_bytes(data, 200, MIME.get(target.suffix.lower(), 'application/octet-stream'))

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path

        if path == '/api/upload':
            code = self.code()
            if not valid_code(code):
                return self.send_json({'error': 'invalid_or_expired_pair'}, 401)
            try:
                length = int(self.headers.get('Content-Length', '0'))
            except ValueError:
                length = 0
            if length <= 0:
                return self.send_json({'error': 'empty_upload'}, 400)
            if length > MAX_FILE:
                return self.send_json({'error': 'file_too_large'}, 413)
            ct = self.headers.get('Content-Type', 'image/jpeg').lower()
            if not ct.startswith('image/'):
                return self.send_json({'error': 'image_only'}, 415)
            data = self.rfile.read(length)
            ext = '.jpg' if 'jpeg' in ct else '.png' if 'png' in ct else '.webp' if 'webp' in ct else '.bin'
            name = f'snap_{int(now()*1000)}_{secrets.token_hex(3)}{ext}'
            d = pair_dir(code)
            d.mkdir(exist_ok=True)
            (d / name).write_bytes(data)
            touch_pair(code)
            return self.send_json({'ok': True, 'name': name})

        if path == '/api/ack':
            code = self.code()
            if not valid_code(code):
                return self.send_json({'error': 'invalid_or_expired_pair'}, 401)
            try:
                length = int(self.headers.get('Content-Length', '0'))
                body = json.loads(self.rfile.read(min(length, 100_000)).decode('utf-8'))
                name = Path(str(body.get('name', ''))).name
            except Exception:
                return self.send_json({'error': 'invalid_json'}, 400)
            f = pair_dir(code) / name
            if f.exists() and f.is_file():
                try:
                    f.unlink()
                except Exception:
                    pass
            return self.send_json({'ok': True})

        return self.send_json({'error': 'not found'}, 404)


def public_base(handler):
    # Railway terminates TLS before forwarding to the app. Prefer an explicit
    # public URL when set, otherwise reconstruct the external HTTPS URL from
    # forwarded headers.
    env = os.getenv('PUBLIC_BASE_URL', '').strip().rstrip('/')
    if env:
        return env
    host = handler.headers.get('X-Forwarded-Host') or handler.headers.get('Host', '')
    host = host.split(',')[0].strip()
    proto = handler.headers.get('X-Forwarded-Proto', 'https').split(',')[0].strip()
    if proto not in ('http', 'https'):
        proto = 'https'
    return f'{proto}://{host}'


if __name__ == '__main__':
    port = int(os.getenv('PORT', '8765'))
    print(f'AI Snap Cloud listening on :{port}')
    ThreadingHTTPServer(('0.0.0.0', port), Handler).serve_forever()
