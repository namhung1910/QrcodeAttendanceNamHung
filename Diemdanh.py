#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from datetime import datetime, timedelta
from pymongo import MongoClient
import csv
from tkcalendar import DateEntry

# ---------------------------
# KẾT NỐI DATABASE
# ---------------------------
client = MongoClient("mongodb://localhost:27017/")
db = client.AttendanceDB  # Sử dụng database AttendanceDB_New
attendance_collection = db.attendance
students_collection = db.students      # Dữ liệu sinh viên (và QR trong mỗi sinh viên)
sessions_collection = db.sessions        # Lưu các phiên điểm danh (session)

# ---------------------------
# HÀM XỬ LÝ BỘ LỌC VÀ EXPORT CSV
# ---------------------------
def clear_filters():
    date_start.set_date(datetime.now() - timedelta(days=7))
    date_end.set_date(datetime.now())
    combo_class.set("Tất cả")
    combo_mode.set("Điểm danh")
    load_data()

def load_class_options():
    classes = students_collection.distinct("class")
    classes.sort()
    return ["Tất cả"] + classes

def export_csv():
    file_path = filedialog.asksaveasfilename(defaultextension=".csv",
                                             filetypes=[("CSV files", "*.csv")],
                                             title="Lưu file CSV")
    if not file_path:
        return
    rows = []
    header = ["Mã Sinh viên", "Tên", "Lớp", "Email", "Thời gian", "Số tiết vắng"]
    rows.append(header)
    for child in tree.get_children():
        row = tree.item(child)["values"]
        rows.append(row)
    try:
        with open(file_path, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerows(rows)
        messagebox.showinfo("Thành công", f"Xuất dữ liệu thành công ra file:\n{file_path}")
    except Exception as e:
        messagebox.showerror("Lỗi", f"Không thể xuất file CSV:\n{e}")

# ---------------------------
# HÀM LOAD DỮ LIỆU VÀ HIỂN THỊ
# ---------------------------
def load_data():
    tree.delete(*tree.get_children())
    mode = combo_mode.get()  # Các chế độ: "Điểm danh", "Vắng mặt", "Muộn 1 tiết", "Muộn 2 tiết"

    # Lấy khoảng thời gian lọc (dựa trên thời gian tạo phiên QR: qr_created_at)
    try:
        start_date = datetime.strptime(date_start.get(), "%Y-%m-%d")
        end_date = datetime.strptime(date_end.get(), "%Y-%m-%d")
        start_datetime = datetime.combine(start_date.date(), datetime.min.time())
        end_datetime = datetime.combine(end_date.date(), datetime.max.time())
    except Exception as e:
        messagebox.showerror("Lỗi định dạng", f"Định dạng khoảng thời gian không đúng: {e}")
        return

    class_filter = combo_class.get().strip()

    # --- Bước 1: Query các phiên (sessions) trong khoảng lọc ---
    session_query = {"qr_created_at": {"$gte": start_datetime, "$lte": end_datetime}}
    sessions = list(sessions_collection.find(session_query).sort("qr_created_at", 1))
    session_ids = [session["session_id"] for session in sessions]
    # Tạo dictionary để tra cứu nhanh thông tin phiên theo session_id
    session_dict = { session["session_id"]: session for session in sessions }

    # --- Bước 2: Với mỗi phiên đã kết thúc, chốt phiên bằng cách tạo bản ghi vắng nếu sinh viên chưa điểm danh ---
    now = datetime.now()
    student_query = {}
    if class_filter and class_filter != "Tất cả":
        student_query["class"] = class_filter
    all_students = list(students_collection.find(student_query))
    for session in sessions:
        session_id = session["session_id"]
        # Xác định thời gian kết thúc phiên: nếu có session_end thì dùng, nếu không thì qr_created_at + 100 phút
        session_end = session.get("session_end", session["qr_created_at"] + timedelta(minutes=100))
        if now < session_end:
            continue  # Phiên chưa kết thúc, không chốt
        for student in all_students:
            # Kiểm tra xem đã có bản ghi điểm danh của sinh viên cho phiên này chưa
            rec = attendance_collection.find_one({
                "student_id": student["student_id"],
                "session_id": session_id
            })
            if not rec:
                absent_record = {
                    "student_id": student["student_id"],
                    "name": student["name"],
                    "class": student["class"],
                    "email": student["email"],
                    "check_in_time": session_end,  # Ghi nhận thời điểm kết thúc phiên
                    "date": session["qr_created_at"].strftime("%Y-%m-%d"),
                    "session_id": session_id,
                    "sotiet": 4,      # 4 tiết → vắng
                    "status": "Vắng"
                }
                attendance_collection.insert_one(absent_record)

    # --- Bước 3: Query toàn bộ bản ghi điểm danh (theo session_id) trong khoảng lọc ---
    attendance_query = {"session_id": {"$in": session_ids}}
    if class_filter and class_filter != "Tất cả":
        attendance_query["class"] = class_filter
    records = list(attendance_collection.find(attendance_query).sort("check_in_time", -1))

    # --- Bước 4: Với từng bản ghi, nếu là điểm danh (status khác "Vắng") thì tính số tiết dựa vào delta thời gian ---
    for rec in records:
        # Lấy thông tin phiên từ session_dict
        sess = session_dict.get(rec.get("session_id"))
        if sess and rec.get("check_in_time") and sess.get("qr_created_at"):
            delta = (rec["check_in_time"] - sess["qr_created_at"]).total_seconds() / 60
            if rec.get("status", "Điểm danh") == "Vắng":
                sotiet = 4
            else:
                if delta <= 10:
                    sotiet = 0
                elif delta <= 55:
                    sotiet = 1
                elif delta <= 100:
                    sotiet = 2
                else:
                    sotiet = 4
        else:
            sotiet = rec.get("sotiet", 0)

        # --- Bổ sung: Ở chế độ "Điểm danh", chỉ hiển thị các bản ghi có số tiết vắng khác 4 ---
        if mode == "Điểm danh" and sotiet == 4:
            continue

        # Áp dụng bộ lọc theo chế độ xem
        if mode == "Muộn 1 tiết" and sotiet != 1:
            continue
        if mode == "Muộn 2 tiết" and sotiet != 2:
            continue
        if mode == "Vắng mặt" and rec.get("status", "Điểm danh") != "Vắng":
            continue

        time_str = rec["check_in_time"].strftime("%Y-%m-%d %H:%M:%S") if isinstance(rec["check_in_time"], datetime) else str(rec["check_in_time"])
        tree.insert("", "end", values=(
            rec.get("student_id", ""),
            rec.get("name", ""),
            rec.get("class", ""),
            rec.get("email", ""),
            time_str,
            sotiet
        ))

# ---------------------------
# GIAO DIỆN TKINTER
# ---------------------------
root = tk.Tk()
root.title("Hệ thống điểm danh sinh viên bằng mã QR - Lịch sử điểm danh")
root.geometry("1200x600")

frame_filter = tk.Frame(root, padx=10, pady=10)
frame_filter.pack(side=tk.TOP, fill=tk.X)

tk.Label(frame_filter, text="Chế độ:").grid(row=0, column=0, padx=5, pady=5, sticky="e")
combo_mode = ttk.Combobox(frame_filter, values=["Điểm danh", "Vắng mặt", "Muộn 1 tiết", "Muộn 2 tiết"], width=12)
combo_mode.grid(row=0, column=1, padx=5, pady=5)
combo_mode.set("Điểm danh")

tk.Label(frame_filter, text="Từ ngày:").grid(row=0, column=2, padx=5, pady=5, sticky="e")
date_start = DateEntry(frame_filter, width=12, date_pattern="yyyy-mm-dd")
date_start.grid(row=0, column=3, padx=5, pady=5)
tk.Label(frame_filter, text="Đến ngày:").grid(row=0, column=4, padx=5, pady=5, sticky="e")
date_end = DateEntry(frame_filter, width=12, date_pattern="yyyy-mm-dd")
date_end.grid(row=0, column=5, padx=5, pady=5)
date_start.set_date(datetime.now() - timedelta(days=7))
date_end.set_date(datetime.now())

tk.Label(frame_filter, text="Lớp:").grid(row=0, column=6, padx=5, pady=5, sticky="e")
combo_class = ttk.Combobox(frame_filter, values=load_class_options(), width=10)
combo_class.grid(row=0, column=7, padx=5, pady=5)
combo_class.set("Tất cả")

btn_search = tk.Button(frame_filter, text="Tìm kiếm", command=load_data)
btn_search.grid(row=0, column=8, padx=10, pady=5)
btn_clear = tk.Button(frame_filter, text="Xóa bộ lọc", command=clear_filters)
btn_clear.grid(row=0, column=9, padx=10, pady=5)
btn_export = tk.Button(frame_filter, text="Xuất CSV", command=export_csv)
btn_export.grid(row=0, column=10, padx=10, pady=5)

frame_result = tk.Frame(root, padx=10, pady=10)
frame_result.pack(fill=tk.BOTH, expand=True)

columns = ("student_id", "name", "class", "email", "time", "sotiet")
tree = ttk.Treeview(frame_result, columns=columns, show="headings")
tree.heading("student_id", text="Mã Sinh viên")
tree.heading("name", text="Tên")
tree.heading("class", text="Lớp")
tree.heading("email", text="Email")
tree.heading("time", text="Thời gian")
tree.heading("sotiet", text="Số tiết vắng")
tree.column("student_id", width=100)
tree.column("name", width=150)
tree.column("class", width=100)
tree.column("email", width=200)
tree.column("time", width=150)
tree.column("sotiet", width=100)
tree.pack(fill=tk.BOTH, expand=True)

btn_refresh = tk.Button(root, text="Refresh", command=load_data)
btn_refresh.pack(pady=5)

load_data()
root.mainloop()
