import { useEffect, useState } from 'react';
import { authToken, camerasApi, type Camera } from '@/services';

type Props = {
  camera: Camera;
  overlay: boolean;
  className?: string;
};

export default function CameraLiveFrame({ camera, overlay, className }: Props) {
  const [url, setUrl] = useState('');

  useEffect(() => {
    if (camera.status !== 'ONLINE') {
      setUrl('');
      return;
    }
    let active = true;
    let currentUrl = '';
    let socket: WebSocket | null = null;
    let retry: number | undefined;

    const show = (blob: Blob) => {
      if (!active) return;
      const next = URL.createObjectURL(blob);
      if (currentUrl) URL.revokeObjectURL(currentUrl);
      currentUrl = next;
      setUrl(next);
    };

    const loadSnapshot = async () => {
      try { show(await camerasApi.frame(camera.id, overlay)); }
      catch { /* WebSocket can still deliver the next frame. */ }
    };

    const connect = () => {
      const token = authToken.get();
      if (!active || !token) return;
      const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
      socket = new WebSocket(
        `${scheme}://${location.host}/ws/cameras/${camera.id}?overlay=${overlay}`,
        ['bearer', token],
      );
      socket.binaryType = 'blob';
      socket.onmessage = event => {
        if (event.data instanceof Blob) show(event.data);
        else if (event.data instanceof ArrayBuffer) show(new Blob([event.data], { type: 'image/jpeg' }));
      };
      socket.onclose = () => {
        if (active) retry = window.setTimeout(connect, 1500);
      };
    };

    void loadSnapshot();
    connect();
    return () => {
      active = false;
      if (retry) window.clearTimeout(retry);
      socket?.close();
      if (currentUrl) URL.revokeObjectURL(currentUrl);
    };
  }, [camera.id, camera.status, overlay]);

  return url
    ? <img className={className} src={url} alt={`Xem trực tiếp ${camera.name}`} />
    : <span className="material-symbols-outlined" aria-label={`${camera.name} đang ngoại tuyến`}>videocam_off</span>;
}
