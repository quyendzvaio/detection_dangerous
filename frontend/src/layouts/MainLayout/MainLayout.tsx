import { NavLink, Link, useNavigate, useLocation, Outlet } from 'react-router-dom';
import { useCallback, useState, useEffect, useRef } from 'react';
import useTheme from '@/hooks/useTheme';
import styles from './MainLayout.module.css';
import { logout } from '@/services';
import useAlertsRealtime from '@/hooks/useAlertsRealtime';

interface NotificationItem {
  id: string;
  type: 'danger' | 'warning' | 'success' | 'info';
  title: string;
  message: string;
  time: string;
  read: boolean;
}

export default function MainLayout() {
  const navigate = useNavigate();
  const location = useLocation();
  const { theme, toggleTheme } = useTheme();
  
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);
  const [notificationsOpen, setNotificationsOpen] = useState(false);

  const receiveNotification = useCallback((message?: unknown) => {
    if (!message) return;
    const envelope = message as { event_category?: string };
    const title = envelope.event_category === 'CAMERA_STATUS' ? 'Trạng thái camera thay đổi' : envelope.event_category === 'CONFIG_STATUS' ? 'Cấu hình runtime đã cập nhật' : 'Có cảnh báo an toàn mới';
    const type: NotificationItem['type'] = envelope.event_category === 'SAFETY_EVENT' ? 'danger' : 'info';
    setNotifications(items => [{id: crypto.randomUUID(), type, title, message: 'Dashboard đã đồng bộ dữ liệu mới từ backend.', time: new Date().toLocaleTimeString('vi-VN'), read: false}, ...items].slice(0, 20));
  }, []);
  useAlertsRealtime(receiveNotification);

  const notificationsRef = useRef<HTMLDivElement>(null);

  // Close notifications dropdown when clicking outside
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (notificationsRef.current && !notificationsRef.current.contains(event.target as Node)) {
        setNotificationsOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, []);

  // Determine current page title
  const getPageTitle = (pathname: string) => {
    switch (pathname) {
      case '/':
        return 'Dashboard Overview';
      case '/cameras':
        return 'CCTV Camera Management';
      case '/models':
        return 'AI Model Configuration';
      case '/violations':
        return 'Safety Violations Log';
      case '/settings':
        return 'System Settings';
      case '/help':
        return 'Help & Documentation';
      default:
        return 'VisionGuard AI';
    }
  };

  return (
    <div className={styles.container}>
      {/* Top Header Navbar */}
      <header className={styles.header}>
        <div className={styles.headerLeft}>
          <div className={styles.breadcrumbs}>
            <span className={styles.breadcrumbParent}>Console</span>
            <span className={styles.breadcrumbSeparator}>/</span>
            <h2 className={styles.headerTitle}>{getPageTitle(location.pathname)}</h2>
          </div>
        </div>
        
        <div className={styles.headerRight}>
          {/* Theme Toggle */}
          <button 
            className={styles.iconBtn} 
            onClick={toggleTheme} 
            title={theme === 'light' ? 'Chuyển sang chế độ tối' : 'Chuyển sang chế độ sáng'}
            aria-label="Toggle Theme"
          >
            <span className="material-symbols-outlined">
              {theme === 'light' ? 'dark_mode' : 'light_mode'}
            </span>
          </button>
          
          {/* Notifications */}
          <div className={styles.notificationsWrapper} ref={notificationsRef}>
            <button 
              className={`${styles.iconBtn} ${notificationsOpen ? styles.iconBtnActive : ''}`} 
              aria-label="Notifications"
              onClick={() => setNotificationsOpen(!notificationsOpen)}
            >
              <span className="material-symbols-outlined">notifications</span>
              {notifications.some(n => !n.read) && (
                <span className={styles.notificationDot}></span>
              )}
            </button>
            
            {notificationsOpen && (
              <div className={styles.notificationDropdown}>
                <div className={styles.dropdownHeader}>
                  <h3>Thông báo quan trọng</h3>
                  {notifications.some(n => !n.read) && (
                    <button 
                      className={styles.markReadBtn}
                      onClick={() => setNotifications(notifications.map(n => ({ ...n, read: true })))}
                    >
                      Đánh dấu đã đọc
                    </button>
                  )}
                </div>
                <div className={styles.dropdownList}>
                  {notifications.length === 0 ? (
                    <div className={styles.emptyState}>Không có thông báo nào</div>
                  ) : (
                    notifications.map(n => (
                      <div 
                        key={n.id} 
                        className={`${styles.notificationItem} ${n.read ? styles.notificationItemRead : ''}`}
                        onClick={() => {
                          setNotifications(notifications.map(item => item.id === n.id ? { ...item, read: true } : item));
                        }}
                      >
                        <div className={`${styles.statusIndicator} ${styles[n.type]}`}></div>
                        <div className={styles.itemContent}>
                          <div className={styles.itemTitleRow}>
                            <span className={styles.itemTitle}>{n.title}</span>
                            <span className={styles.itemTime}>{n.time}</span>
                          </div>
                          <p className={styles.itemMessage}>{n.message}</p>
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </div>
            )}
          </div>
          
          {/* Profile */}
          <button className={styles.profileBtn} aria-label="Profile" onClick={() => navigate('/settings')}>
            <div className={styles.avatar}>
              <span>AD</span>
            </div>
          </button>
        </div>
      </header>

      {/* Side Navigation Bar */}
      <nav className={styles.sidebar}>
        <div className={styles.sidebarHeader}>
          <Link to="/" style={{ textDecoration: 'none' }}>
            <h1 className={styles.logoText}>VisionGuard AI</h1>
          </Link>
          <p className={styles.logoSubText}>Safety monitoring console</p>
        </div>

        <ul className={styles.navLinksList}>
          <li>
            <NavLink 
              to="/" 
              className={({ isActive }) => `${styles.navItem} ${isActive ? styles.navItemActive : ''}`}
            >
              <span className="material-symbols-outlined">dashboard</span>
              <span>Dashboard</span>
            </NavLink>
          </li>
          <li>
            <NavLink 
              to="/cameras" 
              className={({ isActive }) => `${styles.navItem} ${isActive ? styles.navItemActive : ''}`}
            >
              <span className="material-symbols-outlined">videocam</span>
              <span>Cameras</span>
            </NavLink>
          </li>

          <li>
            <NavLink 
              to="/violations" 
              className={({ isActive }) => `${styles.navItem} ${isActive ? styles.navItemActive : ''}`}
            >
              <span className="material-symbols-outlined">warning</span>
              <span>Violations</span>
            </NavLink>
          </li>
          <li>
            <NavLink 
              to="/settings" 
              className={({ isActive }) => `${styles.navItem} ${isActive ? styles.navItemActive : ''}`}
            >
              <span className="material-symbols-outlined">settings</span>
              <span>Settings</span>
            </NavLink>
          </li>
        </ul>

        {/* Sidebar Footer Link list */}
        <div className={styles.sidebarFooter}>
          <NavLink to="/help" className={styles.sidebarFooterItem}>
            <span className="material-symbols-outlined">help</span>
            <span>Help Center</span>
          </NavLink>
          <Link to="/login" className={styles.sidebarFooterItem} onClick={logout}>
            <span className="material-symbols-outlined">logout</span>
            <span>Logout</span>
          </Link>
        </div>
      </nav>

      {/* Main Content Pane */}
      <main className={styles.main}>
        <div className={styles.contentWrapper}>
          <Outlet />
        </div>
      </main>

      {/* Mobile Bottom Nav */}
      <nav className={styles.mobileNav}>
        <NavLink to="/" className={({ isActive }) => `${styles.mobileNavItem} ${isActive ? styles.mobileNavItemActive : ''}`}>
          <span className="material-symbols-outlined">dashboard</span>
          <span>Dashboard</span>
        </NavLink>
        <NavLink to="/cameras" className={({ isActive }) => `${styles.mobileNavItem} ${isActive ? styles.mobileNavItemActive : ''}`}>
          <span className="material-symbols-outlined">videocam</span>
          <span>Cameras</span>
        </NavLink>
        <NavLink to="/violations" className={({ isActive }) => `${styles.mobileNavItem} ${isActive ? styles.mobileNavItemActive : ''}`}>
          <span className="material-symbols-outlined">warning</span>
          <span>Violations</span>
        </NavLink>
        <NavLink to="/settings" className={({ isActive }) => `${styles.mobileNavItem} ${isActive ? styles.mobileNavItemActive : ''}`}>
          <span className="material-symbols-outlined">settings</span>
          <span>Settings</span>
        </NavLink>
      </nav>
    </div>
  );
}
