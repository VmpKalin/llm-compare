const express = require('express');
const { createProxyMiddleware } = require('http-proxy-middleware');

const app = express();

app.use('/', createProxyMiddleware({
    target: 'http://192.168.0.157:11434',
    changeOrigin: true,

    // Логуємо запит ТУТ — з даних, які проксі вже зібрав, не чіпаючи вхідний потік.
    onProxyReq: (proxyReq, req, res) => {
        let body = [];
        req.on('data', chunk => body.push(chunk));
        req.on('end', () => {
            try {
                const parsed = JSON.parse(Buffer.concat(body).toString());
                console.log('\n--- [REQUEST FROM AIDER] ---');
                console.log(JSON.stringify(parsed, null, 2));
            } catch (e) { /* не JSON — ігноруємо */ }
        });
    },

    onError: (err, req, res) => {
        console.error('\n--- [PROXY ERROR] ---', err.code, err.message);
        if (res && !res.headersSent) res.writeHead(502);
        if (res) res.end('proxy error: ' + err.message);
    }
}));

app.listen(3000, () => console.log('Proxy on http://localhost:3000'));