# server.py (phiên bản cuối với dọn dẹp key không sử dụng)
import os
import uuid
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import or_

# --- Khởi tạo ứng dụng Flask ---
app = Flask(__name__)

# --- Cấu hình Database ---
db_url = os.environ.get('DATABASE_URL')
if db_url and db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url or 'sqlite:///licenses.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# --- Định nghĩa Bảng trong Database ---
class License(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    license_key = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    hwid = db.Column(db.String(100), unique=False, nullable=True)
    expires_at = db.Column(db.DateTime, nullable=True, default=None)
    customer_info = db.Column(db.String(200), nullable=True)
    status = db.Column(db.String(20), nullable=False, default='active')
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return f'<License {self.license_key}>'

# --- API Endpoint để xác thực ---
@app.route('/validate', methods=['POST'])
def validate_license():
    data = request.get_json()
    if not data or 'license_key' not in data or 'hwid' not in data:
        return jsonify({"status": "error", "message": "Dữ liệu không hợp lệ."}), 400

    key_from_client = data['license_key']
    hwid_from_client = data['hwid']
    
    current_time = datetime.utcnow()

    license_record = License.query.filter_by(license_key=key_from_client).first()

    if not license_record:
        return jsonify({"status": "error", "message": "License key không tồn tại."}), 404

    if license_record.status == 'revoked':
        return jsonify({"status": "error", "message": "Key đã bị thu hồi."}), 403
    
    if license_record.expires_at and license_record.expires_at < current_time:
        if license_record.status != 'expired':
            license_record.status = 'expired'
            db.session.commit()
        return jsonify({"status": "error", "message": "Key đã hết hạn sử dụng."}), 403

    if license_record.status == 'expired':
        return jsonify({"status": "error", "message": "Key đã hết hạn sử dụng."}), 403

    if license_record.hwid is None:
        license_record.hwid = hwid_from_client
        db.session.commit()
        expires_msg = f"Hạn sử dụng đến: {license_record.expires_at.strftime('%Y-%m-%d %H:%M')}" if license_record.expires_at else "Bản quyền vĩnh viễn."
        return jsonify({"status": "success", "message": f"Kích hoạt thành công. {expires_msg}"}), 200

    if license_record.hwid == hwid_from_client:
        return jsonify({"status": "success", "message": "Xác thực thành công."}), 200
    else:
        return jsonify({"status": "error", "message": "Key đã được sử dụng trên máy khác."}), 403

# Endpoint để kiểm tra server có hoạt động không
@app.route('/')
def index():
    return "License Server (v3 with Full Cleanup) is running."

# ===================================================================
# == CẬP NHẬT ENDPOINT DỌN DẸP DATABASE ==
# ===================================================================
@app.route('/admin/cleanup_tasks/<secret_key>', methods=['POST'])
def cleanup_tasks(secret_key):
    # Xác thực request
    # Thay 'YOUR_SUPER_SECRET_KEY' bằng biến môi trường để an toàn hơn
    cron_secret = os.environ.get('CRON_SECRET_KEY', 'YOUR_SUPER_SECRET_KEY')
    if secret_key != cron_secret:
        return "Unauthorized", 401

    # Khởi tạo bộ đếm cho báo cáo
    expired_deleted_count = 0
    unused_deleted_count = 0

    # === NHIỆM VỤ 1: Xóa các key đã hết hạn quá 180 ngày ===
    six_months_ago = datetime.utcnow() - timedelta(days=180)
    expired_keys_to_delete = License.query.filter(
        License.status == 'expired', 
        License.expires_at < six_months_ago
    ).all()
    
    expired_deleted_count = len(expired_keys_to_delete)
    if expired_deleted_count > 0:
        for key in expired_keys_to_delete:
            db.session.delete(key)

    # === NHIỆM VỤ 2 (MỚI): Xóa các key không sử dụng (chưa kích hoạt) quá 7 ngày ===
    seven_days_ago = datetime.utcnow() - timedelta(days=7)
    unused_keys_to_delete = License.query.filter(
        License.hwid == None,  # Điều kiện: chưa được kích hoạt
        License.created_at < seven_days_ago  # Điều kiện: đã tạo hơn 7 ngày trước
    ).all()

    unused_deleted_count = len(unused_keys_to_delete)
    if unused_deleted_count > 0:
        for key in unused_keys_to_delete:
            db.session.delete(key)

    # Chỉ commit vào database nếu có sự thay đổi
    if expired_deleted_count > 0 or unused_deleted_count > 0:
        db.session.commit()

    # Tạo thông báo kết quả
    message = (
        f"Dọn dẹp hoàn tất. "
        f"Đã xóa {expired_deleted_count} key hết hạn. "
        f"Đã xóa {unused_deleted_count} key chưa sử dụng."
    )
    
    print(f"Cron Job: {message}") # Ghi log trên server để bạn theo dõi
    return jsonify({"status": "success", "message": message})


# --- Khởi tạo/Cập nhật database ---
with app.app_context():
    db.create_all()
