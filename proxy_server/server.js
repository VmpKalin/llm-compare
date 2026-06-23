const express = require('express');
const { createProxyMiddleware } = require('http-proxy-middleware');

const app = express();

// НЕ використовуємо express.json() — щоб не споживати потік тіла.
// Логуємо сирі дані вручну, не торкаючись самого потоку для проксі.
app.use((req, res, next) => {
    let raw = '';
    req.on('data', chunk => { raw += chunk.toString(); });
    req.on('end', () => {
        console.log('\n--- [REQUEST FROM AIDER] ---');
        try { console.log(JSON.parse(raw)); } catch { console.log(raw); }
    });
    // ВАЖЛИВО: не чекаємо 'end', одразу передаємо далі —
    // потік тіла лишається недоторканим для проксі
    next();
});

app.use('/', createProxyMiddleware({
    target: 'http://192.168.0.157:11434',
    changeOrigin: true,
    selfHandleResponse: true,

    onProxyRes: (proxyRes, req, res) => {
        console.log('\n--- [RESPONSE FROM LLAMA] (status ' + proxyRes.statusCode + ') ---');
        res.statusCode = proxyRes.statusCode;
        res.setHeader('Content-Type', proxyRes.headers['content-type'] || 'application/json');
        proxyRes.on('data', (chunk) => {
            process.stdout.write(chunk.toString());
            res.write(chunk);
        });
        proxyRes.on('end', () => {
            console.log('\n--- [STREAM END] ---');
            res.end();
        });
    },

    onError: (err, req, res) => {
        console.error('\n--- [PROXY ERROR] ---', err.code, err.message);
        if (res && !res.headersSent) res.writeHead(502, { 'Content-Type': 'text/plain' });
        if (res) res.end('proxy error: ' + err.message);
    }
}));

app.listen(3000, () => {
    console.log('LLM Proxy Server is running on http://localhost:3000');
});