import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError, camerasApi, type Camera } from '@/services';
import { CameraLiveFrame } from '@/components';
import styles from './CamerasPage.module.css';
import ZoneEditor from './ZoneEditor';

const blankCamera = { name: '', camera_key: '', source: '', location_desc: '' };

export default function CamerasPage() {
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [showAdd, setShowAdd] = useState(false);
  const [form, setForm] = useState(blankCamera);
  const [saving, setSaving] = useState(false);
  const [overlay, setOverlay] = useState(true);
  const [zoneCamera, setZoneCamera] = useState<Camera | null>(null);
  const [zoomCamera, setZoomCamera] = useState<Camera | null>(null);
  const [editingCamera, setEditingCamera] = useState<Camera | null>(null);
  const [pendingToggles, setPendingToggles] = useState<Set<string>>(() => new Set());
  const pendingTogglesRef = useRef(new Set<string>());
  const cameraMutationVersion = useRef(0);

  const load = useCallback(async () => {
    const versionAtStart = cameraMutationVersion.current;
    setError('');
    try {
      const data = await camerasApi.list();
      // Ignore a polling response that began before a model mutation. Without
      // this guard a slow GET can repaint a switch with its previous value.
      if (versionAtStart !== cameraMutationVersion.current) return;
      setCameras(data);
      setZoomCamera(current => current ? data.find(item => item.id === current.id) ?? null : null);
      setZoneCamera(current => current ? data.find(item => item.id === current.id) ?? null : null);
    }
    catch (reason) { setError(reason instanceof ApiError ? reason.message : 'Không thể tải camera.'); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), 3000);
    return () => window.clearInterval(timer);
  }, [load]);

  const toggle = async (camera: Camera, field: 'ppe_enabled' | 'fall_enabled' | 'zone_enabled') => {
    const pendingKey = `${camera.id}:${field}`;
    if (pendingTogglesRef.current.has(pendingKey)) return;
    pendingTogglesRef.current.add(pendingKey);
    cameraMutationVersion.current += 1;
    setPendingToggles(new Set(pendingTogglesRef.current));
    setError('');
    try {
      // PATCH only the switch the operator touched. Sending all three values
      // lets an older render overwrite another switch during rapid clicks.
      const updated = await camerasApi.models(camera.id, { [field]: !camera[field] });
      cameraMutationVersion.current += 1;
      setCameras(items => items.map(item => item.id === updated.id ? updated : item));
    } catch (reason) { setError(reason instanceof ApiError ? reason.message : 'Không thể cập nhật model.'); }
    finally {
      pendingTogglesRef.current.delete(pendingKey);
      setPendingToggles(new Set(pendingTogglesRef.current));
    }
  };

  const create = async (event: React.FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setError('');
    try {
      const input = editingCamera && !form.source ? {name: form.name, camera_key: form.camera_key, location_desc: form.location_desc} : form;
      const saved = editingCamera
        ? await camerasApi.update(editingCamera.id, input)
        : await camerasApi.create(form);
      setCameras(items => editingCamera ? items.map(item => item.id === saved.id ? saved : item) : [...items, saved]);
      setForm(blankCamera);
      setEditingCamera(null);
      setShowAdd(false);
    } catch (reason) { setError(reason instanceof ApiError ? reason.message : 'Không thể thêm camera.'); }
    finally { setSaving(false); }
  };

  const remove = async (camera: Camera) => {
    if (!window.confirm(`Xóa nguồn "${camera.name}"? Lịch sử cảnh báo vẫn được giữ.`)) return;
    try {
      await camerasApi.remove(camera.id);
      setCameras(items => items.filter(item => item.id !== camera.id));
    } catch (reason) { setError(reason instanceof ApiError ? reason.message : 'Không thể xóa camera.'); }
  };

  if (loading) return <div className={styles.state}>Đang tải nguồn giám sát...</div>;

  return <div className={styles.page}>
    <div className={styles.toolbar}>
      <div><h2>Nguồn giám sát</h2><p>{cameras.length} camera hoặc video đã cấu hình</p></div>
      <div className={styles.toolbarActions}><button className="btn btn-outline" onClick={() => setOverlay(value => !value)}>{overlay ? 'Tắt overlay' : 'Bật overlay'}</button><button className="btn btn-primary" onClick={() => setShowAdd(true)}>Thêm nguồn</button></div>
    </div>
    {error && <div className={styles.error} role="alert">{error} <button onClick={() => void load()}>Thử lại</button></div>}
    {cameras.length === 0 ? <div className={styles.state}>Chưa có nguồn. Thêm camera USB, RTSP, HTTP hoặc video file để bắt đầu.</div> :
      <div className={styles.grid}>{cameras.map(camera => <article className={styles.card} key={camera.id}>
        <div className={styles.preview} onClick={() => setZoomCamera(camera)} role="button" tabIndex={0} aria-label={`Phóng to ${camera.name}`}>
          <CameraLiveFrame camera={camera} overlay={overlay} />
          <span className={`${styles.status} ${camera.status === 'ONLINE' ? styles.online : ''}`}>{camera.status}</span>
        </div>
        <div className={styles.body}>
          <div className={styles.title}><div><h3>{camera.name}</h3><p>{camera.location_desc || camera.camera_key}</p></div><div className={styles.iconActions}><button aria-label={`Sửa ${camera.name}`} onClick={() => {setEditingCamera(camera);setForm({name:camera.name,camera_key:camera.camera_key,source:'',location_desc:camera.location_desc || ''});setShowAdd(true);}}><span className="material-symbols-outlined">edit</span></button><button aria-label={`Xóa ${camera.name}`} onClick={() => void remove(camera)}><span className="material-symbols-outlined">delete</span></button></div></div>
          <dl className={styles.metrics}><div><dt>FPS</dt><dd>{camera.processing_fps?.toFixed(1) ?? '-'}</dd></div><div><dt>Latency</dt><dd>{camera.latency_ms ? `${camera.latency_ms.toFixed(0)} ms` : '-'}</dd></div><div><dt>Config</dt><dd>{camera.config_status}</dd></div></dl>
          <div className={styles.toggles}>
            {(['ppe_enabled', 'fall_enabled', 'zone_enabled'] as const).map(field => { const pendingKey = `${camera.id}:${field}`; return <label key={field}><input type="checkbox" checked={camera[field]} disabled={pendingToggles.has(pendingKey)} onChange={() => void toggle(camera, field)} /><span>{field.split('_')[0].toUpperCase()}{pendingToggles.has(pendingKey) ? '…' : ''}</span></label>; })}
          </div>
          <button className="btn btn-outline" onClick={() => setZoneCamera(camera)}>Vẽ và quản lý zone</button>
          {camera.config_error && <p className={styles.configError}>{camera.config_error}</p>}
        </div>
      </article>)}</div>}
    {showAdd && <div className={styles.modal} role="dialog" aria-modal="true"><form className={styles.form} onSubmit={create}>
      <div className={styles.formHeader}><h3>{editingCamera ? 'Sửa nguồn giám sát' : 'Thêm nguồn giám sát'}</h3><button type="button" onClick={() => {setShowAdd(false);setEditingCamera(null);setForm(blankCamera);}} aria-label="Đóng"><span className="material-symbols-outlined">close</span></button></div>
      <label>Tên<input required value={form.name} onChange={e => setForm({...form, name:e.target.value})} /></label>
      <label>Mã camera<input required value={form.camera_key} onChange={e => setForm({...form, camera_key:e.target.value})} /></label>
      <label>Nguồn<input required={!editingCamera} value={form.source} onChange={e => setForm({...form, source:e.target.value})} placeholder={editingCamera ? 'Để trống để giữ nguồn hiện tại' : '0, rtsp://..., http://... hoặc file.mp4'} /></label>
      <label>Vị trí<input value={form.location_desc} onChange={e => setForm({...form, location_desc:e.target.value})} /></label>
      <div className={styles.actions}><button type="button" className="btn btn-outline" onClick={() => {setShowAdd(false);setEditingCamera(null);setForm(blankCamera);}}>Hủy</button><button disabled={saving} className="btn btn-primary">{saving ? 'Đang lưu...' : 'Lưu nguồn'}</button></div>
    </form></div>}
    {zoneCamera && <ZoneEditor camera={zoneCamera} onClose={() => setZoneCamera(null)} />}
    {zoomCamera && <div className={styles.modal} role="dialog" aria-modal="true"><div className={styles.liveDialog}><div className={styles.formHeader}><div><h3>{zoomCamera.name}</h3><p>{zoomCamera.location_desc || zoomCamera.camera_key}</p></div><button onClick={() => setZoomCamera(null)} aria-label="Đóng"><span className="material-symbols-outlined">close</span></button></div><div className={styles.fullFrame}><CameraLiveFrame camera={zoomCamera} overlay={overlay} /></div><dl className={styles.metrics}><div><dt>FPS</dt><dd>{zoomCamera.processing_fps?.toFixed(1) ?? '-'}</dd></div><div><dt>Latency</dt><dd>{zoomCamera.latency_ms?.toFixed(0) ?? '-'} ms</dd></div><div><dt>Frame cuối</dt><dd>{zoomCamera.last_frame_at ? new Date(zoomCamera.last_frame_at).toLocaleTimeString('vi-VN') : '-'}</dd></div></dl></div></div>}
  </div>;
}
