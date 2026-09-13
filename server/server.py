#!/usr/bin/env python3
import base64, io, json, os, secrets, threading, time, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MOBILE = ROOT / 'mobile'
DATA = ROOT / 'data'
DATA.mkdir(exist_ok=True)
MAX_FILE = 25 * 1024 * 1024
PAIR_TTL = 24 * 60 * 60
FILE_TTL = 10 * 60
CLEAN_INTERVAL = 60
MIME = {'.html':'text/html; charset=utf-8','.js':'application/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.json':'application/json; charset=utf-8'}
lock = threading.RLock()
pairs = {}

def now(): return time.time()
def b64url(data): return base64.urlsafe_b64encode(data).rstrip(b'=').decode()
def new_code():
    alphabet='ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
    while True:
        code=''.join(secrets.choice(alphabet) for _ in range(6))
        if code not in pairs:return code

def pair_dir(code): return DATA / code

def valid_code(code):
    if not code or len(code)!=6 or any(c not in 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789' for c in code): return False
    with lock:
        item=pairs.get(code)
        if not item or now()-item['created']>PAIR_TTL:return False
        item['last_used']=now();return True

def cleanup_loop():
    while True:
        time.sleep(CLEAN_INTERVAL)
        cutoff_file=now()-FILE_TTL; cutoff_pair=now()-PAIR_TTL
        with lock:
            expired=[c for c,v in pairs.items() if v['created']<cutoff_pair]
            for c in expired:
                item=pairs.pop(c,None)
                if item:
                    for q in list(item['subscribers']):
                        try:q.put_nowait(None)
                        except Exception:pass
                d=pair_dir(c)
                if d.exists():
                    for p in d.iterdir():
                        try:p.unlink()
                        except Exception:pass
                    try:d.rmdir()
                    except Exception:pass
        for d in DATA.iterdir():
            if not d.is_dir():continue
            for p in d.iterdir():
                try:
                    if p.is_file() and p.stat().st_mtime<cutoff_file:p.unlink()
                except Exception:pass
threading.Thread(target=cleanup_loop,daemon=True).start()

class Handler(BaseHTTPRequestHandler):
    server_version='AISnapCloud/0.4.3'
    def log_message(self,fmt,*args): return
    def cors(self):
        self.send_header('Access-Control-Allow-Origin','*')
        self.send_header('Access-Control-Allow-Headers','Content-Type, X-AI-Snap-IV, X-AI-Snap-AES-Key, X-AI-Snap-Name')
        self.send_header('Access-Control-Expose-Headers','X-AI-Snap-IV, X-AI-Snap-Key, X-AI-Snap-Mime, X-AI-Snap-Name')
        self.send_header('Access-Control-Allow-Methods','GET, POST, OPTIONS')
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer')
    def send_bytes(self,data,status=200,content_type='application/octet-stream',extra=None):
        self.send_response(status);self.cors();self.send_header('Content-Type',content_type)
        if extra:
            for k,v in extra.items():self.send_header(k,v)
        self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    def send_json(self,obj,status=200):self.send_bytes(json.dumps(obj,separators=(',',':')).encode(),status,'application/json; charset=utf-8')
    def q(self):return urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
    def code(self):return (self.q().get('code',[''])[0] or '').strip().upper()
    def do_OPTIONS(self):self.send_response(204);self.cors();self.end_headers()
    def file_meta(self,code,name):
        with lock:
            item=pairs.get(code); meta=item.get('files',{}).get(name,{}) if item else {}
        return meta

    def do_GET(self):
        path=urllib.parse.urlparse(self.path).path
        if path=='/health':return self.send_json({'ok':True,'name':'AI Snap Cloud','version':'0.4.3','e2ee':True,'instant':True})
        if path=='/':return self.send_json({'ok':True,'name':'AI Snap Cloud','version':'0.4.3','e2ee':True,'mobile':f'{public_base(self)}/mobile/'})
        if path=='/api/pair/status':
            code=self.code()
            if not valid_code(code):return self.send_json({'ok':False,'error':'invalid_or_expired_pair'},401)
            item=pairs[code]
            return self.send_json({'ok':True,'code':code,'connected':True,'e2ee':True,'publicKey':item['public_key'],'expiresIn':max(0,int(PAIR_TTL-(now()-item['created'])))})
        if path=='/api/pair/qr':
            code=self.code()
            if not valid_code(code):return self.send_json({'ok':False,'error':'invalid_or_expired_pair'},401)
            try:
                import qrcode
                img=qrcode.make(f'{public_base(self)}/mobile/?code={code}');out=io.BytesIO();img.save(out,format='PNG');return self.send_bytes(out.getvalue(),200,'image/png')
            except Exception:return self.send_json({'ok':False,'error':'qr_unavailable'},500)
        if path=='/mobile/' or path=='/mobile':return self.serve_file(MOBILE/'index.html')
        if path.startswith('/mobile/'):
            rel=path[len('/mobile/'): ] or 'index.html';target=(MOBILE/rel).resolve()
            if not str(target).startswith(str(MOBILE.resolve())) or not target.exists() or not target.is_file():return self.send_json({'error':'not found'},404)
            return self.serve_file(target)
        if path in ('/api/pending','/api/events'):
            if path=='/api/events':return self.events(self.code())
            code=self.code()
            if not valid_code(code):return self.send_json({'error':'invalid_or_expired_pair'},401)
            d=pair_dir(code);files=[]
            if d.exists():
                for f in sorted(d.iterdir(),key=lambda p:p.stat().st_mtime):
                    if f.is_file():files.append({'name':f.name,'size':f.stat().st_size,'age':round(now()-f.stat().st_mtime,1)})
            return self.send_json({'files':files})
        if path=='/api/file-meta':
            code=self.code()
            if not valid_code(code):return self.send_json({'error':'invalid_or_expired_pair'},401)
            name=Path(urllib.parse.unquote(self.q().get('name',[''])[0])).name
            f=pair_dir(code)/name
            if not f.exists() or not f.is_file():return self.send_json({'error':'not_found'},404)
            meta=self.file_meta(code,name)
            if not meta:return self.send_json({'error':'metadata_not_found'},404)
            return self.send_json({'ok':True,'name':name,'iv':meta.get('iv',''),'wrappedKey':meta.get('wrapped_key',''),'mime':meta.get('mime','image/jpeg'),'originalName':meta.get('name',name)})
        if path.startswith('/api/file/'):
            code=self.code()
            if not valid_code(code):return self.send_json({'error':'invalid_or_expired_pair'},401)
            name=Path(urllib.parse.unquote(path[len('/api/file/'):])).name;f=pair_dir(code)/name
            if not f.exists() or not f.is_file():return self.send_json({'error':'not_found'},404)
            data=f.read_bytes(); ext=f.suffix.lower();ct={'.jpg':'image/jpeg','.jpeg':'image/jpeg','.png':'image/png','.webp':'image/webp'}.get(ext,'application/octet-stream')
            meta=self.file_meta(code,name)
            return self.send_bytes(data,200,ct,{'Content-Disposition':f'inline; filename="{meta.get("name",f.name)}"','X-AI-Snap-IV':meta.get('iv',''),'X-AI-Snap-Key':meta.get('wrapped_key',''),'X-AI-Snap-Mime':meta.get('mime',ct),'X-AI-Snap-Name':meta.get('name',f.name)})
        return self.send_json({'error':'not found'},404)

    def events(self,code):
        if not valid_code(code):return self.send_json({'error':'invalid_or_expired_pair'},401)
        import queue
        q=queue.Queue(maxsize=20)
        with lock:
            item=pairs.get(code)
            if not item:return self.send_json({'error':'invalid_or_expired_pair'},401)
            item['subscribers'].add(q)
        try:
            self.send_response(200);self.send_header('Content-Type','text/event-stream; charset=utf-8');self.send_header('Cache-Control','no-cache, no-store');self.send_header('Connection','keep-alive');self.send_header('Access-Control-Allow-Origin','*');self.end_headers();self.wfile.write(b': connected\n\n');self.wfile.flush()
            while True:
                try:event=q.get(timeout=20)
                except queue.Empty:
                    self.wfile.write(b': ping\n\n');self.wfile.flush();continue
                if event is None:break
                payload=json.dumps(event,separators=(',',':')).encode();self.wfile.write(b'data: '+payload+b'\n\n');self.wfile.flush()
        except (BrokenPipeError,ConnectionResetError):pass
        finally:
            with lock:
                item=pairs.get(code)
                if item:item['subscribers'].discard(q)

    def serve_file(self,target):self.send_bytes(target.read_bytes(),200,MIME.get(target.suffix.lower(),'application/octet-stream'))

    def do_POST(self):
        path=urllib.parse.urlparse(self.path).path
        if path=='/api/pair/create':
            try:
                length=int(self.headers.get('Content-Length','0'));body=json.loads(self.rfile.read(min(length,100000)).decode());pub=body.get('publicKey')
                if not isinstance(pub,dict) or pub.get('kty')!='RSA':raise ValueError()
            except Exception:return self.send_json({'ok':False,'error':'invalid_public_key'},400)
            with lock:
                code=new_code();pairs[code]={'created':now(),'last_used':now(),'public_key':pub,'files':{},'subscribers':set()}
            pair_dir(code).mkdir(exist_ok=True)
            return self.send_json({'ok':True,'code':code,'expiresIn':PAIR_TTL,'e2ee':True,'mobileUrl':f'{public_base(self)}/mobile/?code={code}'})
        if path=='/api/upload':return self.upload()
        if path=='/api/ack':return self.ack()
        return self.send_json({'error':'not found'},404)

    def upload(self):
        code=self.code()
        if not valid_code(code):return self.send_json({'error':'invalid_or_expired_pair'},401)
        try:length=int(self.headers.get('Content-Length','0'))
        except ValueError:length=0
        if length<=0:return self.send_json({'error':'empty_upload'},400)
        if length>MAX_FILE:return self.send_json({'error':'file_too_large'},413)
        ct=self.headers.get('Content-Type','image/jpeg').split(';')[0].lower()
        if not ct.startswith('image/'):return self.send_json({'error':'image_only'},415)
        data=self.rfile.read(length)
        client_iv=self.headers.get('X-AI-Snap-IV');client_key=self.headers.get('X-AI-Snap-AES-Key');orig=self.headers.get('X-AI-Snap-Name','ai-snap.jpg')
        if not client_iv or not client_key:return self.send_json({'error':'missing_encryption_metadata'},400)
        orig=Path(urllib.parse.unquote(orig)).name or 'ai-snap.jpg'
        ext='.jpg' if 'jpeg' in ct else '.png' if 'png' in ct else '.webp' if 'webp' in ct else '.bin'
        name=f'snap_{int(now()*1000)}_{secrets.token_hex(3)}{ext}';d=pair_dir(code);d.mkdir(exist_ok=True);(d/name).write_bytes(data)
        meta={'name':orig,'mime':ct,'iv':client_iv,'wrapped_key':client_key}
        with lock:
            pairs[code]['files'][name]=meta;pairs[code]['last_used']=now();subs=list(pairs[code]['subscribers'])
        event={'name':name,'iv':client_iv,'wrappedKey':client_key,'mime':ct,'originalName':orig}
        for q in subs:
            try:q.put_nowait(event)
            except Exception:pass
        return self.send_json({'ok':True,'name':name,'instant':True})

    def ack(self):
        code=self.code()
        if not valid_code(code):return self.send_json({'error':'invalid_or_expired_pair'},401)
        try:
            length=int(self.headers.get('Content-Length','0'));body=json.loads(self.rfile.read(min(length,100000)).decode());name=Path(str(body.get('name',''))).name
        except Exception:return self.send_json({'error':'invalid_json'},400)
        f=pair_dir(code)/name
        if f.exists() and f.is_file():
            try:f.unlink()
            except Exception:pass
        with lock:
            item=pairs.get(code)
            if item:item['files'].pop(name,None)
        return self.send_json({'ok':True})

def public_base(handler):
    env=os.getenv('PUBLIC_BASE_URL','').strip().rstrip('/')
    if env:return env
    host=(handler.headers.get('X-Forwarded-Host') or handler.headers.get('Host','')).split(',')[0].strip();proto=(handler.headers.get('X-Forwarded-Proto','https').split(',')[0].strip())
    return f'{proto if proto in ("http","https") else "https"}://{host}'

if __name__=='__main__':
    port=int(os.getenv('PORT','8765'));print(f'AI Snap Cloud v0.4.3 listening on :{port}');ThreadingHTTPServer(('0.0.0.0',port),Handler).serve_forever()
