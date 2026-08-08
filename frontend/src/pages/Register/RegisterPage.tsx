import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import styles from './RegisterPage.module.css';
import { ApiError, register } from '@/services';

export default function RegisterPage() {
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    if (password !== confirmPassword) {
      setError('Mật khẩu xác nhận không khớp.');
      return;
    }

    setSubmitting(true);
    try {
      await register(email, password);
      navigate('/login', { replace: true });
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : 'Không thể kết nối máy chủ.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <>
      {/* Registration Header */}
      <div className={styles.header}>
        <h1 className={styles.title}>VisionGuard AI</h1>
        <p className={styles.subtitle}>Tạo tài khoản mới</p>
      </div>

      {/* Register Form */}
      <form className={styles.form} onSubmit={handleSubmit}>
        {/* Work Email */}
        <div className="input-group">
          <label className="input-label" htmlFor="email">Gmail</label>
          <div className="input-wrapper">
            <span className="material-symbols-outlined input-icon">mail</span>
            <input
              type="email"
              id="email"
              className="input-field"
              placeholder="name@gmail.com"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>
        </div>

        {/* Password */}
        <div className="input-group">
          <label className="input-label" htmlFor="password">Mật khẩu</label>
          <div className="input-wrapper">
            <span className="material-symbols-outlined input-icon">lock</span>
            <input
              type="password"
              id="password"
              className="input-field"
              placeholder="••••••••"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
        </div>

        {/* Confirm Password */}
        <div className="input-group">
          <label className="input-label" htmlFor="confirmPassword">Xác nhận Mật khẩu</label>
          <div className="input-wrapper">
            <span className="material-symbols-outlined input-icon">lock</span>
            <input
              type="password"
              id="confirmPassword"
              className="input-field"
              placeholder="••••••••"
              required
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
            />
          </div>
        </div>

        {/* Submit Button */}
        {error && <p role="alert" style={{ color: 'var(--danger-color, #dc2626)', margin: 0 }}>{error}</p>}
        <button type="submit" disabled={submitting} className="btn btn-primary styles.submitBtn" style={{ width: '100%' }}>
          {submitting ? 'Đang tạo...' : 'Tạo tài khoản'}
        </button>
      </form>

      {/* Footer Link */}
      <div className={styles.footer}>
        Đã có tài khoản?{' '}
        <Link to="/login" className={styles.loginLink}>
          Đăng nhập thay thế
        </Link>
      </div>
    </>
  );
}
