import { api, apiBlob } from './api';

export interface Camera {
  id: number;
  camera_key: string;
  name: string;
  source: string;
  source_type: 'USB' | 'RTSP' | 'HTTP' | 'VIDEO_FILE';
  location_desc: string | null;
  status: string;
  zone_enabled: boolean;
  fall_enabled: boolean;
  ppe_enabled: boolean;
  config_revision: number;
  applied_revision: number | null;
  config_status: 'PENDING' | 'APPLIED' | 'FAILED' | 'OFFLINE';
  config_error: string | null;
  processing_fps: number | null;
  latency_ms: number | null;
  last_frame_at: string | null;
}

export interface Violation {
  id: number;
  event_id: string;
  camera_id: number;
  track_id: string;
  detected_time: string;
  violation_type: string;
  severity_level: string;
  confidence: number | null;
  zone_id: number | null;
  violation_codes: string[] | null;
  evidence_status: string;
  status: string;
}

export interface EvidenceUrls {
  violation_id: number;
  image_url: string | null;
  video_url: string | null;
}

export interface ReportSummary {
  total_violations: number;
  total_cameras: number;
  total_users: number;
  violations_by_type: { violation_type: string; count: number }[];
  violations_by_camera: { camera_id: number; camera_name: string; count: number }[];
}

export interface Zone {
  id: number;
  camera_id: number;
  name: string;
  polygon_json: number[][];
  is_active: boolean;
}

export const camerasApi = {
  list: () => api<Camera[]>('/cameras'),
  create: (input: Partial<Camera>) => api<Camera>('/cameras', { method: 'POST', body: JSON.stringify(input) }),
  update: (id: number, input: Partial<Camera>) => api<Camera>(`/cameras/${id}`, { method: 'PATCH', body: JSON.stringify(input) }),
  remove: (id: number) => api(`/cameras/${id}`, { method: 'DELETE' }),
  models: (id: number, input: Partial<Pick<Camera, 'ppe_enabled' | 'fall_enabled' | 'zone_enabled'>>) =>
    api<Camera>(`/cameras/${id}/models`, { method: 'PATCH', body: JSON.stringify(input) }),
  frame: (id: number, overlay: boolean) => apiBlob(`/cameras/${id}/stream?overlay=${overlay}`),
};

export const violationsApi = {
  list: (query = '') => api<Violation[]>(`/violations${query}`),
  evidence: (id: number) => api<EvidenceUrls>(`/violations/${id}/presigned-url`),
};

export const reportsApi = { summary: () => api<ReportSummary>('/reports/summary') };
export const zonesApi = {
  list: (cameraId: number) => api<Zone[]>(`/zones?camera_id=${cameraId}`),
  create: (cameraId: number, name: string, polygon: number[][]) => api<Zone>('/zones', { method: 'POST', body: JSON.stringify({ camera_id: cameraId, name, polygon_json: polygon, is_active: true }) }),
  update: (zone: Zone, input: Partial<Pick<Zone, 'name' | 'polygon_json' | 'is_active'>>) => api<Zone>(`/zones/${zone.id}`, { method: 'PATCH', body: JSON.stringify(input) }),
  remove: (id: number) => api<void>(`/zones/${id}`, { method: 'DELETE' }),
};
