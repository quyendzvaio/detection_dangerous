import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import styles from './LoginPage.module.css';
import { ApiError, login } from '@/services';

export default function LoginPage() {
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setSubmitting(true);
    try {
      await login(email, password);
      navigate('/');
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : 'Không thể kết nối máy chủ.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <>
      {/* Brand Logo Header */}
      <div className={styles.header}>
        <span className={`material-symbols-outlined ${styles.logoIcon} icon-filled`}>
          security
        </span>
        <h1 className={styles.title}>VisionGuard AI</h1>
        <p className={styles.subtitle}>Safety Command Center</p>
      </div>

      {/* Login Form */}
      <form className={styles.form} onSubmit={handleSubmit}>
        {/* Email Field */}
        <div className="input-group">
          <label className="input-label" htmlFor="email">Email</label>
          <div className="input-wrapper">
            <span className="material-symbols-outlined input-icon">mail</span>
            <input
              type="email"
              id="email"
              className="input-field"
              placeholder="Nhập địa chỉ email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>
        </div>

        {/* Password Field */}
        <div className="input-group">
          <div className={styles.labelWrapper}><label className="input-label" htmlFor="password">Mật khẩu</label></div>
          <div className="input-wrapper">
            <span className="material-symbols-outlined input-icon">lock</span>
            <input
              type={showPassword ? 'text' : 'password'}
              id="password"
              className="input-field"
              placeholder="Nhập mật khẩu"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            <button
              type="button"
              className={styles.eyeBtn}
              onClick={() => setShowPassword(!showPassword)}
              aria-label={showPassword ? 'Hide password' : 'Show password'}
            >
              <span className="material-symbols-outlined text-lg">
                {showPassword ? 'visibility_off' : 'visibility'}
              </span>
            </button>
          </div>
        </div>

        {/* Submit Button */}
        {error && <p role="alert" style={{ color: 'var(--danger-color, #dc2626)', margin: 0 }}>{error}</p>}
        <button type="submit" disabled={submitting} className="btn btn-primary styles.submitBtn" style={{ width: '100%' }}>
          {submitting ? 'Đang đăng nhập...' : 'Đăng nhập'}
          <span className="material-symbols-outlined text-sm">arrow_forward</span>
        </button>
      </form>

      {/* Register Link */}
      <div className={styles.footer}>
        Chưa có tài khoản? 
        <Link to="/register" className={styles.signupLink}>
          Tạo tài khoản
        </Link>
      </div>
    </>
  );
}
