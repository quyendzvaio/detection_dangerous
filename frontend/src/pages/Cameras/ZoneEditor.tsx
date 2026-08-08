import { useCallback, useEffect, useState } from 'react';
import { ApiError, zonesApi, type Camera, type Zone } from '@/services';
import { CameraLiveFrame } from '@/components';
import styles from './CamerasPage.module.css';

export default function ZoneEditor({camera, onClose}:{camera:Camera; onClose:()=>void}) {
  const [zones, setZones] = useState<Zone[]>([]);
  const [name, setName] = useState('Khu vực cấm');
  const [points, setPoints] = useState<number[][]>([]);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const [editing, setEditing] = useState<Zone | null>(null);
  const load = useCallback(() => zonesApi.list(camera.id).then(setZones).catch(reason => setError(reason instanceof ApiError ? reason.message : 'Không thể tải zone.')), [camera.id]);
  useEffect(() => { void load(); }, [load]);

  const addPoint = (event: React.MouseEvent<HTMLDivElement>) => {
    const bounds = event.currentTarget.getBoundingClientRect();
    setPoints(current => [...current, [Number(((event.clientX - bounds.left) / bounds.width).toFixed(4)), Number(((event.clientY - bounds.top) / bounds.height).toFixed(4))]]);
  };
  const save = async () => {
    if (points.length < 3) { setError('Cần ít nhất 3 điểm để tạo polygon.'); return; }
    setSaving(true); setError('');
    try {
      if (editing) await zonesApi.update(editing, {name, polygon_json: points});
      else await zonesApi.create(camera.id, name, points);
      setPoints([]); setEditing(null); setName('Khu vực cấm'); await load();
    }
    catch (reason) { setError(reason instanceof ApiError ? reason.message : 'Không thể lưu zone.'); }
    finally { setSaving(false); }
  };
  const toggle = async (zone: Zone) => { try { await zonesApi.update(zone, {is_active: !zone.is_active}); await load(); } catch { setError('Không thể cập nhật zone.'); } };
  const remove = async (zone: Zone) => { if (!window.confirm(`Xóa zone "${zone.name}"?`)) return; try { await zonesApi.remove(zone.id); await load(); } catch { setError('Không thể xóa zone.'); } };

  const polygon = points.map(point => `${point[0] * 100},${point[1] * 100}`).join(' ');
  return <div className={styles.modal} role="dialog" aria-modal="true"><div className={styles.zoneDialog}>
    <div className={styles.formHeader}><div><h3>Zone: {camera.name}</h3><p>Nhấp lên khung hình theo thứ tự để vẽ vùng cấm.</p></div><button onClick={onClose} aria-label="Đóng"><span className="material-symbols-outlined">close</span></button></div>
    {error && <p className={styles.configError} role="alert">{error}</p>}
    <div className={styles.zoneCanvas} onClick={addPoint} role="button" tabIndex={0} aria-label="Khung vẽ polygon">
      <CameraLiveFrame camera={camera} overlay={false} className={styles.zoneFrame} />
      <svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true"><polygon points={polygon} /><g>{points.map((point,index) => <circle key={index} cx={point[0]*100} cy={point[1]*100} r="1.5" />)}</g></svg>
      {!points.length && <span className={styles.zoneHint}>Nhấp để đặt điểm đầu tiên</span>}
    </div>
    <div className={styles.zoneActions}><label>Tên zone<input value={name} onChange={e => setName(e.target.value)} /></label><button className="btn btn-outline" onClick={() => {setPoints([]);setEditing(null);}}>Vẽ lại</button><button className="btn btn-primary" disabled={saving || points.length < 3} onClick={() => void save()}>{saving ? 'Đang lưu...' : editing ? 'Cập nhật zone' : 'Lưu zone'}</button></div>
    <div className={styles.zoneList}>{zones.map(zone => <div key={zone.id}><span><strong>{zone.name}</strong><small>{zone.polygon_json.length} điểm, {zone.is_active ? 'đang bật' : 'đang tắt'}</small></span><button className="btn btn-outline" onClick={() => {setEditing(zone);setName(zone.name);setPoints(zone.polygon_json);}}>Sửa</button><button className="btn btn-outline" onClick={() => void toggle(zone)}>{zone.is_active ? 'Tắt' : 'Bật'}</button><button className="btn btn-outline" onClick={() => void remove(zone)}>Xóa</button></div>)}{!zones.length && <p>Camera này chưa có zone.</p>}</div>
  </div></div>;
}
