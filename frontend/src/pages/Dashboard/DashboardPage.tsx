import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { camerasApi, reportsApi, violationsApi, type Camera, type ReportSummary, type Violation } from '@/services';
import { CameraLiveFrame } from '@/components';
import useAlertsRealtime from '@/hooks/useAlertsRealtime';
import styles from './DashboardPage.module.css';

const alertLabel: Record<string, string> = { PPE_VIOLATION: 'Vi phạm PPE', FALL_DETECTED: 'Phát hiện ngã', RESTRICTED_ZONE: 'Đi vào vùng cấm', FALL_SUSPECTED: 'Nghi ngờ ngã' };

export default function DashboardPage() {
  const navigate = useNavigate();
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [alerts, setAlerts] = useState<Violation[]>([]);
  const [summary, setSummary] = useState<ReportSummary | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [overlay, setOverlay] = useState(true);

  const load = useCallback(async () => {
    try {
      const [cameraData, alertData, reportData] = await Promise.all([camerasApi.list(), violationsApi.list('?limit=8'), reportsApi.summary()]);
      setCameras(cameraData); setAlerts(alertData); setSummary(reportData); setError('');
    } catch { setError('Không thể đồng bộ dữ liệu dashboard.'); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { void load(); }, [load]);
  useAlertsRealtime(load);

  const online = cameras.filter(camera => camera.status === 'ONLINE').length;
  const pending = cameras.filter(camera => camera.config_status === 'PENDING').length;
  const averageFps = useMemo(() => {
    const values = cameras.flatMap(camera => camera.processing_fps == null ? [] : [camera.processing_fps]);
    return values.length ? (values.reduce((a, b) => a + b, 0) / values.length).toFixed(1) : '-';
  }, [cameras]);

  if (loading) return <div className="glass-panel" style={{padding:24}}>Đang tải dashboard...</div>;
  return <div>
    {error && <div className="glass-panel" role="alert" style={{padding:16, marginBottom:16, color:'var(--color-danger)'}}>{error} <button onClick={() => void load()}>Thử lại</button></div>}
    <div className={styles.metricsGrid}>
      <Metric icon="videocam" title="Camera online" value={`${online} / ${cameras.length}`} />
      <Metric icon="speed" title="FPS trung bình" value={averageFps} />
      <Metric icon="warning" title="Tổng cảnh báo" value={String(summary?.total_violations ?? 0)} action={() => navigate('/violations')} />
      <Metric icon="sync" title="Cấu hình chờ ACK" value={String(pending)} action={() => navigate('/cameras')} />
    </div>
    <div className={styles.mainGrid}>
      <section className={`${styles.feedCard} glass-panel`}><div className={styles.cardHeader}><h3 className={styles.cardTitle}>Lưới camera trực tiếp</h3><div className={styles.headerActions}><button className="btn btn-outline" onClick={() => setOverlay(value => !value)}>{overlay ? 'Tắt overlay' : 'Bật overlay'}</button><button className="btn btn-outline" onClick={() => navigate('/cameras')}>Quản lý camera</button></div></div>
        <div className={styles.liveGrid}>{cameras.map(camera => <article className={styles.liveTile} key={camera.id}><div className={styles.liveViewport}><CameraLiveFrame camera={camera} overlay={overlay} /><span className={`${styles.liveStatus} ${camera.status === 'ONLINE' ? styles.liveOnline : ''}`}>{camera.status}</span></div><div className={styles.liveMeta}><span><strong>{camera.name}</strong><small>{camera.location_desc || camera.camera_key}</small></span><span>{camera.processing_fps?.toFixed(1) ?? '-'} FPS<br />{camera.latency_ms?.toFixed(0) ?? '-'} ms</span></div></article>)}{!cameras.length && <p>Chưa có camera được cấu hình.</p>}</div>
      </section>
      <section className={`${styles.alertsCard} glass-panel`}><div className={styles.cardHeader}><h3 className={styles.cardTitle}>Cảnh báo mới nhất</h3><button className="btn btn-outline" onClick={() => navigate('/violations')}>Xem tất cả</button></div><ul className={styles.alertsList}>{alerts.map(alert => <li key={alert.id} className={styles.alertItem}><div className={styles.alertContent}><div className={styles.alertHeading}>{alertLabel[alert.violation_type] || alert.violation_type}</div><div className={styles.alertMeta}><span>Camera {alert.camera_id}</span><time>{new Date(alert.detected_time).toLocaleTimeString('vi-VN')}</time></div></div></li>)}{!alerts.length && <li>Chưa có cảnh báo.</li>}</ul></section>
    </div>
  </div>;
}

function Metric({icon, title, value, action}:{icon:string; title:string; value:string; action?:()=>void}) {
  return <div className={`${styles.metricCard} glass-panel`} onClick={action} role={action ? 'button' : undefined} tabIndex={action ? 0 : undefined}><div className={styles.metricIconWrapper}><span className="material-symbols-outlined">{icon}</span></div><div><div className={styles.metricTitle}>{title}</div><div className={`${styles.metricValue} tabular-nums`}>{value}</div></div></div>;
}
