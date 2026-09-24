#!/usr/bin/env python3
import io, json, os, queue, secrets, threading, time, urllib.parse
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
SSE_HEARTBEAT = 15

MIME = {
    '.html': 'text/html; charset=utf-8',
    '.js': 'application/javascript; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.json': 'application/json; charset=utf-8',
    '.svg': 'image/svg+xml',
}

lock = threading.Lock()
sub_lock = threading.Lock()
# code -> {'created': epoch, 'last_used': epoch, 'publicKey': JWK, 'files': {name: metadata}}
pairs = {}
# code -> list[queue.Queue]
subscribers = {}


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


def close_subscribers(code):
    with sub_lock:
        queues = subscribers.pop(code, [])
        for q in queues:
            try:
                q.put_nowait(None)
            except Exception:
                pass


def notify_subscribers(code, event):
    with sub_lock:
        for q in subscribers.get(code, []):
            try:
                q.put_nowait(event)
            except Exception:
                pass


def cleanup_loop():
    while True:
        time.sleep(CLEAN_INTERVAL)
        cutoff_file = now() - FILE_TTL
        cutoff_pair = now() - PAIR_TTL
        with lock:
            expired = [c for c, v in pairs.items() if v['created'] < cutoff_pair]
            for c in expired:
                pairs.pop(c, None)
        for c in expired:
            close_subscribers(c)
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
                        with lock:
                            for item in pairs.values():
                                item.get('files', {}).pop(p.name, None)
                except Exception:
                    pass


threading.Thread(target=cleanup_loop, daemon=True).start()


class Handler(BaseHTTPRequestHandler):
    server_version = 'OramiCloud/1.0.0'

    def cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, X-AI-Snap-IV, X-AI-Snap-AES-Key, X-AI-Snap-Name')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Expose-Headers', 'X-AI-Snap-IV, X-AI-Snap-Key, X-AI-Snap-Mime, X-AI-Snap-Name')
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
        self.send_bytes(json.dumps(obj).encode('utf-8'), status, 'application/json; charset=utf-8')

    def q(self):
        return urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)

    def code(self):
        return (self.q().get('code', [''])[0] or '').strip().upper()

    def do_OPTIONS(self):
        self.send_response(204)
        self.cors()
        self.end_headers()

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path

        if path == '/health':
            return self.send_json({'ok': True, 'name': 'Orami', 'version': '1.0.0', 'e2ee': True, 'instant': True})

        if path == '/':
            return self.serve_file(ROOT / 'index.html')

        if path == '/api/pair/create':
            public_key = None
            # Pair creation is intentionally POST-only for E2EE. A JSON body is
            # required so the server can return the exact PC public key to the phone.
            return self.send_json({'ok': False, 'error': 'use_post_for_secure_pairing'}, 405)

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
            with lock:
                item = pairs.get(code)
                public_key = item.get('publicKey') if item else None
            return self.send_json({'ok': True, 'code': code, 'connected': True, 'e2ee': True, 'publicKey': public_key})

        if path == '/api/events':
            code = self.code()
            if not valid_code(code):
                return self.send_json({'ok': False, 'error': 'invalid_or_expired_pair'}, 401)
            self.send_response(200)
            self.cors()
            self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
            self.send_header('X-Accel-Buffering', 'no')
            self.end_headers()
            q = queue.Queue()
            with sub_lock:
                subscribers.setdefault(code, []).append(q)
            try:
                while True:
                    with lock:
                        if code not in pairs:
                            break
                    try:
                        event = q.get(timeout=SSE_HEARTBEAT)
                        if event is None:
                            break
                        self.wfile.write(f'data: {json.dumps(event, separators=(",", ":"))}\n\n'.encode('utf-8'))
                    except queue.Empty:
                        self.wfile.write(b': ping\n\n')
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                with sub_lock:
                    lst = subscribers.get(code)
                    if lst and q in lst:
                        lst.remove(q)
                    if lst is not None and not lst:
                        subscribers.pop(code, None)
            return

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

        if path == '/api/file-meta':
            code = self.code()
            if not valid_code(code):
                return self.send_json({'ok': False, 'error': 'invalid_or_expired_pair'}, 401)
            name = Path(self.q().get('name', [''])[0] or '').name
            with lock:
                meta = pairs.get(code, {}).get('files', {}).get(name)
            if not meta:
                return self.send_json({'ok': False, 'error': 'metadata_not_found'}, 404)
            return self.send_json({'ok': True, **meta})

        if path.startswith('/api/file/'):
            code = self.code()
            if not valid_code(code):
                return self.send_json({'error': 'invalid_or_expired_pair'}, 401)
            name = Path(urllib.parse.unquote(path[len('/api/file/'):])).name
            f = pair_dir(code) / name
            if not f.exists() or not f.is_file():
                return self.send_json({'error': 'not_found'}, 404)
            with lock:
                meta = dict(pairs.get(code, {}).get('files', {}).get(name, {}))
            data = f.read_bytes()
            ct = meta.get('mime') or 'application/octet-stream'
            extra = {
                'Content-Disposition': f'inline; filename="{name}"',
                'X-AI-Snap-IV': meta.get('iv', ''),
                'X-AI-Snap-Key': meta.get('wrappedKey', ''),
                'X-AI-Snap-Mime': ct,
                'X-AI-Snap-Name': meta.get('originalName', name),
            }
            return self.send_bytes(data, 200, ct, extra)

        return self.send_json({'error': 'not found'}, 404)

    def serve_file(self, target):
        data = target.read_bytes()
        self.send_bytes(data, 200, MIME.get(target.suffix.lower(), 'application/octet-stream'))

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path

        if path == '/api/pair/create':
            try:
                length = int(self.headers.get('Content-Length', '0'))
                body = json.loads(self.rfile.read(min(length, 100_000)).decode('utf-8'))
                public_key = body.get('publicKey')
                if not isinstance(public_key, dict) or public_key.get('kty') != 'RSA' or public_key.get('n') is None or public_key.get('e') is None:
                    raise ValueError
            except Exception:
                return self.send_json({'ok': False, 'error': 'invalid_public_key'}, 400)

            # Creating a new secure pairing revokes every older pairing.
            with lock:
                old_codes = list(pairs.keys())
                code = new_code()
                pairs.clear()
                pairs[code] = {
                    'created': now(),
                    'last_used': now(),
                    'publicKey': public_key,
                    'files': {},
                }
            for old in old_codes:
                close_subscribers(old)
                d = pair_dir(old)
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
            pair_dir(code).mkdir(exist_ok=True)
            base = public_base(self)
            return self.send_json({'ok': True, 'code': code, 'expiresIn': PAIR_TTL, 'e2ee': True, 'mobileUrl': f'{base}/mobile/?code={code}'})

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
            ct = self.headers.get('Content-Type', 'image/jpeg').lower().split(';', 1)[0].strip()
            if not ct.startswith('image/'):
                return self.send_json({'error': 'image_only'}, 415)
            iv = self.headers.get('X-AI-Snap-IV', '').strip()
            wrapped_key = self.headers.get('X-AI-Snap-AES-Key', '').strip()
            original_name = urllib.parse.unquote(self.headers.get('X-AI-Snap-Name', 'ai-snap.jpg')).strip() or 'ai-snap.jpg'
            if not iv or not wrapped_key:
                return self.send_json({'error': 'missing_encryption_metadata'}, 400)
            data = self.rfile.read(length)
            ext = '.jpg' if ct == 'image/jpeg' else '.png' if ct == 'image/png' else '.webp' if ct == 'image/webp' else '.bin'
            name = f'snap_{int(now()*1000)}_{secrets.token_hex(3)}{ext}'
            d = pair_dir(code)
            d.mkdir(exist_ok=True)
            (d / name).write_bytes(data)
            meta = {'name': name, 'iv': iv, 'wrappedKey': wrapped_key, 'mime': ct, 'originalName': original_name}
            with lock:
                item = pairs.get(code)
                if not item:
                    return self.send_json({'error': 'invalid_or_expired_pair'}, 401)
                item.setdefault('files', {})[name] = meta
                item['last_used'] = now()
            notify_subscribers(code, meta)
            return self.send_json({'ok': True, 'name': name, 'e2ee': True})

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
            with lock:
                pairs.get(code, {}).get('files', {}).pop(name, None)
            return self.send_json({'ok': True})

        return self.send_json({'error': 'not found'}, 404)


def public_base(handler):
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
    print(f'Orami listening on :{port}')
    ThreadingHTTPServer(('0.0.0.0', port), Handler).serve_forever()
