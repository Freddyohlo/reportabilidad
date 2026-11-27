#!/usr/bin/env python3
"""Generador de reportes de turno (STG Chile / CCU).

Servidor sin dependencias externas:
  /            bandeja para subir fotos
  /editor      formulario con vista previa en vivo
  /historial   reportes guardados
  /reporte     reporte (acepta ?id=<reporte>)
  /reporte.pdf PDF A4 generado con chromium headless

Los datos de cada reporte quedan en ./reportes/<id>.json, de modo que se pueden
versionar en git y regenerar el PDF cuando haga falta.
"""

import html
import json
import mimetypes
import os
import re
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

BASE = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE, "uploads")
REPORT_DIR = os.path.join(BASE, "reportes")
PUERTO_BASE = int(os.environ.get("PORT") or 12000)
MAX_BYTES = 25 * 1024 * 1024
ID_OK = re.compile(r"^[a-z0-9][a-z0-9-]{0,60}$")

# Chrome o Edge sirven igual para imprimir el PDF; en Windows Edge siempre esta.
CANDIDATOS_NAVEGADOR = [
    os.environ.get("CHROME_PATH", ""),
    "/usr/bin/chromium", "/usr/bin/chromium-browser", "/usr/bin/google-chrome",
    "/usr/bin/microsoft-edge", "/snap/bin/chromium",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


def buscar_navegador():
    """Devuelve la ruta de Chrome/Edge, o None si no hay."""
    for ruta in CANDIDATOS_NAVEGADOR:
        if ruta and os.path.isfile(ruta):
            return ruta
    if os.name == "nt":
        for raiz in (os.environ.get("LOCALAPPDATA", ""), os.environ.get("PROGRAMFILES", ""),
                     os.environ.get("PROGRAMFILES(X86)", "")):
            for sub in (r"Google\Chrome\Application\chrome.exe",
                        r"Microsoft\Edge\Application\msedge.exe"):
                ruta = os.path.join(raiz, sub) if raiz else ""
                if ruta and os.path.isfile(ruta):
                    return ruta
    return None


NAVEGADOR = buscar_navegador()
PUERTO_ACTUAL = PUERTO_BASE


def puerto_libre(inicial: int, intentos: int = 20) -> int:
    for p in range(inicial, inicial + intentos):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if s.connect_ex(("127.0.0.1", p)) != 0:
                return p
    return inicial

STATIC = {
    "/reporte": "reporte.html",
    "/reporte.html": "reporte.html",
    "/editor": "editor.html",
    "/editor.html": "editor.html",
}

INDEX = """<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Reportes de turno</title>
<style>
 :root{--ccu-dark:#013c06;--muted:#67735e;--line:#dbe0d2}
 *{box-sizing:border-box}
 body{font:16px/1.5 system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;margin:0;padding:24px;
      background:#eaede2;color:#13200f}
 main{max-width:760px;margin:0 auto}
 h1{font-size:20px;margin:0 0 4px;color:var(--ccu-dark)}
 p.hint{margin:0 0 20px;color:var(--muted);font-size:14px}
 .nav{display:flex;gap:10px;margin:0 0 22px;flex-wrap:wrap}
 .nav a{font-size:13px;font-weight:600;text-decoration:none;color:var(--ccu-dark);background:#fff;
        border:1px solid var(--line);border-radius:9px;padding:8px 14px}
 .nav a:hover{background:#f6f8ef}
 #drop{border:2px dashed #b9c4a6;border-radius:14px;padding:40px 20px;text-align:center;
       background:#fff;cursor:pointer;transition:.15s}
 #drop.over{border-color:#97c000;background:#f6fae8}
 #drop strong{display:block;font-size:16px;margin-bottom:6px}
 .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:12px;margin-top:24px}
 figure{margin:0;background:#fff;border:1px solid var(--line);border-radius:10px;overflow:hidden}
 figure img{width:100%;height:130px;object-fit:cover;display:block}
 figcaption{font-size:11px;padding:6px 8px;color:var(--muted);word-break:break-all}
 #status{font-size:14px;margin-top:12px;min-height:20px}
 .ok{color:#1f6a0b}.err{color:#b42318}
</style></head><body><main>
<h1>Reportes de turno</h1>
<p class="hint">Sube las capturas del turno o entra al generador para armar el reporte.</p>
<div class="nav">
  <a href="/editor">Generador de reporte &rarr;</a>
  <a href="/historial">Historial</a>
  <a href="/reporte">Ver reporte</a>
  <a href="/descargar">Descargar proyecto (.zip)</a>
</div>
<div id="drop"><strong>Suelta las fotos aquí</strong><span>o haz clic para seleccionarlas</span>
  <input id="file" type="file" accept="image/*" multiple hidden>
</div>
<div id="status"></div>
<div class="grid" id="grid"></div>
<script>
const drop=document.getElementById('drop'),input=document.getElementById('file'),
      grid=document.getElementById('grid'),status=document.getElementById('status');
drop.onclick=()=>input.click();
input.onchange=()=>send([...input.files]);
['dragenter','dragover'].forEach(e=>drop.addEventListener(e,ev=>{ev.preventDefault();drop.classList.add('over')}));
['dragleave','drop'].forEach(e=>drop.addEventListener(e,ev=>{ev.preventDefault();drop.classList.remove('over')}));
drop.addEventListener('drop',ev=>send([...ev.dataTransfer.files].filter(f=>f.type.startsWith('image/'))));
async function send(files){
  if(!files.length)return;
  let ok=0,bad=[];
  for(const f of files){
    status.className='';status.textContent=`Subiendo ${f.name}...`;
    try{
      const r=await fetch('/upload?name='+encodeURIComponent(f.name),{method:'POST',body:f});
      if(r.ok)ok++;else bad.push(f.name+' ('+r.status+')');
    }catch(e){bad.push(f.name);}
  }
  status.className=bad.length?'err':'ok';
  status.textContent=bad.length?`Subidas ${ok}. Fallaron: ${bad.join(', ')}`:`Listo, ${ok} foto(s) subida(s).`;
  load();
}
async function load(){
  const items=await(await fetch('/list')).json();
  grid.innerHTML=items.map(i=>`<figure><a href="/uploads/${encodeURIComponent(i.name)}" target="_blank">
    <img src="/uploads/${encodeURIComponent(i.name)}" alt=""></a>
    <figcaption>${i.name}<br>${i.size_kb} KB</figcaption></figure>`).join('');
}
load();
</script></main></body></html>
"""


def report_id(data: dict) -> str:
    fecha = (data.get("fechaCorte") or time.strftime("%Y-%m-%d")).strip()
    turno = re.sub(r"\D", "", str(data.get("titulo", ""))) or "c"
    return f"{fecha}-turno-{turno.lower()}"


def cargar_reportes():
    if not os.path.isdir(REPORT_DIR):
        return []
    salida = []
    for nombre in sorted(os.listdir(REPORT_DIR), reverse=True):
        if not nombre.endswith(".json"):
            continue
        ruta = os.path.join(REPORT_DIR, nombre)
        try:
            with open(ruta, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        salida.append({
            "id": nombre[:-5],
            "titulo": data.get("titulo", ""),
            "fecha": data.get("fecha", ""),
            "responsable": data.get("responsable", ""),
            "pendientes": len(data.get("noDevueltos") or []),
            "equipos": data.get("equiposAsignados", ""),
            "mtime": os.path.getmtime(ruta),
        })
    return salida


def historial_html():
    filas = []
    for r in cargar_reportes():
        fecha = time.strftime("%d/%m/%Y %H:%M", time.localtime(r["mtime"]))
        filas.append(f"""<tr>
          <td><strong>{html.escape(r['titulo'] or r['id'])}</strong><div class="sub">{html.escape(r['fecha'])}</div></td>
          <td>{html.escape(str(r['responsable']))}</td>
          <td class="num">{r['pendientes']}</td>
          <td class="sub">{fecha}</td>
          <td class="acc">
            <a href="/reporte?id={r['id']}">Ver</a>
            <a href="/reporte.pdf?id={r['id']}">PDF</a>
            <a href="/editor?id={r['id']}">Editar</a>
          </td>
        </tr>""")
    cuerpo = "\n".join(filas) or ('<tr><td colspan="5" class="sub" '
                                  'style="padding:24px;text-align:center">'
                                  'Todavía no hay reportes guardados.</td></tr>')
    return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Historial de reportes</title>
<style>
 :root{{--ccu-dark:#013c06;--line:#dbe0d2;--muted:#67735e}}
 *{{box-sizing:border-box}}
 body{{font:15px/1.5 system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;margin:0;padding:28px 20px;
      background:#eaede2;color:#13200f}}
 main{{max-width:900px;margin:0 auto;background:#fff;border:1px solid var(--line);border-radius:16px;padding:24px}}
 h1{{font-size:19px;margin:0 0 18px;color:var(--ccu-dark)}}
 .nav{{margin:0 0 18px}} .nav a{{font-size:13px;font-weight:600;color:var(--ccu-dark);text-decoration:none}}
 table{{width:100%;border-collapse:collapse;font-size:13.5px}}
 th{{text-align:left;font-size:10px;letter-spacing:.07em;text-transform:uppercase;color:var(--muted);
     padding:0 10px 8px;border-bottom:1px solid var(--line)}}
 td{{padding:12px 10px;border-bottom:1px solid #ecefe5;vertical-align:top}}
 tr:last-child td{{border-bottom:0}}
 .sub{{font-size:11.5px;color:var(--muted)}}
 .num{{text-align:right;font-variant-numeric:tabular-nums;font-weight:600}}
 .acc{{text-align:right;white-space:nowrap}}
 .acc a{{font-size:12px;font-weight:600;color:var(--ccu-dark);text-decoration:none;margin-left:10px}}
 .acc a:hover{{text-decoration:underline}}
</style></head><body><main>
<h1>Historial de reportes</h1>
<div class="nav"><a href="/editor">&larr; Nuevo reporte</a></div>
<table>
  <thead><tr><th>Reporte</th><th>Responsable</th><th style="text-align:right">Pendientes</th>
  <th>Guardado</th><th></th></tr></thead>
  <tbody>{cuerpo}</tbody>
</table>
</main></body></html>"""


def generar_pdf(rid: str) -> str:
    """Genera (o reutiliza) el PDF A4 de un reporte guardado."""
    origen = os.path.join(REPORT_DIR, f"{rid}.json")
    destino = os.path.join(REPORT_DIR, f"{rid}.pdf")
    if not os.path.isfile(origen):
        raise FileNotFoundError(rid)
    if os.path.isfile(destino) and os.path.getmtime(destino) > os.path.getmtime(origen):
        return destino
    if not NAVEGADOR:
        raise RuntimeError("no encontre Chrome ni Edge para generar el PDF")
    tmp = destino + ".tmp"
    orden = [NAVEGADOR, "--headless", "--disable-gpu", "--no-pdf-header-footer",
             f"--print-to-pdf={tmp}", "--virtual-time-budget=5000",
             f"http://127.0.0.1:{PUERTO_ACTUAL}/reporte?id={rid}"]
    # en contenedores el sandbox de Chromium suele fallar; se reintenta sin el
    for extra in ([], ["--no-sandbox"]):
        try:
            subprocess.run(orden[:1] + extra + orden[1:],
                           check=True, capture_output=True, timeout=120)
            break
        except subprocess.CalledProcessError:
            if extra:
                raise
    os.replace(tmp, destino)
    return destino


class Handler(BaseHTTPRequestHandler):
    server_version = "Reportes/2.0"

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args), flush=True)

    def _send(self, code, body=b"", ctype="text/plain; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def _file(self, ruta, ctype=None):
        if not os.path.isfile(ruta):
            return self._send(404, b"no encontrado")
        ctype = ctype or mimetypes.guess_type(ruta)[0] or "application/octet-stream"
        with open(ruta, "rb") as fh:
            return self._send(200, fh.read(), ctype)

    def do_GET(self):
        parsed = urlparse(self.path)
        path, query = parsed.path, parse_qs(parsed.query)

        if path in ("/", "/index.html"):
            return self._send(200, INDEX.encode(), "text/html; charset=utf-8")

        if path in STATIC:
            return self._file(os.path.join(BASE, STATIC[path]), "text/html; charset=utf-8")

        if path == "/descargar":
            return self._file(os.path.join(BASE, "reportabilidad.zip"), "application/zip")

        if path == "/historial":
            return self._send(200, historial_html().encode(), "text/html; charset=utf-8")

        if path == "/list":
            items = []
            for f in sorted(os.listdir(UPLOAD_DIR), reverse=True):
                full = os.path.join(UPLOAD_DIR, f)
                if os.path.isfile(full) and not f.startswith("."):
                    items.append({"name": f, "size_kb": round(os.path.getsize(full) / 1024, 1)})
            return self._json(200, items)

        if path == "/api/reportes":
            return self._json(200, cargar_reportes())

        if path.startswith("/api/reportes/"):
            rid = unquote(path[len("/api/reportes/"):])
            if not ID_OK.match(rid):
                return self._send(400, b"id invalido")
            return self._file(os.path.join(REPORT_DIR, f"{rid}.json"), "application/json; charset=utf-8")

        if path == "/reporte.pdf":
            rid = (query.get("id") or [""])[0]
            if not ID_OK.match(rid):
                return self._file(os.path.join(BASE, "reporte-turno-C.pdf"), "application/pdf")
            try:
                return self._file(generar_pdf(rid), "application/pdf")
            except FileNotFoundError:
                return self._send(404, b"reporte no encontrado")
            except RuntimeError as exc:
                return self._send(500, str(exc).encode())
            except subprocess.SubprocessError as exc:
                return self._send(500, f"error generando pdf: {exc}".encode())

        if path.startswith("/uploads/"):
            name = os.path.basename(unquote(path[len("/uploads/"):]))
            return self._file(os.path.join(UPLOAD_DIR, name))

        return self._send(404, b"no encontrado")

    def do_POST(self):
        parsed = urlparse(self.path)
        path, query = parsed.path, parse_qs(parsed.query)

        if path == "/upload":
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0:
                return self._send(400, b"cuerpo vacio")
            if length > MAX_BYTES:
                return self._send(413, b"archivo demasiado grande")
            data = b""
            while len(data) < length:
                chunk = self.rfile.read(min(65536, length - len(data)))
                if not chunk:
                    break
                data += chunk
            name = self._nombre_archivo(query.get("name", ["foto"])[0])
            with open(os.path.join(UPLOAD_DIR, name), "wb") as fh:
                fh.write(data)
            print(f"guardado {name} ({len(data)} bytes)", flush=True)
            return self._json(201, {"name": name})

        if path == "/api/reportes":
            length = int(self.headers.get("Content-Length") or 0)
            crudo = self.rfile.read(length) if length else b"{}"
            try:
                cuerpo = json.loads(crudo or b"{}")
            except json.JSONDecodeError as exc:
                return self._send(400, f"json invalido: {exc}".encode())
            data = cuerpo.get("data") or {}
            if not data.get("fechaCorte"):
                return self._send(400, b"falta fechaCorte")
            rid = cuerpo.get("id") or report_id(data)
            if not ID_OK.match(rid):
                return self._send(400, b"id invalido")
            os.makedirs(REPORT_DIR, exist_ok=True)
            with open(os.path.join(REPORT_DIR, f"{rid}.json"), "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
            print(f"reporte guardado {rid}", flush=True)
            return self._json(200, {"id": rid, "url": f"/reporte?id={rid}",
                                    "pdf": f"/reporte.pdf?id={rid}"})

        return self._send(404, b"no encontrado")

    @staticmethod
    def _nombre_archivo(raw: str) -> str:
        name = os.path.basename(unquote(raw)).strip() or "foto"
        name = re.sub(r"[^A-Za-z0-9._-]+", "_", name)
        stem, ext = os.path.splitext(name)
        stamp = time.strftime("%H%M%S")
        candidato, n = f"{stem}_{stamp}{ext}", 1
        while os.path.exists(os.path.join(UPLOAD_DIR, candidato)):
            candidato, n = f"{stem}_{stamp}_{n}{ext}", n + 1
        return candidato


def abrir_navegador(url: str):
    """Abre el editor en modo ventana (sin barra de direcciones) si se puede."""
    if os.environ.get("NO_ABRIR"):
        return
    if NAVEGADOR:
        try:
            subprocess.Popen([NAVEGADOR, f"--app={url}", "--window-size=1440,1000"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except OSError:
            pass
    webbrowser.open(url)


if __name__ == "__main__":
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    os.makedirs(REPORT_DIR, exist_ok=True)
    PUERTO_ACTUAL = puerto_libre(PUERTO_BASE)
    url = f"http://127.0.0.1:{PUERTO_ACTUAL}/editor"
    print(f"Reportes STG/CCU en {url}", flush=True)
    print(f"PDF: {'si (' + os.path.basename(NAVEGADOR) + ')' if NAVEGADOR else 'no (instala Chrome o Edge)'}", flush=True)
    print("Cierra esta ventana para apagar el servidor.", flush=True)
    threading.Timer(1.0, lambda: abrir_navegador(url)).start()
    try:
        ThreadingHTTPServer(("127.0.0.1", PUERTO_ACTUAL), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\nchao", flush=True)
    except OSError as exc:
        print(f"No pude abrir el puerto {PUERTO_ACTUAL}: {exc}", flush=True)
        sys.exit(1)
