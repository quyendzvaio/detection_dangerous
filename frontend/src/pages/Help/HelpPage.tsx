import styles from './HelpPage.module.css';

export default function HelpPage() {
  return <div className={`${styles.card} glass-panel`}><div className={styles.title}><span className="material-symbols-outlined text-primary">help</span>Hướng dẫn sử dụng</div><div className={styles.content}>
    <section className={styles.faqItem}><h4 className={styles.question}>Thêm camera hoặc video</h4><p className={styles.answer}>Mở Cameras, chọn Thêm nguồn, nhập mã duy nhất và nguồn USB, RTSP, HTTP hoặc đường dẫn video. Pipeline phải được chạy với cùng camera ID để nguồn chuyển sang ONLINE.</p></section>
    <section className={styles.faqItem}><h4 className={styles.question}>Bật model và kiểm tra ACK</h4><p className={styles.answer}>Bật PPE, Fall hoặc Zone trên thẻ camera. PENDING nghĩa là backend đang chờ runtime; APPLIED nghĩa là runtime đã nhận cấu hình.</p></section>
    <section className={styles.faqItem}><h4 className={styles.question}>Vẽ vùng cấm</h4><p className={styles.answer}>Chọn Vẽ và quản lý zone, nhấp ít nhất ba điểm trên khung, rồi lưu. Có thể sửa polygon, bật/tắt hoặc xóa mà không restart pipeline.</p></section>
    <section className={styles.faqItem}><h4 className={styles.question}>Xem cảnh báo và evidence</h4><p className={styles.answer}>Mở Violations để lọc cảnh báo. Evidence ở trạng thái READY có thể xem bằng URL Azure ngắn hạn; PROCESSING nghĩa là video hoặc ảnh vẫn đang được xử lý.</p></section>
  </div></div>;
}
