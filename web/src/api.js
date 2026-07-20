export async function get(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function post(url, body) {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
  return r.json();
}

export async function del(url) {
  const r = await fetch(url, { method: "DELETE" });
  return r.json();
}

export function connectWs(onMessage, onStatus) {
  let ws;
  let timer;
  let closed = false;

  const connect = () => {
    if (closed) return;
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${proto}://${location.host}/ws`);
    ws.onopen = () => {
      onStatus?.(true);
      timer = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) ws.send("ping");
      }, 20000);
    };
    ws.onclose = () => {
      onStatus?.(false);
      clearInterval(timer);
      if (!closed) setTimeout(connect, 2000);
    };
    ws.onerror = () => ws.close();
    ws.onmessage = (ev) => {
      try {
        onMessage(JSON.parse(ev.data));
      } catch {
        /* ignore */
      }
    };
  };

  connect();
  return () => {
    closed = true;
    clearInterval(timer);
    ws?.close();
  };
}
