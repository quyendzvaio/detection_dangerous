import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import useTheme from '@/hooks/useTheme';
import { getMe, logout, type CurrentUser } from '@/services';
import styles from './SettingsPage.module.css';

export default function SettingsPage() {
  const { theme, setTheme } = useTheme();
  const navigate = useNavigate();
  const [user, setUser] = useState<CurrentUser | null>(null);
  useEffect(() => { getMe().then(setUser).catch(() => setUser(null)); }, []);
  const signOut = () => { logout(); navigate('/login', {replace:true}); };
  return <div style={{display:'flex', flexDirection:'column', gap:24}}>
    <section className={`${styles.card} glass-panel`}><div className={styles.title}><span className="material-symbols-outlined text-primary">account_circle</span>Tài khoản</div>{user ? <div><p><strong>{user.gmail}</strong></p><p style={{fontSize:13,color:'var(--on-surface-variant)'}}>Loại tài khoản: {user.role}</p></div> : <p>Không thể tải thông tin tài khoản.</p>}<button className="btn btn-outline" onClick={signOut}>Đăng xuất</button></section>
    <section className={`${styles.card} glass-panel`}><div className={styles.title}><span className="material-symbols-outlined text-primary">palette</span>Giao diện</div><p style={{fontSize:13,color:'var(--on-surface-variant)'}}>Chọn chế độ hiển thị cho phòng giám sát.</p><div className={styles.themeSelector}><button className={`${styles.themeOption} ${theme === 'light' ? styles.themeOptionActive : ''}`} onClick={() => setTheme('light')}><span className="material-symbols-outlined text-3xl">light_mode</span><span className={styles.themeName}>Sáng</span></button><button className={`${styles.themeOption} ${theme === 'dark' ? styles.themeOptionActive : ''}`} onClick={() => setTheme('dark')}><span className="material-symbols-outlined text-3xl">dark_mode</span><span className={styles.themeName}>Tối</span></button></div></section>
    <section className={`${styles.card} glass-panel`}><div className={styles.title}><span className="material-symbols-outlined text-primary">info</span>Phạm vi MVP</div><p style={{fontSize:13,lineHeight:1.6,color:'var(--on-surface-variant)'}}>Email/SMS, chính sách retention và báo cáo nâng cao chưa được bật trong bản MVP. Evidence được lưu trên Azure theo cấu hình vận hành.</p></section>
  </div>;
}
