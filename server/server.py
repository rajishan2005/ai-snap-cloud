#!/usr/bin/env python3
import io, json, os, secrets, threading, time, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent; MOBILE=ROOT/'mobile'; DATA=ROOT/'data'; DATA.mkdir(exist_ok=True)
MAX_FILE=25*1024*1024; PAIR_TTL=30*60; FILE_TTL=10*60; CLEAN_INTERVAL=60
MIME={'.html':'text/html; charset=utf-8','.js':'application/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.json':'application/json; charset=utf-8','.svg':'image/svg+xml'}
lock=threading.Lock(); pairs={}; subscribers={}
def now(): return time.time()
def new_code():
    alphabet='ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
    while True:
        code=''.join(secrets.choice(alphabet) for _ in range(6))
        if code not in pairs:return code
def pair_dir(code): return DATA/code
def valid_code(code):
    if not code or len(code)!=6 or any(c not in 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789' for c in code):return False
    with lock:
        item=pairs.get(code)
        if not item or now()-item['created']>PAIR_TTL:return False
        item['last_used']=now(); return True
def touch_pair(code):
    with lock:
        if code in pairs:pairs[code]['last_used']=now()
def notify(code,name):
    payload=f'data: {json.dumps({"name":name})}\n\n'.encode()
    with lock:targets=list(subscribers.get(code,[]))
    dead=[]
    for w in targets:
        try:w.write(payload);w.flush()
        except Exception:dead.append(w)
    if dead:
        with lock:subscribers[code]=[x for x in subscribers.get(code,[]) if x not in dead]
def cleanup_loop():
    while True:
        time.sleep(CLEAN_INTERVAL); cf,cp=now()-FILE_TTL,now()-PAIR_TTL
        with lock:
            expired=[c for c,v in pairs.items() if v['created']<cp]
            for c in expired:
                pairs.pop(c,None);subscribers.pop(c,None);d=pair_dir(c)
                if d.exists():
                    for p in d.iterdir():
                        try:p.unlink()
                        except Exception:pass
                    try:d.rmdir()
                    except Exception:pass
        if DATA.exists():
            for d in DATA.iterdir():
                if d.is_dir():
                    for p in d.iterdir():
                        try:
                            if p.is_file() and p.stat().st_mtime<cf:p.unlink()
                        except Exception:pass
threading.Thread(target=cleanup_loop,daemon=True).start()

class Handler(BaseHTTPRequestHandler):
    server_version='AISnapCloud/0.4'
    def cors(self):
        self.send_header('Access-Control-Allow-Origin','*');self.send_header('Access-Control-Allow-Headers','Content-Type, X-AI-Snap-Key, X-AI-Snap-IV, X-AI-Snap-Mime, X-AI-Snap-Name');self.send_header('Access-Control-Allow-Methods','GET, POST, OPTIONS');self.send_header('Access-Control-Expose-Headers','X-AI-Snap-IV, X-AI-Snap-Key, X-AI-Snap-Mime, X-AI-Snap-Name');self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('Referrer-Policy','no-referrer')
    def send_bytes(self,data,status=200,content_type='application/octet-stream',extra=None):
        self.send_response(status);self.cors();self.send_header('Content-Type',content_type)
        if extra:
            for k,v in extra.items():self.send_header(k,v)
        self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    def send_json(self,obj,status=200):self.send_bytes(json.dumps(obj).encode(),status,'application/json; charset=utf-8')
    def q(self):return urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
    def code(self):return (self.q().get('code',[''])[0] or '').strip().upper()
    def do_OPTIONS(self):self.send_response(204);self.cors();self.end_headers()
    def do_GET(self):
        path=urllib.parse.urlparse(self.path).path
        if path=='/health':return self.send_json({'ok':True,'name':'AI Snap Cloud','version':'0.4.0','e2ee':True})
        if path=='/':return self.send_json({'ok':True,'name':'AI Snap Cloud','version':'0.4.0','e2ee':True,'mobile':f'{public_base(self)}/mobile/'})
        if path=='/api/pair/create':
            with lock:code=new_code();pairs[code]={'created':now(),'last_used':now(),'public_key':None}
            pair_dir(code).mkdir(exist_ok=True);base=public_base(self);return self.send_json({'ok':True,'code':code,'expiresIn':PAIR_TTL,'mobileUrl':f'{base}/mobile/?code={code}'})
        if path=='/api/pair/qr':
            code=self.code()
            if not valid_code(code):return self.send_json({'ok':False,'error':'invalid_or_expired_pair'},401)
            try:
                import qrcode;img=qrcode.make(f'{public_base(self)}/mobile/?code={code}');out=io.BytesIO();img.save(out,format='PNG');return self.send_bytes(out.getvalue(),200,'image/png')
            except Exception:return self.send_json({'ok':False,'error':'qr_unavailable'},500)
        if path=='/api/pair/status':
            code=self.code()
            if not valid_code(code):return self.send_json({'ok':False,'error':'invalid_or_expired_pair'},401)
            with lock:has_key=bool(pairs[code].get('public_key'))
            return self.send_json({'ok':True,'code':code,'connected':True,'e2ee':has_key})
        if path=='/api/pair/key':
            code=self.code()
            if not valid_code(code):return self.send_json({'ok':False,'error':'invalid_or_expired_pair'},401)
            with lock:key=pairs[code].get('public_key')
            if not key:return self.send_json({'ok':False,'error':'pair_not_ready'},409)
            return self.send_json({'ok':True,'publicKey':key})
        if path=='/api/events':
            code=self.code()
            if not valid_code(code):return self.send_json({'ok':False,'error':'invalid_or_expired_pair'},401)
            self.send_response(200);self.cors();self.send_header('Content-Type','text/event-stream; charset=utf-8');self.send_header('Connection','keep-alive');self.send_header('X-Accel-Buffering','no');self.end_headers()
            try:
                self.wfile.write(b'retry: 3000\n\n');self.wfile.flush()
                with lock:subscribers.setdefault(code,[]).append(self.wfile)
                while valid_code(code):
                    time.sleep(15);self.wfile.write(b': keepalive\n\n');self.wfile.flush()
            except Exception:pass
            finally:
                with lock:subscribers[code]=[x for x in subscribers.get(code,[]) if x is not self.wfile]
            return
        if path=='/mobile/' or path=='/mobile':return self.serve_file(MOBILE/'index.html')
        if path.startswith('/mobile/'):
            rel=path[len('/mobile/'):]
            if rel in ('','.') :rel='index.html'
            target=(MOBILE/rel).resolve()
            if not str(target).startswith(str(MOBILE.resolve())) or not target.exists() or not target.is_file():return self.send_json({'error':'not found'},404)
            return self.serve_file(target)
        if path=='/api/pending':
            code=self.code()
            if not valid_code(code):return self.send_json({'error':'invalid_or_expired_pair'},401)
            d=pair_dir(code);files=[]
            if d.exists():
                for f in sorted(d.glob('*.enc'),key=lambda p:p.stat().st_mtime):
                    if f.is_file():files.append({'name':f.name,'size':f.stat().st_size,'age':round(now()-f.stat().st_mtime,1)})
            return self.send_json({'files':files})
        if path.startswith('/api/file/'):
            code=self.code()
            if not valid_code(code):return self.send_json({'error':'invalid_or_expired_pair'},401)
            name=Path(urllib.parse.unquote(path[len('/api/file/'):])).name;f=pair_dir(code)/name;meta=f.with_suffix('.json')
            if not f.exists() or not f.is_file() or not meta.exists():return self.send_json({'error':'not found'},404)
            try:info=json.loads(meta.read_text())
            except Exception:return self.send_json({'error':'invalid_metadata'},500)
            return self.send_bytes(f.read_bytes(),200,'application/octet-stream',{'X-AI-Snap-IV':info['iv'],'X-AI-Snap-Key':info['key'],'X-AI-Snap-Mime':info['mime'],'X-AI-Snap-Name':info['name']})
        return self.send_json({'error':'not found'},404)
    def serve_file(self,target):self.send_bytes(target.read_bytes(),200,MIME.get(target.suffix.lower(),'application/octet-stream'))
    def do_POST(self):
        path=urllib.parse.urlparse(self.path).path
        if path=='/api/pair/create':
            try:
                length=int(self.headers.get('Content-Length','0'));body=json.loads(self.rfile.read(min(length,100_000)).decode());public_key=body.get('publicKey')
                if not isinstance(public_key,dict) or public_key.get('kty')!='RSA':return self.send_json({'error':'invalid_public_key'},400)
            except Exception:return self.send_json({'error':'invalid_json'},400)
            with lock:code=new_code();pairs[code]={'created':now(),'last_used':now(),'public_key':public_key}
            pair_dir(code).mkdir(exist_ok=True);base=public_base(self);return self.send_json({'ok':True,'code':code,'expiresIn':PAIR_TTL,'mobileUrl':f'{base}/mobile/?code={code}','e2ee':True})
        if path=='/api/upload':
            code=self.code()
            if not valid_code(code):return self.send_json({'error':'invalid_or_expired_pair'},401)
            try:length=int(self.headers.get('Content-Length','0'))
            except ValueError:length=0
            if length<=0:return self.send_json({'error':'empty_upload'},400)
            if length>MAX_FILE+1024:return self.send_json({'error':'file_too_large'},413)
            if not self.headers.get('X-AI-Snap-Key') or not self.headers.get('X-AI-Snap-IV'):return self.send_json({'error':'encryption_required'},400)
            data=self.rfile.read(length)
            if len(data)!=length:return self.send_json({'error':'incomplete_upload'},400)
            name_header=self.headers.get('X-AI-Snap-Name','photo.jpg');safe_name=Path(urllib.parse.unquote(name_header)).name[:180] or 'photo.jpg';mime=self.headers.get('X-AI-Snap-Mime','image/jpeg')
            if not mime.startswith('image/'):return self.send_json({'error':'image_only'},415)
            name=f'snap_{int(now()*1000)}_{secrets.token_hex(3)}.enc';d=pair_dir(code);d.mkdir(exist_ok=True);(d/name).write_bytes(data)
            (d/Path(name).with_suffix('.json')).write_text(json.dumps({'name':safe_name,'mime':mime,'iv':self.headers['X-AI-Snap-IV'],'key':self.headers['X-AI-Snap-Key']}))
            touch_pair(code);notify(code,name);return self.send_json({'ok':True,'name':name,'encrypted':True})
        if path=='/api/pair/register':
            code=self.code()
            if not valid_code(code):return self.send_json({'error':'invalid_or_expired_pair'},401)
            try:
                length=int(self.headers.get('Content-Length','0'));body=json.loads(self.rfile.read(min(length,100_000)).decode());public_key=body.get('publicKey')
            except Exception:return self.send_json({'error':'invalid_json'},400)
            if not isinstance(public_key,dict) or public_key.get('kty')!='RSA':return self.send_json({'error':'invalid_public_key'},400)
            with lock:pairs[code]['public_key']=public_key
            return self.send_json({'ok':True,'e2ee':True})
        if path=='/api/ack':
            code=self.code()
            if not valid_code(code):return self.send_json({'error':'invalid_or_expired_pair'},401)
            try:
                length=int(self.headers.get('Content-Length','0'));body=json.loads(self.rfile.read(min(length,100_000)).decode());name=Path(str(body.get('name',''))).name
            except Exception:return self.send_json({'error':'invalid_json'},400)
            f=pair_dir(code)/name;meta=f.with_suffix('.json')
            for target in (f,meta):
                if target.exists() and target.is_file():
                    try:target.unlink()
                    except Exception:pass
            return self.send_json({'ok':True})
        return self.send_json({'error':'not found'},404)

def public_base(handler):
    env=os.getenv('PUBLIC_BASE_URL','').strip().rstrip('/')
    if env:return env
    host=handler.headers.get('Host','');forwarded=handler.headers.get('X-Forwarded-Proto','');scheme=forwarded.split(',')[0].strip() if forwarded else ('https' if os.getenv('RAILWAY_PUBLIC_DOMAIN') else 'http');return f'{scheme}://{host}'
if __name__=='__main__':
    port=int(os.getenv('PORT','8765'));print(f'AI Snap Cloud listening on :{port}');ThreadingHTTPServer(('0.0.0.0',port),Handler).serve_forever()
