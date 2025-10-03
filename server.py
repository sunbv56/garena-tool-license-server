# server.py
import os
import uuid
from datetime import datetime
from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy

# --- Khởi tạo ứng dụng Flask ---
app = Flask(__name__)

# --- Cấu hình Database ---
# Render sẽ cung cấp một DATABASE_URL trong biến môi trường.
# Nếu không có, ta dùng sqlite mặc định để test ở local.
db_url = os.environ.get('DATABASE_URL')
if db_url and db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1) # SQLAlchemy yêu cầu tên protocol là postgresql

app.config['SQLALCHEMY_DATABASE_URI'] = db_url or 'sqlite:///licenses.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# --- Định nghĩa Bảng trong Database ---
class License(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    license_key = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    hwid = db.Column(db.String(100), unique=False, nullable=True) # Hardware ID
    status = db.Column(db.String(20), nullable=False, default='active') # Trạng thái: active, revoked
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

    # Tìm key trong database
    license_record = License.query.filter_by(license_key=key_from_client).first()

    if not license_record:
        return jsonify({"status": "error", "message": "License key không tồn tại."}), 404

    if license_record.status != 'active':
        return jsonify({"status": "error", "message": f"Key đã bị vô hiệu hóa."}), 403

    if license_record.hwid is None:
        license_record.hwid = hwid_from_client
        db.session.commit()
        return jsonify({"status": "success", "message": "Kích hoạt thành công."}), 200

    if license_record.hwid == hwid_from_client:
        return jsonify({"status": "success", "message": "Xác thực thành công."}), 200
    else:
        return jsonify({"status": "error", "message": "Key đã được sử dụng trên máy khác."}), 403

# Endpoint để kiểm tra server có hoạt động không
@app.route('/')
def index():
    return "License Server is running."

# --- Khởi tạo database (chỉ chạy một lần) ---
with app.app_context():
    db.create_all()

# Không cần app.run() ở đây, Gunicorn sẽ xử lý việc chạy server