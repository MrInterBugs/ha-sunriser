const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '../..');
http.createServer((req, res) => {
  const url = new URL(req.url, 'http://localhost');
  const file = path.resolve(root, '.' + (url.pathname === '/' ? '/tests/browser/index.html' : url.pathname));
  if (!file.startsWith(root + path.sep)) { res.writeHead(403).end(); return; }
  try {
    let body = fs.readFileSync(file, 'utf8');
    if (file.endsWith('sunriser-dayplan-card.js')) {
      body = body.replace('https://unpkg.com/lit@3/index.js?module', '/node_modules/lit/index.js')
        .replace('https://unpkg.com/lit@3/directives/unsafe-svg.js?module', '/node_modules/lit/directives/unsafe-svg.js');
    }
    res.setHeader('Content-Type', file.endsWith('.html') ? 'text/html' : 'text/javascript');
    res.end(body);
  } catch { res.writeHead(404).end(); }
}).listen(8766, '127.0.0.1');
