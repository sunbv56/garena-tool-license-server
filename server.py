# server.py (phiên bản có thời hạn)
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
    # Thêm cột expires_at, nullable=True nghĩa là key có thể không có ngày hết hạn (vĩnh viễn)
    expires_at = db.Column(db.DateTime, nullable=True, default=None)
    status = db.Column(db.String(20), nullable=False, default='active') # active, revoked, expired
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    customer_info = db.Column(db.String(200), nullable=True) # Thêm thông tin khách hàng nếu cần

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

    # === LOGIC KIỂM TRA MỚI ===
    # 1. Kiểm tra trạng thái (ví dụ: bị thu hồi thủ công)
    if license_record.status == 'revoked':
        return jsonify({"status": "error", "message": "Key đã bị thu hồi."}), 403
    
    # 2. Kiểm tra nếu key đã hết hạn và cập nhật status
    if license_record.expires_at and license_record.expires_at < current_time:
        if license_record.status != 'expired': # Chỉ cập nhật DB nếu trạng thái chưa phải là expired
            license_record.status = 'expired'
            db.session.commit()
        return jsonify({"status": "error", "message": "Key đã hết hạn sử dụng."}), 403

    # Nếu key đang ở trạng thái expired nhưng bằng cách nào đó vẫn lọt qua (ví dụ: do cache), chặn lại
    if license_record.status == 'expired':
        return jsonify({"status": "error", "message": "Key đã hết hạn sử dụng."}), 403

    # === LOGIC KÍCH HOẠT VÀ XÁC THỰC HWID (giữ nguyên) ===
    if license_record.hwid is None:
        license_record.hwid = hwid_from_client
        db.session.commit()
        # Trả về thông tin ngày hết hạn cho client nếu có
        expires_msg = f"Hạn sử dụng đến: {license_record.expires_at.strftime('%Y-%m-%d %H:%M')}" if license_record.expires_at else "Bản quyền vĩnh viễn."
        return jsonify({"status": "success", "message": f"Kích hoạt thành công. {expires_msg}"}), 200

    if license_record.hwid == hwid_from_client:
        return jsonify({"status": "success", "message": "Xác thực thành công."}), 200
    else:
        return jsonify({"status": "error", "message": "Key đã được sử dụng trên máy khác."}), 403

# Endpoint để kiểm tra server có hoạt động không
@app.route('/')
def index():
    return "License Server (v2 with Expiry) is running."

# --- Cron Job (Tùy chọn, để dọn dẹp database) ---
# Đây là một endpoint bí mật mà bạn có thể dùng dịch vụ cron job để gọi định kỳ
# Ví dụ: https://cron-job.org/
@app.route('/admin/cleanup_expired_keys/<secret_key>', methods=['POST'])
def cleanup_keys(secret_key):
    # Thay 'YOUR_SUPER_SECRET_KEY' bằng một chuỗi ngẫu nhiên, dài
    if secret_key != os.environ.get('CRON_SECRET_KEY', 'YOUR_SUPER_SECRET_KEY'):
        return "Unauthorized", 401

    # Xóa các key đã hết hạn hơn 180 ngày
    six_months_ago = datetime.utcnow() - timedelta(days=180)
    keys_to_delete = License.query.filter(License.status == 'expired', License.expires_at < six_months_ago).all()
    
    count = len(keys_to_delete)
    if count > 0:
        for key in keys_to_delete:
            db.session.delete(key)
        db.session.commit()

    return jsonify({"status": "success", "message": f"Đã xóa {count} key hết hạn quá 180 ngày."})


# --- Khởi tạo/Cập nhật database ---
# LƯU Ý QUAN TRỌNG: Khi bạn thêm cột mới, bạn cần migrate database.
# Với Flask-Migrate thì sẽ chuyên nghiệp hơn, nhưng cách đơn giản nhất là
# tạo lại database hoặc tự thêm cột bằng tay.
# Với SQLite, chỉ cần chạy lại là nó tự thêm.
# Với PostgreSQL trên Render, bạn cần kết nối và chạy lệnh SQL:
# ALTER TABLE license ADD COLUMN expires_at TIMESTAMP WITHOUT TIME ZONE;
# ALTER TABLE license ADD COLUMN customer_info VARCHAR(200);
with app.app_context():
    db.create_all()
