# Tiny local receiver for the Splash collector.
#
# Splash's Content-Security-Policy blocks fetch() from its page to localhost, but it
# cannot block window.postMessage. So the Splash tab embeds /collector.html from this
# server in an iframe and posts the collected JSON to it; the iframe (same origin as
# this server) then POSTs the JSON here, and we save it and exit.
import json, sys, pathlib, threading, urllib.parse, base64, gzip
from http.server import BaseHTTPRequestHandler, HTTPServer

OUT = pathlib.Path(sys.argv[1])
LOG = OUT.with_suffix(".log")

COLLECTOR_HTML = b"""<!doctype html><meta charset="utf-8"><title>collector</title>
<p id=s style="font-family:sans-serif">waiting for data...</p>
<script>
const note = (m) => fetch('/note?' + encodeURIComponent(m)).catch(() => {});
note('collector script running');
if (location.hash.length > 10) {
  fetch('/b64', {method: 'POST', headers: {'content-type': 'text/plain'}, body: location.hash.slice(1)})
    .then(r => r.text()).then(t => { document.getElementById('s').textContent = t; history.replaceState(null, '', location.pathname); })
    .catch(e => note('b64 post failed: ' + e));
}
window.addEventListener('message', async (ev) => {
  note('message from ' + ev.origin + ' type=' + typeof ev.data + ' len=' + (ev.data && ev.data.length));
  if (typeof ev.data !== 'string' || ev.data[0] !== '{') return;
  try {
    const r = await fetch('/', {method: 'POST', headers: {'content-type': 'application/json'}, body: ev.data});
    document.getElementById('s').textContent = 'saved: ' + r.status;
    ev.source.postMessage('saved ' + r.status, '*');
  } catch (e) { note('post failed: ' + e); }
});
</script>"""

def log(msg):
    with LOG.open("a", encoding="utf-8") as f:
        f.write(msg + "\n")

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/note?"):
            log("NOTE " + urllib.parse.unquote(self.path[6:]))
            self.send_response(204); self.end_headers(); return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(COLLECTOR_HTML)
        log("GET " + self.path)

    def do_POST(self):
        n = int(self.headers.get("content-length", 0))
        body = self.rfile.read(n)
        if self.path == "/b64":
            body = gzip.decompress(base64.b64decode(body))
        json.loads(body)  # must be valid JSON
        OUT.write_bytes(body)
        self.send_response(200); self.send_header("Content-Type", "text/plain"); self.end_headers()
        self.wfile.write(b"saved")
        log(f"saved {len(body)} bytes")
        threading.Thread(target=srv.shutdown, daemon=True).start()

    def log_message(self, *a):
        pass

srv = HTTPServer(("127.0.0.1", 8765), H)
log("listening")
srv.serve_forever()
log("done")
