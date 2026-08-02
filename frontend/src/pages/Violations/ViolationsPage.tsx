import { useCallback, useEffect, useMemo, useState } from 'react';
import { ApiError, camerasApi, violationsApi, type Camera, type EvidenceUrls, type Violation } from '@/services';
import styles from './ViolationsPage.module.css';
import useAlertsRealtime from '@/hooks/useAlertsRealtime';

const labels: Record<string, string> = {
  PPE_VIOLATION: 'Vi phạm trang bị bảo hộ',
  FALL_DETECTED: 'Phát hiện ngã',
  RESTRICTED_ZONE: 'Đi vào vùng cấm',
  FALL_SUSPECTED: 'Nghi ngờ ngã',
};

export default function ViolationsPage() {
  const [logs, setLogs] = useState<Violation[]>([]);
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [search, setSearch] = useState('');
  const [severity, setSeverity] = useState('all');
  const [selected, setSelected] = useState<Violation | null>(null);
  const [evidence, setEvidence] = useState<EvidenceUrls | null>(null);
  const [evidenceError, setEvidenceError] = useState('');
  const [videoError, setVideoError] = useState('');

  const load = useCallback(async () => {
    setError('');
    try {
      const [nextLogs, nextCameras] = await Promise.all([violationsApi.list('?limit=200'), camerasApi.list()]);
      setLogs(nextLogs); setCameras(nextCameras);
    } catch (reason) { setError(reason instanceof ApiError ? reason.message : 'Không thể tải cảnh báo.'); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { void load(); }, [load]);
  useAlertsRealtime(load);
  const loadEvidence = useCallback(async (violation: Violation) => {
    setEvidenceError('');
    setVideoError('');
    try { setEvidence(await violationsApi.evidence(violation.id)); }
    catch (reason) { setEvidenceError(reason instanceof ApiError ? reason.message : 'Không thể tải evidence.'); }
  }, []);

  useEffect(() => {
    if (!selected || selected.evidence_status !== 'READY') { setEvidence(null); return; }
    void loadEvidence(selected);
  }, [loadEvidence, selected]);

  const cameraMap = useMemo(() => new Map(cameras.map(camera => [camera.id, camera])), [cameras]);
  const filtered = logs.filter(log => {
    const camera = cameraMap.get(log.camera_id);
    const haystack = `${labels[log.violation_type] || log.violation_type} ${camera?.name || ''} ${log.track_id}`.toLowerCase();
    return haystack.includes(search.toLowerCase()) && (severity === 'all' || log.severity_level === severity);
  });

  if (loading) return <div className={styles.emptyState}>Đang tải cảnh báo...</div>;
  return <div>
    <div className={styles.topBar}>
      <div className={`input-group ${styles.searchField}`}><label className="input-label" htmlFor="alert-search">Tìm cảnh báo</label><div className="input-wrapper"><span className="material-symbols-outlined input-icon">search</span><input id="alert-search" className="input-field" value={search} onChange={e => setSearch(e.target.value)} placeholder="Camera, loại lỗi hoặc track ID" /></div></div>
      <div><label className="input-label" htmlFor="severity">Mức độ</label><select id="severity" className={styles.filterSelect} value={severity} onChange={e => setSeverity(e.target.value)}><option value="all">Tất cả</option><option value="CRITICAL">Critical</option><option value="DANGER">Danger</option><option value="WARNING">Warning</option></select></div>
    </div>
    {error && <div className={styles.emptyState} role="alert">{error} <button onClick={() => void load()}>Thử lại</button></div>}
    <div className={styles.tableContainer}><table className={styles.table}><thead><tr><th className={styles.th}>ID</th><th className={styles.th}>Thời gian</th><th className={styles.th}>Camera</th><th className={styles.th}>Cảnh báo</th><th className={styles.th}>Mức độ</th><th className={`${styles.th} ${styles.actionsCell}`}>Evidence</th></tr></thead>
      <tbody>{filtered.map(log => <tr key={log.id} className={styles.tr}><td className={`${styles.td} ${styles.violationTitle}`}>#{log.id}</td><td className={`${styles.td} tabular-nums`}>{new Date(log.detected_time).toLocaleString('vi-VN')}</td><td className={styles.td}>{cameraMap.get(log.camera_id)?.name || `Camera ${log.camera_id}`}<small className={styles.track}>Track {log.track_id}</small></td><td className={styles.td}>{labels[log.violation_type] || log.violation_type}{log.violation_codes?.length ? <small className={styles.track}>{log.violation_codes.join(', ')}</small> : null}</td><td className={styles.td}><span className={`badge ${log.severity_level === 'CRITICAL' || log.severity_level === 'DANGER' ? 'badge-danger' : 'badge-warning'}`}>{log.severity_level}</span></td><td className={`${styles.td} ${styles.actionsCell}`}><button className="btn btn-outline" onClick={() => setSelected(log)}>{log.evidence_status === 'READY' ? 'Xem' : log.evidence_status}</button></td></tr>)}
      {!filtered.length && <tr><td colSpan={6} className={styles.emptyState}>Không có cảnh báo phù hợp.</td></tr>}</tbody></table></div>
    {selected && <div className={styles.modal} role="dialog" aria-modal="true"><div className={styles.dialog}><div className={styles.dialogHeader}><h3>Cảnh báo #{selected.id}</h3><button onClick={() => setSelected(null)} aria-label="Đóng"><span className="material-symbols-outlined">close</span></button></div>
      <div className={styles.evidence}>{evidence?.video_url ? <div className={styles.videoEvidence}><video key={evidence.video_url} src={evidence.video_url} controls preload="metadata" playsInline onError={() => setVideoError('Trình duyệt không thể phát video này. Hãy làm mới URL; evidence cũ có thể dùng codec chưa tương thích.')} />{videoError && <div className={styles.mediaError} role="alert"><p>{videoError}</p><button className="btn btn-outline" onClick={() => void loadEvidence(selected)}>Làm mới URL video</button></div>}</div> : evidence?.image_url ? <img src={evidence.image_url} alt={`Evidence cảnh báo ${selected.id}`} /> : selected.evidence_status === 'PROCESSING' ? <p>Evidence đang được xử lý.</p> : <p>{evidenceError || 'Không có evidence.'}</p>}{evidence?.video_url && evidence.image_url && <details className={styles.thumbnail}><summary>Xem ảnh tại thời điểm cảnh báo</summary><img src={evidence.image_url} alt={`Ảnh evidence cảnh báo ${selected.id}`} /></details>}</div>
      <dl className={styles.details}><div><dt>Loại</dt><dd>{labels[selected.violation_type] || selected.violation_type}</dd></div><div><dt>Camera</dt><dd>{cameraMap.get(selected.camera_id)?.name || selected.camera_id}</dd></div><div><dt>Track ID</dt><dd>{selected.track_id}</dd></div><div><dt>Thời gian</dt><dd>{new Date(selected.detected_time).toLocaleString('vi-VN')}</dd></div>{selected.confidence != null && <div><dt>Độ tin cậy</dt><dd>{(selected.confidence * 100).toFixed(1)}%</dd></div>}</dl>
    </div></div>}
  </div>;
}
