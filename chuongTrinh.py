#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import tkinter as tk
from tkinter import ttk, messagebox
import subprocess
import threading
import os
import socketserver
import serial
import time

# ---------------------------
# LED SERVICE TÍCH HỢP
# ---------------------------
# Cấu hình cổng COM và tốc độ truyền (update theo hệ thống của bạn)
SERIAL_PORT = "COM5"  # Arduino Uno đang ở COM5
BAUDRATE = 9600

try:
    ser = serial.Serial(SERIAL_PORT, BAUDRATE, timeout=1)
    time.sleep(2)  # Đợi Arduino khởi động
    print(f"Đã mở kết nối {SERIAL_PORT} thành công.")
except Exception as e:
    print("Không thể mở cổng COM5:", e)
    ser = None

class LedRequestHandler(socketserver.StreamRequestHandler):
    def handle(self):
        # Đọc lệnh gửi đến từ client
        command = self.rfile.readline().strip().decode('utf-8')
        print(f"Nhận lệnh: {command}")
        if ser:
            try:
                ser.write((command + "\n").encode('utf-8'))
            except Exception as ex:
                print("Lỗi khi gửi lệnh tới Arduino:", ex)
        # Gửi phản hồi cho client
        self.wfile.write(b"OK\n")

def start_led_service():
    HOST, PORT = "localhost", 6000
    with socketserver.TCPServer((HOST, PORT), LedRequestHandler) as server:
        print(f"LED Service đang chạy trên {HOST}:{PORT}")
        server.serve_forever()

# Khởi chạy LED Service trong một thread riêng
led_service_thread = threading.Thread(target=start_led_service, daemon=True)
led_service_thread.start()

# ---------------------------
# CHẠY TÁC VỤ KHÁC (TaoQR.py và Diemdanh.py)
# ---------------------------
def run_checkemtp():
    try:
        # Chạy file TaoQR.py trong cửa sổ console mới
        subprocess.Popen(
            ["python", "TaoQR.py"],
            creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == 'nt' else 0
        )
    except Exception as e:
        messagebox.showerror("Lỗi", f"Không thể chạy TaoQR.py.\nChi tiết: {e}")

def run_attendance():
    try:
        subprocess.Popen(
            ["python", "Diemdanh.py"],
            creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == 'nt' else 0
        )
    except Exception as e:
        messagebox.showerror("Lỗi", f"Không thể chạy Diemdanh.py.\nChi tiết: {e}")

def create_qr():
    thread = threading.Thread(target=run_checkemtp, daemon=True)
    thread.start()

def view_attendance():
    thread = threading.Thread(target=run_attendance, daemon=True)
    thread.start()

# ---------------------------
# GIAO DIỆN CHÍNH
# ---------------------------
root = tk.Tk()
root.title("Hệ thống điểm danh sinh viên bằng mã QR")
root.geometry("1200x600")
root.resizable(False, False)

# Tạo frame chính
main_frame = ttk.Frame(root, padding=20)
main_frame.pack(expand=True, fill="both")

# Tiêu đề
title_label = ttk.Label(main_frame, text="Hệ thống điểm danh sinh viên bằng mã QR", font=("Helvetica", 24, "bold"))
title_label.pack(pady=30)

# Frame chứa các nút chức năng
button_frame = ttk.Frame(main_frame)
button_frame.pack(pady=20)

# Nút "Tạo mã QR"
btn_create_qr = ttk.Button(button_frame, text="Tạo mã QR", command=create_qr)
btn_create_qr.grid(row=0, column=0, padx=40, ipadx=20, ipady=10)

# Nút "Xem điểm danh"
btn_view_attendance = ttk.Button(button_frame, text="Xem điểm danh", command=view_attendance)
btn_view_attendance.grid(row=0, column=1, padx=40, ipadx=20, ipady=10)

# Footer
footer_label = ttk.Label(main_frame, text="© 2025 - Hệ thống điểm danh sinh viên bằng mã QR-Nhóm 1", font=("Helvetica", 10))
footer_label.pack(side="bottom", pady=20)

root.mainloop()
