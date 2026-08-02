import { useEffect } from 'react';
import { authToken } from '@/services';

export default function useAlertsRealtime(onEvent: (message?: unknown) => void) {
  useEffect(() => {
    let active = true;
    let socket: WebSocket | null = null;
    let retry: number | undefined;
    const connect = () => {
      const token = authToken.get();
      if (!active || !token) return;
      const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
      socket = new WebSocket(`${scheme}://${location.host}/ws/alerts`, ['bearer', token]);
      socket.onopen = () => onEvent();
      socket.onmessage = event => {
        try { onEvent(JSON.parse(event.data)); }
        catch { onEvent(); }
      };
      socket.onclose = () => { if (active) retry = window.setTimeout(connect, 2000); };
    };
    connect();
    return () => { active = false; if (retry) clearTimeout(retry); socket?.close(); };
  }, [onEvent]);
}
