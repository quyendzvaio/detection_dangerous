import { useEffect, useState } from 'react';
import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { authToken, getMe } from '@/services';

export default function ProtectedRoute() {
  const location = useLocation();
  const [authorized, setAuthorized] = useState<boolean | null>(authToken.get() ? null : false);
  useEffect(() => {
    if (!authToken.get()) { setAuthorized(false); return; }
    getMe().then(() => setAuthorized(true)).catch(() => setAuthorized(false));
  }, []);
  if (authorized === null) return <div style={{padding:24}}>Đang xác thực...</div>;
  if (!authorized) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  return <Outlet />;
}
