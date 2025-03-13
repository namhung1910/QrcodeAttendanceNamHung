import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from PIL import Image, ImageTk
import qrcode
import base64
from io import BytesIO
from pymongo import MongoClient
from bson.objectid import ObjectId
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders
from datetime import datetime, timedelta
from flask import Flask, request, redirect, render_template
import threading
from uuid import uuid4
import socket  # sử dụng cho chức năng lấy địa chỉ IP
import csv
import time

# ---------------------------
# PHẦN THÔNG BÁO LED & BUZZER (IOT)
# ---------------------------
LED_SERVICE_HOST = "localhost"
LED_SERVICE_PORT = 6000

def send_command_to_led_service(cmd):
    try:
        with socket.create_connection((LED_SERVICE_HOST, LED_SERVICE_PORT), timeout=10) as sock:
            sock.sendall((cmd+"\n").encode('utf-8'))
            response = sock.recv(1024).decode('utf-8').strip()
            # Có thể in response nếu cần debug
    except Exception as e:
        print("Lỗi khi gửi lệnh", cmd, e)

def led_green_notification(duration):
    send_command_to_led_service("GREEN_ON")
    time.sleep(duration)
    send_command_to_led_service("GREEN_OFF")

def led_red_notification(duration):
    send_command_to_led_service("RED_ON")
    time.sleep(duration)
    send_command_to_led_service("RED_OFF")

def buzzer_notification(duration):
    send_command_to_led_service("BUZZER_ON")
    time.sleep(duration)
    send_command_to_led_service("BUZZER_OFF")

# ---------------------------
# CHỨC NĂNG PHÁT ÂM THÔNG BÁO (TTS qua máy tính)
# ---------------------------
from gtts import gTTS
import pygame

def speak_late(student_name):
    """Phát ra thông báo: 'Sinh viên [tên] điểm danh muộn' qua loa máy tính."""
    text = f"Sinh viên {student_name} điểm danh muộn"
    try:
        tts = gTTS(text=text, lang='vi')
        fp = BytesIO()
        tts.write_to_fp(fp)
        fp.seek(0)
        if not pygame.mixer.get_init():
            pygame.mixer.init()
        pygame.mixer.music.load(fp, "mp3")
        pygame.mixer.music.play()
        # Chờ đến khi âm thanh phát xong
        while pygame.mixer.music.get_busy():
            time.sleep(0.1)
    except Exception as e:
        print("Lỗi khi phát thông báo:", e)

# ---------------------------
# HÀM LẤY ĐỊA CHỈ IP CỦA MÁY CHỦ
# ---------------------------
def get_host_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip

# ---------------------------
# CẤU HÌNH & KẾT NỐI DATABASE
# ---------------------------
client = MongoClient("mongodb://localhost:27017/")
db = client.AttendanceDB
students_collection = db.students
attendance_collection = db.attendance
sessions_collection = db.sessions

# ---------------------------
# KHỞI TẠO FLASK SERVER
# ---------------------------
app = Flask(__name__)

@app.route('/checkin/<student_id>')
def handle_checkin(student_id):
    token = request.args.get('token')
    student = students_collection.find_one({
        "student_id": student_id,
        "qr.token": token
    })
    if not student:
        return "Liên kết điểm danh không hợp lệ hoặc đã hết hạn!", 400
    
    qr_created = student['qr']['created_at']
    if datetime.now() - qr_created > timedelta(minutes=100):
        return "Mã QR đã hết hiệu lực!", 400

    session_id = student["qr"].get("session_id")
    if not session_id:
        return "Thông tin phiên không hợp lệ!", 400

    existing = attendance_collection.find_one({
        "student_id": student.get("student_id"),
        "session_id": session_id
    })
    if existing:
        return "Bạn đã điểm danh trước đó rồi!", 200

    checkin_time = datetime.now()
    attendance_doc = {
        "student_id": student.get("student_id"),
        "name": student.get("name"),
        "class": student.get("class"),
        "email": student.get("email"),
        "check_in_time": checkin_time,
        "date": checkin_time.strftime("%Y-%m-%d"),
        "month": checkin_time.month,
        "year": checkin_time.year,
        "session_id": session_id
    }
    attendance_collection.insert_one(attendance_doc)
    
    # Tính khoảng cách thời gian giữa thời điểm tạo QR và điểm danh
    delta_minutes = (checkin_time - student['qr']['created_at']).total_seconds() / 60
    if delta_minutes <= 2:
         # Điểm danh kịp thời: bật LED xanh trong 2 giây
         threading.Thread(target=led_green_notification, args=(2,), daemon=True).start()
    else:
         # Điểm danh trễ: bật LED đỏ, kích hoạt còi và phát thông báo qua loa máy tính
         threading.Thread(target=led_red_notification, args=(2,), daemon=True).start()
         threading.Thread(target=buzzer_notification, args=(2,), daemon=True).start()
         threading.Thread(target=speak_late, args=(student['name'],), daemon=True).start()
    
    return redirect("/checkin-success")

@app.route('/checkin-success')
def checkin_success():
    return render_template("checkin_success.html")

def run_flask():
    app.run(host='0.0.0.0', port=5000, debug=False)

flask_thread = threading.Thread(target=run_flask, daemon=True)
flask_thread.start()

# ---------------------------
# HÀM TẠO QR CODE
# ---------------------------
def generate_qr(data):
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=4,
        border=2,
    )
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    img_bytes = buffer.getvalue()
    img_b64 = base64.b64encode(img_bytes).decode("utf-8")
    return img_b64

# ---------------------------
# HÀM GỬI EMAIL
# ---------------------------
def send_email(receiver_email, subject, body, attachment_base64, attachment_name="qr.png"):
    sender_email = "testnamhung@gmail.com"
    sender_password = "utie gvgb hsfc khbx"
    smtp_server = "smtp.gmail.com"
    smtp_port = 587

    msg = MIMEMultipart()
    msg['From'] = sender_email
    msg['To'] = receiver_email
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))

    attachment = MIMEBase('application', 'octet-stream')
    attachment_data = base64.b64decode(attachment_base64)
    attachment.set_payload(attachment_data)
    encoders.encode_base64(attachment)
    attachment.add_header('Content-Disposition', f'attachment; filename="{attachment_name}"')
    msg.attach(attachment)

    try:
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(sender_email, sender_password)
        server.send_message(msg)
        server.quit()
    except Exception as e:
        print("Lỗi gửi email:", e)

# ---------------------------
# CHỨC NĂNG QUẢN LÝ SINH VIÊN
# ---------------------------
def add_student():
    student_id = entry_student_id.get().strip()
    name = entry_name.get().strip()
    class_name = entry_class.get().strip()
    email = entry_email.get().strip()
    if not (student_id and name and class_name and email):
        messagebox.showwarning("Thiếu thông tin", "Vui lòng nhập đầy đủ thông tin!")
        return
    if students_collection.find_one({"student_id": student_id}):
        messagebox.showwarning("Trùng mã", "Mã sinh viên đã tồn tại!")
        return
    doc = {
        "student_id": student_id,
        "name": name,
        "class": class_name,
        "email": email,
        "qr": {
            "data": None,
            "created_at": None,
            "token": None,
            "session_id": None
        }
    }
    students_collection.insert_one(doc)
    messagebox.showinfo("Thành công", "Đã thêm sinh viên thành công!")
    clear_entries()
    update_student_list()

def update_student_list():
    for row in tree.get_children():
        tree.delete(row)
    for student in students_collection.find():
        last_checkin = ""
        current_session = student.get("qr", {}).get("session_id")
        if current_session:
            latest_record = attendance_collection.find_one({
                "student_id": student.get("student_id"),
                "session_id": current_session
            }, sort=[("check_in_time", -1)])
            if latest_record and latest_record.get("check_in_time"):
                last_checkin = latest_record.get("check_in_time").strftime("%Y-%m-%d %H:%M:%S")
        tree.insert("", "end", iid=str(student["_id"]), values=(
            student.get("student_id", ""),
            student.get("name", ""),
            student.get("class", ""),
            student.get("email", ""),
            "Có" if student.get("qr", {}).get("data") else "Không",
            last_checkin
        ))

def clear_entries():
    entry_student_id.delete(0, tk.END)
    entry_name.delete(0, tk.END)
    entry_class.delete(0, tk.END)
    entry_email.delete(0, tk.END)

def create_qr_for_students(filter_query):
    students = list(students_collection.find(filter_query))
    if not students:
        messagebox.showwarning("Không có dữ liệu", "Không tìm thấy sinh viên nào phù hợp!")
        return
    now = datetime.now()
    session_id = str(uuid4())
    session_doc = {
        "session_id": session_id,
        "qr_created_at": now,
        "session_end": now + timedelta(minutes=100),
        "created_at": now
    }
    sessions_collection.insert_one(session_doc)
    host_ip = get_host_ip()
    base_url = f"http://{host_ip}:5000/checkin/"
    threads = []
    for student in students:
        unique_token = str(uuid4())
        qr_url = f"{base_url}{student['student_id']}?token={unique_token}"
        qr_b64 = generate_qr(qr_url)
        students_collection.update_one(
            {"_id": student["_id"]},
            {"$set": {
                "qr.data": qr_b64,
                "qr.created_at": now,
                "qr.token": unique_token,
                "qr.session_id": session_id
            }}
        )
        subject = "Mã QR điểm danh của bạn"
        body = f"""Xin chào {student['name']},

Vui lòng quét mã QR dưới đây để điểm danh vào lớp học.
Lưu ý:
- Mã QR có hiệu lực trong 100 phút (2 tiết) kể từ thời điểm gửi email.
- Nếu không điểm danh trong vòng 10 phút, bạn sẽ bị tính là muộn.
- Nếu điểm danh sau 100 phút, bạn sẽ bị tính là vắng.
- Bạn không thể quét QR nếu sử dụng Wifi khác: WIFI SINH VIEN

Liên kết điểm danh: {qr_url}"""
        t = threading.Thread(target=send_email, args=(student["email"], subject, body, qr_b64))
        t.start()
        threads.append(t)
    for t in threads:
        t.join()
    messagebox.showinfo("Thành công", "Đã tạo QR và gửi email cho sinh viên!")
    update_student_list()

def choose_class_qr():
    choose_window = tk.Toplevel(root)
    choose_window.title("Chọn lớp để tạo QR")
    choose_window.grab_set()
    classes = list(students_collection.distinct("class"))
    classes = [cls for cls in classes if cls.strip() != ""]
    options = ["Tạo và gửi cho tất cả sinh viên"] + [f"Tạo và gửi cho sinh viên lớp {cls}" for cls in classes]
    selected_option = tk.StringVar(value=options[0])
    tk.Label(choose_window, text="Chọn lớp để tạo QR:").pack(pady=10)
    for opt in options:
        tk.Radiobutton(choose_window, text=opt, variable=selected_option, value=opt).pack(anchor="w")
    def confirm_selection():
        opt = selected_option.get()
        choose_window.destroy()
        if opt == "Tạo và gửi cho tất cả sinh viên":
            filter_query = {}
        else:
            cls_name = opt.split("lớp", 1)[1].strip()
            filter_query = {"class": cls_name}
        create_qr_for_students(filter_query)
    tk.Button(choose_window, text="Xác nhận", command=confirm_selection).pack(pady=10)

def delete_old_qr():
    result = students_collection.update_many(
        {},
        {"$set": {
            "qr.data": None,
            "qr.created_at": None,
            "qr.token": None,
            "qr.session_id": None
        }}
    )
    messagebox.showinfo("Xóa QR", f"Đã xóa QR của {result.modified_count} sinh viên!")
    update_student_list()

def delete_student_action():
    selected = tree.selection()
    if not selected:
        messagebox.showwarning("Chưa chọn", "Vui lòng chọn sinh viên cần xóa!")
        return
    student_oid_str = selected[0]
    student = students_collection.find_one({"_id": ObjectId(student_oid_str)})
    if not student:
        messagebox.showerror("Lỗi", "Không tìm thấy sinh viên!")
        return
    del_window = tk.Toplevel(root)
    del_window.title("Xóa Sinh viên")
    del_window.grab_set()
    tk.Label(del_window, text="Bạn có chắc muốn xóa sinh viên dưới đây không?").pack(pady=10)
    info = f"Mã: {student.get('student_id','')}\nTên: {student.get('name','')}\nLớp: {student.get('class','')}\nEmail: {student.get('email','')}"
    tk.Label(del_window, text=info, justify="left").pack(pady=10)
    def confirm_delete():
        students_collection.delete_one({"_id": ObjectId(student_oid_str)})
        update_student_list()
        messagebox.showinfo("Thành công", "Xóa sinh viên thành công!")
        del_window.destroy()
    btn_frame = tk.Frame(del_window)
    btn_frame.pack(pady=10)
    btn_cancel = tk.Button(btn_frame, text="Hủy", width=15, command=del_window.destroy)
    btn_cancel.pack(side="left", padx=5)
    btn_confirm = tk.Button(btn_frame, text="Xác nhận", width=15, command=confirm_delete)
    btn_confirm.pack(side="left", padx=5)

def edit_student_action():
    selected = tree.selection()
    if not selected:
        messagebox.showwarning("Chưa chọn", "Vui lòng chọn sinh viên cần sửa!")
        return
    student_oid_str = selected[0]
    student = students_collection.find_one({"_id": ObjectId(student_oid_str)})
    if not student:
        messagebox.showerror("Lỗi", "Không tìm thấy sinh viên!")
        return
    edit_window = tk.Toplevel(root)
    edit_window.title("Sửa Sinh viên")
    edit_window.grab_set()
    tk.Label(edit_window, text="Mã Sinh viên:").grid(row=0, column=0, padx=5, pady=5, sticky="e")
    lbl_id = tk.Label(edit_window, text=student.get("student_id", ""), relief="sunken", width=20)
    lbl_id.grid(row=0, column=1, padx=5, pady=5)
    tk.Label(edit_window, text="Tên Sinh viên:").grid(row=1, column=0, padx=5, pady=5, sticky="e")
    entry_new_name = tk.Entry(edit_window, width=22)
    entry_new_name.insert(0, student.get("name", ""))
    entry_new_name.grid(row=1, column=1, padx=5, pady=5)
    tk.Label(edit_window, text="Lớp:").grid(row=2, column=0, padx=5, pady=5, sticky="e")
    entry_new_class = tk.Entry(edit_window, width=22)
    entry_new_class.insert(0, student.get("class", ""))
    entry_new_class.grid(row=2, column=1, padx=5, pady=5)
    tk.Label(edit_window, text="Email:").grid(row=3, column=0, padx=5, pady=5, sticky="e")
    entry_new_email = tk.Entry(edit_window, width=22)
    entry_new_email.insert(0, student.get("email", ""))
    entry_new_email.grid(row=3, column=1, padx=5, pady=5)
    def save_changes():
        new_name = entry_new_name.get().strip()
        new_class = entry_new_class.get().strip()
        new_email = entry_new_email.get().strip()
        if not (new_name and new_class and new_email):
            messagebox.showwarning("Thiếu thông tin", "Vui lòng nhập đầy đủ thông tin!")
            return
        students_collection.update_one(
            {"_id": ObjectId(student_oid_str)},
            {"$set": {
                "name": new_name,
                "class": new_class,
                "email": new_email
            }}
        )
        update_student_list()
        messagebox.showinfo("Thành công", "Cập nhật sinh viên thành công!")
        edit_window.destroy()
    btn_save = tk.Button(edit_window, text="Lưu", width=15, command=save_changes)
    btn_save.grid(row=4, column=0, columnspan=2, pady=10)

def refresh_list():
    update_student_list()
    messagebox.showinfo("Refresh", "Đã cập nhật danh sách sinh viên!")

def import_students_csv():
    file_path = filedialog.askopenfilename(
        title="Chọn file CSV nhập danh sách sinh viên",
        filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")]
    )
    if not file_path:
        return
    count_new = 0
    count_skipped = 0
    try:
        with open(file_path, newline='', encoding="utf-8") as csvfile:
            import csv
            reader = csv.DictReader(csvfile)
            for row in reader:
                student_id = row.get("student_id", "").strip()
                name = row.get("name", "").strip()
                class_name = row.get("class", "").strip()
                email = row.get("email", "").strip()
                if not (student_id and name and class_name and email):
                    continue
                if students_collection.find_one({"student_id": student_id}):
                    count_skipped += 1
                    continue
                doc = {
                    "student_id": student_id,
                    "name": name,
                    "class": class_name,
                    "email": email,
                    "qr": {
                        "data": None,
                        "created_at": None,
                        "token": None,
                        "session_id": None
                    }
                }
                students_collection.insert_one(doc)
                count_new += 1
        messagebox.showinfo("Nhập CSV", f"Đã thêm {count_new} sinh viên mới.\nBỏ qua {count_skipped} sinh viên đã tồn tại.")
        update_student_list()
    except Exception as e:
        messagebox.showerror("Lỗi", f"Không thể đọc file CSV.\nChi tiết: {e}")

def export_students_csv():
    file_path = filedialog.asksaveasfilename(
        title="Xuất danh sách sinh viên ra CSV",
        defaultextension=".csv",
        filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")]
    )
    if not file_path:
        return
    try:
        with open(file_path, mode="w", newline='', encoding="utf-8") as csvfile:
            import csv
            fieldnames = ["student_id", "name", "class", "email"]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            for student in students_collection.find():
                writer.writerow({
                    "student_id": student.get("student_id", ""),
                    "name": student.get("name", ""),
                    "class": student.get("class", ""),
                    "email": student.get("email", "")
                })
        messagebox.showinfo("Xuất CSV", "Xuất danh sách sinh viên thành công!")
    except Exception as e:
        messagebox.showerror("Lỗi", f"Không thể xuất file CSV.\nChi tiết: {e}")

# ---------------------------
# GIAO DIỆN TKINTER
# ---------------------------
root = tk.Tk()
root.title("Hệ thống điểm danh sinh viên bằng mã QR - Tạo QR")
root.geometry("1200x600")

frame_left = tk.Frame(root, padx=10, pady=10)
frame_left.pack(side=tk.LEFT, fill=tk.Y)

lbl_title = tk.Label(frame_left, text="Quản lý Sinh viên", font=("Arial", 14, "bold"))
lbl_title.pack(pady=10)

frame_form = tk.Frame(frame_left)
frame_form.pack(pady=10)

tk.Label(frame_form, text="Mã Sinh viên:").grid(row=0, column=0, padx=5, pady=5, sticky="e")
entry_student_id = tk.Entry(frame_form)
entry_student_id.grid(row=0, column=1, padx=5, pady=5)

tk.Label(frame_form, text="Tên Sinh viên:").grid(row=1, column=0, padx=5, pady=5, sticky="e")
entry_name = tk.Entry(frame_form)
entry_name.grid(row=1, column=1, padx=5, pady=5)

tk.Label(frame_form, text="Lớp:").grid(row=2, column=0, padx=5, pady=5, sticky="e")
entry_class = tk.Entry(frame_form)
entry_class.grid(row=2, column=1, padx=5, pady=5)

tk.Label(frame_form, text="Email:").grid(row=3, column=0, padx=5, pady=5, sticky="e")
entry_email = tk.Entry(frame_form)
entry_email.grid(row=3, column=1, padx=5, pady=5)

frame_buttons = tk.Frame(frame_left)
frame_buttons.pack(pady=10)

btn_add_student = tk.Button(frame_buttons, text="Thêm Sinh viên", width=20, command=add_student)
btn_add_student.grid(row=0, column=0, padx=5, pady=5)

btn_create_qr = tk.Button(frame_buttons, text="Chọn lớp để tạo qr", width=20, command=choose_class_qr)
btn_create_qr.grid(row=1, column=0, padx=5, pady=5)

btn_clear_qr = tk.Button(frame_buttons, text="Xóa tất cả QR", width=20, command=delete_old_qr)
btn_clear_qr.grid(row=2, column=0, padx=5, pady=5)

btn_edit_student = tk.Button(frame_buttons, text="Sửa Sinh viên", width=20, command=edit_student_action)
btn_edit_student.grid(row=3, column=0, padx=5, pady=5)

btn_delete_student = tk.Button(frame_buttons, text="Xóa Sinh viên", width=20, command=delete_student_action)
btn_delete_student.grid(row=4, column=0, padx=5, pady=5)

btn_refresh = tk.Button(frame_buttons, text="Refresh", width=20, command=refresh_list)
btn_refresh.grid(row=5, column=0, padx=5, pady=5)

btn_import_csv = tk.Button(frame_buttons, text="Nhập từ CSV", width=20, command=import_students_csv)
btn_import_csv.grid(row=6, column=0, padx=5, pady=5)

btn_export_csv = tk.Button(frame_buttons, text="Xuất ra CSV", width=20, command=export_students_csv)
btn_export_csv.grid(row=7, column=0, padx=5, pady=5)

tree = ttk.Treeview(root, columns=("ID", "Tên", "Lớp", "Email", "QR", "Điểm danh lần cuối"), show="headings")
tree.pack(fill=tk.BOTH, expand=True)

tree.heading("ID", text="Mã Sinh viên")
tree.heading("Tên", text="Tên Sinh viên")
tree.heading("Lớp", text="Lớp")
tree.heading("Email", text="Email")
tree.heading("QR", text="Có QR?")
tree.heading("Điểm danh lần cuối", text="Điểm danh lần cuối")

tree.column("ID", width=100)
tree.column("Tên", width=150)
tree.column("Lớp", width=100)
tree.column("Email", width=200)
tree.column("QR", width=80)
tree.column("Điểm danh lần cuối", width=150)

update_student_list()

root.mainloop()
