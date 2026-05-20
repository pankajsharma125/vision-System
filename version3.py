import csv
import os
import subprocess
import sys
import time
import webbrowser
from ctypes import *
from datetime import datetime, timedelta
from html import escape
from tkinter import filedialog, messagebox
import tkinter as tk

import cv2
import numpy as np
from PIL import Image, ImageTk

try:
    import easyocr
except Exception:
    easyocr = None

try:
    import zxingcpp
except Exception:
    zxingcpp = None

try:
    from ultralytics import YOLO
except Exception:
    YOLO = None


ADMIN_PASSWORD = "4036"

sys.path.append(r"C:\Program Files (x86)\MVS\Development\Samples\Python\MvImport")
try:
    from MvCameraControl_class import *
except ImportError:
    print("Warning: MVS SDK not found. Camera features will fail.")


for folder in [
    "results", "results/ng", "results/trigger", "results/barcode",
    "results/ocr", "results/debug", "results/uploaded", "results/circle",
    "reports"
]:
    os.makedirs(folder, exist_ok=True)


def check_ret(ret, msg):
    if ret != 0:
        raise Exception(f"{msg} failed! ret=0x{ret:x}")


class OKNGSoftware:
    def __init__(self, root):
        self.root = root
        self.root.title("Ingenious Techzoid")
        self.root.geometry("1600x850")
        self.root.minsize(1280, 760)

        self.colors = {
            "app_bg": "#fff7ed",
            "panel": "#ffedd5",
            "panel_2": "#fed7aa",
            "panel_3": "#fdba74",
            "border": "#fb923c",
            "text": "#431407",
            "muted": "#9a3412",
            "green": "#51826E",
            "red": "#c05f5f",
            "blue": "#ea580c",
            "cyan": "#f97316",
            "amber": "#c8a05b",
            "orange": "#c2410c",
            "purple": "#b45309",
            "input": "#fffaf0",
            "white": "#ffffff",
            "header": "#81402a",
            "cream": "#fffaf0",
        }

        self.root.configure(bg=self.colors["app_bg"])

        self.is_unlocked = False
        self.cam = None
        self.data_buf = None
        self.payload_size = 0
        self.camera_running = False

        self.current_frame = None
        self.triggered_frame = None
        self.last_ng_frame = None
        self.uploaded_image = None
        self.last_result_image = None

        self.result_history = []
        self.report_rows = []
        self.report_range_var = tk.StringVar(value="All")
        self.good_count = 0
        self.ng_count = 0

        self.model_path = None
        self.ai_model = None
        self.ai_model_loaded_path = None
        self.trigger_mode = "CONTINUOUS"
        self.reading_mode = "AI"
        self.ocr_reader = None

        self.auto_enabled = True
        self.last_auto_ai_time = 0
        self.last_auto_barcode_time = 0
        self.last_auto_ocr_time = 0
        self.last_auto_circle_time = 0
        self.auto_ai_interval = 1.5
        self.auto_barcode_interval = 2.0
        self.auto_ocr_interval = 2.0
        self.auto_circle_interval = 0.25
        self.auto_processing = False

        # Keep camera and preview updates light enough for Tkinter's single UI thread.
        self.camera_loop_delay_ms = 30
        self.camera_timeout_ms = 30
        self.preview_interval = 1 / 15
        self.last_preview_time = 0
        self.preview_size = (850, 620)

        self.circle_burst_results = []
        self.circle_final_result_locked = False
        self.circle_last_result_time = 0
        self.circle_pause_duration = 3.0
        self.previous_radii = []
        self.burst_size = 10
        self.required_ok_count = 4
        self.required_circles_count = 10
        self.mm_per_pixel = 0.04
        self.max_diameter_mm = 10
        self.radius_smoothing_alpha = 0.98

        self.create_ui()

    def make_panel(self, parent, title, width=None):
        panel = tk.LabelFrame(
            parent,
            text=f"  {title}  ",
            font=("Segoe UI", 10, "bold"),
            bg=self.colors["panel"],
            fg=self.colors["text"],
            bd=1,
            relief="solid",
            highlightthickness=1,
            highlightbackground=self.colors["border"],
            labelanchor="n"
        )
        if width:
            panel.configure(width=width)
        return panel

    def make_button(self, parent, text, command, bg, fg=None):
        btn = tk.Button(
            parent,
            text=text,
            command=command,
            bg=bg,
            fg=fg or self.colors["white"],
            activebackground=self.lighten_color(bg),
            activeforeground=self.colors["white"],
            relief="flat",
            bd=0,
            cursor="hand2",
            font=("Segoe UI", 10, "bold"),
            padx=10,
            pady=9
        )
        btn.default_bg = bg
        btn.bind("<Enter>", lambda event: btn.config(bg=self.lighten_color(btn.default_bg)))
        btn.bind("<Leave>", lambda event: btn.config(bg=btn.default_bg))
        return btn

    def make_label(self, parent, text="", fg=None, bg=None, font=None, **kwargs):
        return tk.Label(
            parent,
            text=text,
            fg=fg or self.colors["text"],
            bg=bg or self.colors["panel"],
            font=font or ("Segoe UI", 10),
            **kwargs
        )

    def style_entry(self, entry):
        entry.configure(
            bg=self.colors["input"],
            fg=self.colors["text"],
            insertbackground=self.colors["text"],
            relief="flat",
            bd=0,
            font=("Segoe UI", 10)
        )
        return entry

    def lighten_color(self, color):
        color = color.lstrip("#")
        if len(color) != 6:
            return color
        r = min(int(color[0:2], 16) + 24, 255)
        g = min(int(color[2:4], 16) + 18, 255)
        b = min(int(color[4:6], 16) + 10, 255)
        return f"#{r:02x}{g:02x}{b:02x}"

    def make_scroll_area(self, panel):
        holder = tk.Frame(panel, bg=self.colors["panel"])
        holder.pack(fill="both", expand=True, padx=6, pady=6)

        canvas = tk.Canvas(holder, bg=self.colors["panel"], bd=0, highlightthickness=0)
        scrollbar = tk.Scrollbar(
            holder,
            orient="vertical",
            command=canvas.yview,
            bg=self.colors["panel_3"],
            troughcolor=self.colors["cream"],
            activebackground=self.colors["border"],
            relief="flat",
            width=14
        )
        body = tk.Frame(canvas, bg=self.colors["panel"])
        window_id = canvas.create_window((0, 0), window=body, anchor="nw")

        def update_scroll_region(event=None):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfigure(window_id, width=canvas.winfo_width())

        def mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        body.bind("<Configure>", update_scroll_region)
        canvas.bind("<Configure>", update_scroll_region)
        canvas.bind("<Enter>", lambda event: canvas.bind_all("<MouseWheel>", mousewheel))
        canvas.bind("<Leave>", lambda event: canvas.unbind_all("<MouseWheel>"))
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        return body

    def make_scale(self, parent, variable, from_, to_, resolution):
        return tk.Scale(
            parent,
            variable=variable,
            from_=from_,
            to=to_,
            resolution=resolution,
            orient="horizontal",
            bg=self.colors["panel"],
            fg=self.colors["muted"],
            troughcolor=self.colors["input"],
            activebackground=self.colors["orange"],
            highlightthickness=0,
            bd=0,
            sliderrelief="flat",
            length=210,
            showvalue=False
        )

    def create_ui(self):
        header = tk.Frame(self.root, bg=self.colors["header"], height=74)
        header.pack(fill="x")
        header.pack_propagate(False)

        tk.Label(
            header,
            text="INGENIOUS TECHZOID",
            font=("Segoe UI", 24, "bold"),
            bg=self.colors["header"],
            fg=self.colors["cream"]
        ).pack(side="left", padx=(28, 10))

        # self.header_mode_lbl = tk.Label(
        #     header,
        #     text="AI",
        #     font=("Segoe UI", 11, "bold"),
        #     bg=self.colors["orange"],
        #     fg=self.colors["white"],
        #     padx=14,
        #     pady=5
        # )
        # self.header_mode_lbl.pack(side="left", padx=12)

        self.lock_status_lbl = tk.Label(
            header,
            text="CLIENT MODE",
            font=("Segoe UI", 15, "bold"),
            bg=self.colors["header"],
            fg="#fde68a"
        )
        self.lock_status_lbl.pack(side="right", padx=(12, 28))

        self.main = tk.Frame(self.root, bg=self.colors["app_bg"])
        self.main.pack(fill="both", expand=True, padx=14, pady=14)

        self.left_shell = self.make_panel(self.main, "Controls", width=304)
        self.left_shell.pack(side="left", fill="y", padx=(0, 10), pady=0)
        self.left_shell.pack_propagate(False)
        self.left = self.make_scroll_area(self.left_shell)

        self.preview = self.make_panel(self.main, "Live Camera")
        self.preview.pack(side="left", fill="both", expand=True, padx=0, pady=0)

        self.preview_label = tk.Label(
            self.preview,
            bg="#000000",
            bd=0,
            highlightthickness=1,
            highlightbackground=self.colors["border"]
        )
        self.preview_label.pack(fill="both", expand=True, padx=10, pady=10)

        self.right_shell = self.make_panel(self.main, "Result Panel", width=350)
        self.right_shell.pack(side="right", fill="y", padx=(10, 0), pady=0)
        self.right_shell.pack_propagate(False)
        self.right = self.make_scroll_area(self.right_shell)

        self.create_left_panel()
        self.create_right_panel()
        self.show_locked_panel()

    def create_left_panel(self):
        self.make_button(self.left, "Select AI Model", self.select_model, self.colors["orange"]).pack(fill="x", padx=16, pady=(14, 6))
        self.make_button(self.left, "Train Model", self.open_yolo_file, self.colors["cyan"]).pack(fill="x", padx=16, pady=6)

        self.model_lbl = self.make_label(self.left, text="No model selected", fg=self.colors["muted"], font=("Segoe UI", 9), wraplength=245)
        self.model_lbl.pack(fill="x", padx=16, pady=(0, 10))

        self.make_button(self.left, "Lock Software", self.lock_software, self.colors["header"]).pack(fill="x", padx=16, pady=6)
        self.make_button(self.left, "Start Camera", self.start_camera, self.colors["green"]).pack(fill="x", padx=16, pady=6)
        self.make_button(self.left, "Stop Camera", self.stop_camera, self.colors["red"]).pack(fill="x", padx=16, pady=6)

        mode_select_box = self.make_panel(self.left, "Reading Mode")
        mode_select_box.pack(fill="x", padx=12, pady=10)
        self.mode_var = tk.StringVar(value="AI")

        for text, value in [
            ("AI OK / NG", "AI"),
            ("Barcode / QR Reading", "BARCODE"),
            ("OCR Reading", "OCR"),
            ("Size Detection", "CIRCLE"),
        ]:
            tk.Radiobutton(
                mode_select_box,
                text=text,
                variable=self.mode_var,
                value=value,
                command=self.change_reading_mode,
                bg=self.colors["panel"],
                fg=self.colors["text"],
                selectcolor=self.colors["cream"],
                activebackground=self.colors["panel"],
                activeforeground=self.colors["orange"],
                font=("Segoe UI", 10, "bold")
            ).pack(anchor="w", padx=12, pady=4)

        camera_mode_box = self.make_panel(self.left, "Camera Mode")
        camera_mode_box.pack(fill="x", padx=12, pady=8)
        self.mode_btn = self.make_button(camera_mode_box, "Mode: CONTINUOUS", self.toggle_mode, self.colors["cyan"])
        self.mode_btn.pack(fill="x", padx=10, pady=(10, 5))
        self.trigger_btn = self.make_button(camera_mode_box, "Trigger Capture", self.software_trigger, self.colors["amber"])
        self.trigger_btn.pack(fill="x", padx=10, pady=5)

        self.make_button(self.left, "Run Selected Reading", self.run_selected_reading, self.colors["orange"]).pack(fill="x", padx=16, pady=6)
        self.make_button(self.left, "Upload Image & Inspect", self.upload_image_inspection, self.colors["purple"]).pack(fill="x", padx=16, pady=6)
        self.make_button(self.left, "Save Result Image", self.save_result_image, "#9a3412").pack(fill="x", padx=16, pady=6)

        report_box = self.make_panel(self.left, "Reports")
        report_box.pack(fill="x", padx=12, pady=10)

        self.make_label(report_box, "Report Range", fg=self.colors["muted"], font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=10, pady=(10, 2))
        self.report_range_menu = tk.OptionMenu(
            report_box,
            self.report_range_var,
            "All",
            "1 Day",
            "7 Days",
            "15 Days",
            "30 Days"
        )
        self.report_range_menu.configure(
            bg=self.colors["input"],
            fg=self.colors["text"],
            activebackground=self.colors["panel_3"],
            activeforeground=self.colors["text"],
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=self.colors["border"],
            font=("Segoe UI", 10, "bold")
        )
        self.report_range_menu["menu"].configure(
            bg=self.colors["input"],
            fg=self.colors["text"],
            activebackground=self.colors["panel_3"],
            activeforeground=self.colors["text"]
        )
        self.report_range_menu.pack(fill="x", padx=10, pady=(0, 8))

        self.make_button(report_box, "View Report", self.open_report_window, self.colors["orange"]).pack(fill="x", padx=10, pady=(10, 5))
        self.make_button(report_box, "Export Report", self.export_report, self.colors["header"]).pack(fill="x", padx=10, pady=5)
        self.make_button(report_box, "Clear Report Data", self.clear_report_data, "#b91c1c").pack(fill="x", padx=10, pady=(5, 10))

        feature_box = self.make_panel(self.left, "Camera Features")
        feature_box.pack(fill="x", padx=12, pady=10)

        self.make_label(feature_box, "Exposure", fg=self.colors["muted"], font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=10, pady=(8, 2))
        self.exposure_var = tk.DoubleVar(value=6000)
        self.make_scale(feature_box, self.exposure_var, 100, 30000, 100).pack(fill="x", padx=10)
        self.style_entry(tk.Entry(feature_box, textvariable=self.exposure_var)).pack(fill="x", padx=10, ipady=6)
        self.make_button(feature_box, "Set Exposure", self.set_exposure, self.colors["header"]).pack(fill="x", padx=10, pady=5)

        self.make_label(feature_box, "Gain", fg=self.colors["muted"], font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=10, pady=(4, 2))
        self.gain_var = tk.DoubleVar(value=8)
        self.make_scale(feature_box, self.gain_var, 0, 24, 0.1).pack(fill="x", padx=10)
        self.style_entry(tk.Entry(feature_box, textvariable=self.gain_var)).pack(fill="x", padx=10, ipady=6)
        self.make_button(feature_box, "Set Gain", self.set_gain, self.colors["header"]).pack(fill="x", padx=10, pady=5)

        self.make_label(feature_box, "FPS", fg=self.colors["muted"], font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=10, pady=(4, 2))
        self.fps_var = tk.DoubleVar(value=15)
        self.make_scale(feature_box, self.fps_var, 1, 60, 1).pack(fill="x", padx=10)
        self.style_entry(tk.Entry(feature_box, textvariable=self.fps_var)).pack(fill="x", padx=10, ipady=6)
        self.make_button(feature_box, "Set FPS", self.set_fps, self.colors["header"]).pack(fill="x", padx=10, pady=(5, 10))

        self.status_lbl = self.make_label(
            self.left,
            text="Status: Ready",
            fg=self.colors["green"],
            bg=self.colors["cream"],
            font=("Segoe UI", 10, "bold"),
            anchor="w",
            padx=12,
            pady=8
        )
        self.status_lbl.pack(fill="x", padx=16, pady=(0, 12))

    def create_right_panel(self):
        self.password_frame = self.make_panel(self.right, "Password Unlock")
        self.make_label(self.password_frame, "Enter Password", font=("Segoe UI", 12, "bold")).pack(pady=(14, 8))

        self.password_var = tk.StringVar()
        self.password_entry = self.style_entry(tk.Entry(
            self.password_frame,
            textvariable=self.password_var,
            show="*",
            font=("Segoe UI", 16, "bold"),
            justify="center"
        ))
        self.password_entry.pack(fill="x", padx=22, pady=5, ipady=8)
        self.password_entry.bind("<Return>", lambda e: self.check_password())
        self.make_button(self.password_frame, "Unlock", self.check_password, self.colors["green"]).pack(fill="x", padx=22, pady=10)
        self.password_msg_lbl = self.make_label(self.password_frame, text="", fg="#dc2626")
        self.password_msg_lbl.pack(pady=(0, 12))

        self.result_frame = self.make_panel(self.right, "Detection Result")
        self.result_box = tk.Label(self.result_frame, text="WAIT", bg=self.colors["panel_3"], fg=self.colors["text"], font=("Segoe UI", 34, "bold"), height=1, relief="flat")
        self.result_box.pack(fill="x", padx=9, pady=(9, 6))

        self.detect_time_lbl = tk.Label(self.result_frame, text="Detection Time: 0.000s", bg=self.colors["cream"], fg=self.colors["text"], font=("Segoe UI", 11, "bold"), pady=7)
        self.detect_time_lbl.pack(fill="x", padx=12, pady=5)

        self.circle_status_lbl = tk.Label(self.result_frame, text="", bg=self.colors["panel"], font=("Segoe UI", 10, "bold"), fg=self.colors["orange"])
        self.circle_status_lbl.pack(fill="x", padx=12, pady=(2, 10))

        self.dots_frame = self.make_panel(self.right, "Last 10 OK / NG Results")
        self.dot_canvas = tk.Canvas(self.dots_frame, width=300, height=72, bg=self.colors["cream"], bd=0, highlightthickness=1, highlightbackground=self.colors["border"])
        self.dot_canvas.pack(padx=12, pady=(12, 8))
        self.counter_lbl = tk.Label(self.dots_frame, text="Good: 0\nNot Good: 0", font=("Segoe UI", 14, "bold"), justify="left", bg=self.colors["panel"], fg=self.colors["text"])
        self.counter_lbl.pack(anchor="w", padx=16, pady=(0, 6))
        self.reset_btn = self.make_button(self.dots_frame, "Reset Counter", self.reset_counter, self.colors["cyan"])
        self.reset_btn.pack(fill="x", padx=16, pady=(0, 12))

        self.read_result_box = self.make_panel(self.right, "Barcode / OCR / AI Details")
        self.reading_result_text = tk.Text(self.read_result_box, height=14, width=42, font=("Consolas", 10), wrap="word", bg=self.colors["input"], fg=self.colors["text"], insertbackground=self.colors["text"], relief="flat", bd=0)
        self.reading_result_text.pack(fill="x", padx=12, pady=12)
        self.reading_result_text.insert(tk.END, "Barcode / OCR value will appear here...")

        self.trigger_img_box = self.make_panel(self.right, "Triggered / Uploaded Image")
        self.trigger_image_label = tk.Label(self.trigger_img_box, bg="#fed7aa", width=300, height=20, bd=0)
        self.trigger_image_label.pack(padx=12, pady=10)

        self.ng_img_box = self.make_panel(self.right, "Last NG Image")
        self.ng_image_label = tk.Label(self.ng_img_box, bg="#fecaca", bd=0)
        self.ng_image_label.configure(width=300, height=140)
        self.ng_image_label.pack_propagate(False)
        self.ng_image_label.pack(padx=12, pady=10)

        self.history_box = self.make_panel(self.right, "Result History")
        self.history_text = tk.Text(self.history_box, height=16, width=42, font=("Consolas", 9), bg=self.colors["input"], fg=self.colors["text"], relief="flat", bd=0)
        self.history_text.pack(fill="both", expand=True, padx=12, pady=12)

        self.draw_result_dots()

    def clear_right_panel(self):
        for widget in self.right.winfo_children():
            widget.pack_forget()

    def show_locked_panel(self):
        self.is_unlocked = False
        self.left_shell.pack_forget()
        self.clear_right_panel()
        self.password_frame.pack(fill="x", padx=10, pady=10)
        self.dots_frame.pack(fill="x", padx=10, pady=10)
        self.lock_status_lbl.config(text="NORMAL MODE", fg="#fde68a")
        self.password_msg_lbl.config(text="")

    def show_unlocked_panel(self):
        self.is_unlocked = True
        self.clear_right_panel()
        self.left_shell.pack(side="left", fill="y", padx=(0, 10), pady=0, before=self.preview)
        self.result_frame.pack(fill="x", padx=10, pady=6)
        self.dots_frame.pack(fill="x", padx=10, pady=6)
        self.read_result_box.pack(fill="x", padx=10, pady=6)
        self.trigger_img_box.pack(fill="x", padx=10, pady=6)
        self.ng_img_box.pack(fill="x", padx=10, pady=6)
        self.history_box.pack(fill="both", expand=True, padx=10, pady=6)
        self.lock_status_lbl.config(text="ADVANCE MODE", fg="#bbf7d0")

    def check_password(self):
        if self.password_var.get() == ADMIN_PASSWORD:
            self.password_var.set("")
            self.show_unlocked_panel()
        else:
            self.password_msg_lbl.config(text="Wrong password")

    def lock_software(self):
        self.show_locked_panel()

    def open_yolo_file(self):
        try:
            yolo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "yolo.py")
            if not os.path.exists(yolo_path):
                messagebox.showerror("File Error", f"yolo.py file not found:\n{yolo_path}")
                return
            subprocess.Popen([sys.executable, yolo_path], creationflags=subprocess.CREATE_NO_WINDOW)
            self.status_lbl.config(text="Status: yolo.py Running", fg=self.colors["green"])
        except Exception as e:
            messagebox.showerror("Train Model Error", str(e))

    def upload_image_inspection(self):
        path = filedialog.askopenfilename(title="Select Image", filetypes=[("Image Files", "*.jpg *.jpeg *.png *.bmp *.webp"), ("All Files", "*.*")])
        if not path:
            return
        frame = cv2.imread(path)
        if frame is None:
            messagebox.showerror("Image Error", "Image load nahi ho pa rahi.")
            return
        self.uploaded_image = frame.copy()
        self.current_frame = frame.copy()
        self.triggered_frame = frame.copy()
        self.show_large_preview(frame)
        if self.is_unlocked:
            self.show_small_image(frame, self.trigger_image_label, 300, 140)
        save_path = f"results/uploaded/uploaded_{time.strftime('%Y%m%d_%H%M%S')}.jpg"
        cv2.imwrite(save_path, frame)
        self.status_lbl.config(text="Status: Uploaded Image Loaded", fg=self.colors["green"])
        self.run_selected_reading()

    def change_reading_mode(self):
        self.reading_mode = self.mode_var.get()
        self.circle_burst_results = []
        self.circle_final_result_locked = False
        self.previous_radii = []
        self.circle_status_lbl.config(text="")
        self.reading_result_text.delete("1.0", tk.END)

        now = time.time()
        self.last_auto_ai_time = now
        self.last_auto_barcode_time = now
        self.last_auto_ocr_time = now
        self.last_auto_circle_time = now

        mode_ui = {
            "AI": ("AI", self.colors["orange"], "Selected Mode: AI Auto Reading\n"),
            "BARCODE": ("BARCODE", self.colors["cyan"], "Selected Mode: Barcode / QR Auto Reading\n"),
            "OCR": ("OCR", self.colors["purple"], "Selected Mode: OCR Auto Reading\n"),
            "CIRCLE": ("SIZE", self.colors["amber"], f"Selected Mode: Size Detection Auto Reading\nBurst Size: {self.burst_size}\n"),
        }
        title, color, details = mode_ui[self.reading_mode]
        self.result_box.config(text=title, bg=color, fg="white")
        if hasattr(self, "header_mode_lbl"):
            self.header_mode_lbl.config(text=title, bg=color)
        self.reading_result_text.insert(tk.END, details)
        self.status_lbl.config(text=f"Auto Mode Selected: {self.reading_mode}", fg=self.colors["orange"])

        if self.current_frame is not None:
            self.root.after(100, self.run_selected_reading)

    def run_selected_reading(self):
        if self.reading_mode == "AI":
            self.run_prediction()
        elif self.reading_mode == "BARCODE":
            self.run_barcode_reading()
        elif self.reading_mode == "OCR":
            self.run_ocr_reading()
        elif self.reading_mode == "CIRCLE" and self.current_frame is not None:
            frame = self.current_frame.copy()
            self.process_circle_detection(frame)
            self.show_large_preview(frame)

    def auto_run_current_mode(self, frame):
        if not self.auto_enabled or self.auto_processing:
            return
        now = time.time()
        if self.reading_mode == "CIRCLE" and now - self.last_auto_circle_time >= self.auto_circle_interval:
            self.last_auto_circle_time = now
            self.auto_processing = True
            try:
                self.process_circle_detection(frame)
            finally:
                self.auto_processing = False
        elif self.reading_mode == "AI" and now - self.last_auto_ai_time >= self.auto_ai_interval:
            self.last_auto_ai_time = now
            self.auto_processing = True
            try:
                self.run_prediction()
            finally:
                self.auto_processing = False
        elif self.reading_mode == "BARCODE" and now - self.last_auto_barcode_time >= self.auto_barcode_interval:
            self.last_auto_barcode_time = now
            self.auto_processing = True
            try:
                self.run_barcode_reading()
            finally:
                self.auto_processing = False
        elif self.reading_mode == "OCR" and now - self.last_auto_ocr_time >= self.auto_ocr_interval:
            self.last_auto_ocr_time = now
            self.auto_processing = True
            try:
                self.run_ocr_reading()
            finally:
                self.auto_processing = False

    def select_model(self):
        path = filedialog.askopenfilename(title="Select Model", filetypes=[("Model Files", "*.pt *.onnx *.h5 *.pkl"), ("All Files", "*.*")])
        if path:
            self.model_path = path
            self.ai_model = None
            self.ai_model_loaded_path = None
            self.model_lbl.config(text=os.path.basename(path))
            self.status_lbl.config(text="Status: Model Selected", fg=self.colors["green"])

    def start_camera(self):
        try:
            if self.camera_running:
                messagebox.showinfo("Info", "Camera already running")
                return
            device_list = MV_CC_DEVICE_INFO_LIST()
            ret = MvCamera.MV_CC_EnumDevices(MV_GIGE_DEVICE, device_list)
            if device_list.nDeviceNum == 0:
                ret = MvCamera.MV_CC_EnumDevices(MV_USB_DEVICE, device_list)
            check_ret(ret, "Enum devices")
            if device_list.nDeviceNum == 0:
                messagebox.showerror("Camera Error", "No Hikrobot camera found")
                return
            self.cam = MvCamera()
            st_device = cast(device_list.pDeviceInfo[0], POINTER(MV_CC_DEVICE_INFO)).contents
            check_ret(self.cam.MV_CC_CreateHandle(st_device), "Create handle")
            check_ret(self.cam.MV_CC_OpenDevice(MV_ACCESS_Control, 0), "Open device")
            packet_size = self.cam.MV_CC_GetOptimalPacketSize()
            if packet_size > 0:
                self.cam.MV_CC_SetIntValue("GevSCPSPacketSize", packet_size)
            self.apply_camera_mode()
            self.apply_default_features()
            check_ret(self.cam.MV_CC_StartGrabbing(), "Start grabbing")
            st_param = MVCC_INTVALUE()
            memset(byref(st_param), 0, sizeof(MVCC_INTVALUE))
            check_ret(self.cam.MV_CC_GetIntValue("PayloadSize", st_param), "Get payload size")
            self.payload_size = st_param.nCurValue
            self.data_buf = (c_ubyte * self.payload_size)()
            self.camera_running = True
            self.status_lbl.config(text="Status: Camera Running", fg=self.colors["green"])
            self.update_frame()
        except Exception as e:
            messagebox.showerror("Camera Error", str(e))

    def apply_camera_mode(self):
        if not self.cam:
            return
        if self.trigger_mode == "CONTINUOUS":
            self.cam.MV_CC_SetEnumValue("TriggerMode", 0)
        else:
            self.cam.MV_CC_SetEnumValue("TriggerMode", 1)
            self.cam.MV_CC_SetEnumValue("TriggerSource", 7)

    def toggle_mode(self):
        try:
            if self.trigger_mode == "CONTINUOUS":
                self.trigger_mode = "TRIGGER"
                color = self.colors["amber"]
                self.mode_btn.config(text="Mode: TRIGGER", bg=color)
                self.mode_btn.default_bg = color
            else:
                self.trigger_mode = "CONTINUOUS"
                color = self.colors["cyan"]
                self.mode_btn.config(text="Mode: CONTINUOUS", bg=color)
                self.mode_btn.default_bg = color
            self.status_lbl.config(text=f"Mode: {self.trigger_mode}", fg=self.colors["orange"])
            if self.cam:
                self.apply_camera_mode()
        except Exception as e:
            messagebox.showerror("Mode Error", str(e))

    def software_trigger(self):
        if not self.cam:
            messagebox.showwarning("Warning", "Camera not started")
            return
        if self.trigger_mode != "TRIGGER":
            messagebox.showinfo("Info", "Please switch to TRIGGER mode first")
            return
        try:
            check_ret(self.cam.MV_CC_SetCommandValue("TriggerSoftware"), "Software trigger")
            self.status_lbl.config(text="Status: Trigger Sent", fg=self.colors["green"])
            self.root.after(200, self.after_trigger_capture)
        except Exception as e:
            messagebox.showerror("Trigger Error", str(e))

    def after_trigger_capture(self):
        if self.current_frame is not None:
            self.triggered_frame = self.current_frame.copy()
            if self.is_unlocked:
                self.show_small_image(self.triggered_frame, self.trigger_image_label, 300, 140)
            filename = f"results/trigger/trigger_{time.strftime('%Y%m%d_%H%M%S')}.jpg"
            cv2.imwrite(filename, self.triggered_frame)
            self.run_selected_reading()

    def apply_default_features(self):
        try:
            self.cam.MV_CC_SetEnumValue("ExposureAuto", 0)
            self.cam.MV_CC_SetFloatValue("ExposureTime", float(self.exposure_var.get()))
            self.cam.MV_CC_SetEnumValue("GainAuto", 0)
            self.cam.MV_CC_SetFloatValue("Gain", float(self.gain_var.get()))
            self.cam.MV_CC_SetBoolValue("AcquisitionFrameRateEnable", True)
            self.cam.MV_CC_SetFloatValue("AcquisitionFrameRate", float(self.fps_var.get()))
        except Exception as e:
            print("Feature warning:", e)

    def update_frame(self):
        if not self.camera_running:
            return
        frame_info = MV_FRAME_OUT_INFO_EX()
        memset(byref(frame_info), 0, sizeof(frame_info))
        ret = self.cam.MV_CC_GetOneFrameTimeout(byref(self.data_buf), self.payload_size, frame_info, self.camera_timeout_ms)
        if ret == 0:
            width = frame_info.nWidth
            height = frame_info.nHeight
            img = np.frombuffer(self.data_buf, dtype=np.uint8)
            if frame_info.enPixelType == PixelType_Gvsp_Mono8:
                img = img.reshape(height, width)
                frame = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
            else:
                img = img.reshape(height, width)
                if frame_info.enPixelType == PixelType_Gvsp_BayerRG8:
                    frame = cv2.cvtColor(img, cv2.COLOR_BAYER_RG2BGR)
                elif frame_info.enPixelType == PixelType_Gvsp_BayerGB8:
                    frame = cv2.cvtColor(img, cv2.COLOR_BAYER_GB2BGR)
                elif frame_info.enPixelType == PixelType_Gvsp_BayerGR8:
                    frame = cv2.cvtColor(img, cv2.COLOR_BAYER_GR2BGR)
                else:
                    frame = cv2.cvtColor(img, cv2.COLOR_BAYER_BG2BGR)

            self.current_frame = frame.copy()
            display_frame = frame.copy()
            self.auto_run_current_mode(display_frame)

            now = time.time()
            if now - self.last_preview_time >= self.preview_interval:
                self.last_preview_time = now
                if self.reading_mode == "CIRCLE":
                    self.show_large_preview(display_frame)
                elif self.last_result_image is not None:
                    self.show_large_preview(self.last_result_image)
                else:
                    self.show_large_preview(frame)

        self.root.after(self.camera_loop_delay_ms, self.update_frame)

    def process_circle_detection(self, frame):
        if self.circle_final_result_locked:
            elapsed = time.time() - self.circle_last_result_time
            remaining = max(int(self.circle_pause_duration - elapsed), 0)
            cv2.putText(frame, f"Next Detection In: {remaining}s", (30, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 140, 255), 3)
            self.circle_status_lbl.config(text=f"Waiting... {remaining}s")
            if elapsed >= self.circle_pause_duration:
                self.circle_final_result_locked = False
                self.circle_burst_results = []
                self.circle_status_lbl.config(text="")
            return

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        blur = cv2.GaussianBlur(gray, (11, 11), 2)
        blur = cv2.medianBlur(blur, 5)
        circles = cv2.HoughCircles(blur, cv2.HOUGH_GRADIENT, dp=1.2, minDist=140, param1=100, param2=30, minRadius=80, maxRadius=115)

        count = 0
        frame_result = "OK"
        current_radii = []
        if circles is not None:
            circles = np.round(circles[0]).astype("int")
            final_circles = []
            for (x, y, r) in circles:
                duplicate = any(np.sqrt((x - fx) ** 2 + (y - fy) ** 2) < 100 for (fx, fy, fr) in final_circles)
                if not duplicate:
                    final_circles.append((x, y, r))
            final_circles = sorted(final_circles, key=lambda c: (c[1], c[0]))[:self.required_circles_count]

            for i, (x, y, r) in enumerate(final_circles):
                if len(self.previous_radii) > i:
                    stable_r = int((self.previous_radii[i] * self.radius_smoothing_alpha) + (r * (1 - self.radius_smoothing_alpha)))
                else:
                    stable_r = r
                current_radii.append(stable_r)
                diameter_mm = (stable_r * 2) * self.mm_per_pixel
                if diameter_mm > self.max_diameter_mm:
                    color = (0, 0, 255)
                    frame_result = "NG"
                else:
                    color = (0, 255, 0)
                cv2.circle(frame, (x, y), stable_r, color, 4)
                cv2.putText(frame, f"{diameter_mm:.2f} mm", (x - 70, y - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 140, 255), 2)
                count += 1

        self.previous_radii = current_radii
        if count != self.required_circles_count:
            frame_result = "NG"
        self.circle_burst_results.append(frame_result)
        self.circle_burst_results = self.circle_burst_results[-self.burst_size:]
        ok_count = self.circle_burst_results.count("OK")
        self.circle_status_lbl.config(text=f"Burst OK: {ok_count}/{len(self.circle_burst_results)}")
        cv2.putText(frame, f"Burst OK: {ok_count}", (30, 60), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 140, 255), 1)

        if len(self.circle_burst_results) >= self.burst_size:
            if ok_count >= self.required_ok_count:
                self.result_box.config(text="GOOD", bg=self.colors["green"], fg="white")
                self.add_history("OK", 100.0, 0, details=f"Size detection OK. Circles: {count}")
            else:
                self.result_box.config(text="NG", bg=self.colors["red"], fg="white")
                self.add_history("NG", 0.0, 0, details=f"Size detection NG. Circles: {count}")
                self.last_ng_frame = frame.copy()
                if self.is_unlocked:
                    self.show_small_image(self.last_ng_frame, self.ng_image_label, 300, 140)
            self.circle_final_result_locked = True
            self.circle_last_result_time = time.time()
            cv2.imwrite(f"results/circle/circle_{time.strftime('%Y%m%d_%H%M%S')}.jpg", frame)
        else:
            self.result_box.config(text=f"CHECKING {len(self.circle_burst_results)}/{self.burst_size}", bg=self.colors["orange"], fg="white")
        self.last_result_image = frame.copy()

    def show_large_preview(self, frame):
        img = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = cv2.resize(img, self.preview_size)
        imgtk = ImageTk.PhotoImage(Image.fromarray(img))
        self.preview_label.imgtk = imgtk
        self.preview_label.config(image=imgtk)

    def show_small_image(self, frame, label_widget, w, h):
        img = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = cv2.resize(img, (w, h))
        imgtk = ImageTk.PhotoImage(Image.fromarray(img))
        label_widget.imgtk = imgtk
        label_widget.config(image=imgtk)

    def stop_camera(self):
        try:
            self.camera_running = False
            if self.cam:
                self.cam.MV_CC_StopGrabbing()
                self.cam.MV_CC_CloseDevice()
                self.cam.MV_CC_DestroyHandle()
                self.cam = None
            if hasattr(self, "status_lbl"):
                self.status_lbl.config(text="Status: Camera Stopped", fg=self.colors["red"])
        except Exception as e:
            messagebox.showerror("Stop Error", str(e))

    def set_exposure(self):
        if self.cam:
            self.cam.MV_CC_SetEnumValue("ExposureAuto", 0)
            self.cam.MV_CC_SetFloatValue("ExposureTime", float(self.exposure_var.get()))
            self.status_lbl.config(text="Status: Exposure Updated", fg=self.colors["green"])

    def set_gain(self):
        if self.cam:
            self.cam.MV_CC_SetEnumValue("GainAuto", 0)
            self.cam.MV_CC_SetFloatValue("Gain", float(self.gain_var.get()))
            self.status_lbl.config(text="Status: Gain Updated", fg=self.colors["green"])

    def set_fps(self):
        if self.cam:
            self.cam.MV_CC_SetBoolValue("AcquisitionFrameRateEnable", True)
            self.cam.MV_CC_SetFloatValue("AcquisitionFrameRate", float(self.fps_var.get()))
            self.status_lbl.config(text="Status: FPS Updated", fg=self.colors["green"])

    def run_prediction(self):
        if self.current_frame is None:
            return
        if YOLO is None:
            self.result_box.config(text="YOLO MISSING", bg=self.colors["red"], fg="white")
            self.reading_result_text.delete("1.0", tk.END)
            self.reading_result_text.insert(tk.END, "Run: pip install ultralytics\n")
            return
        if not self.model_path:
            self.result_box.config(text="NO MODEL", bg=self.colors["red"], fg="white")
            self.reading_result_text.delete("1.0", tk.END)
            self.reading_result_text.insert(tk.END, "Please select AI model first.\n")
            return

        start_time = time.time()
        frame = self.current_frame.copy()
        try:
            if self.ai_model is None or self.ai_model_loaded_path != self.model_path:
                self.status_lbl.config(text="Loading AI Model...", fg=self.colors["orange"])
                self.root.update()
                self.ai_model = YOLO(self.model_path)
                self.ai_model_loaded_path = self.model_path
                self.status_lbl.config(text="AI Model Loaded", fg=self.colors["green"])
            results = self.ai_model(frame, conf=0.15, verbose=False)
            result = results[0]
            label, confidence, frame = self.get_ai_ok_ng_result(result, frame)
        except Exception as e:
            self.result_box.config(text="AI ERROR", bg=self.colors["red"], fg="white")
            self.reading_result_text.delete("1.0", tk.END)
            self.reading_result_text.insert(tk.END, str(e))
            return

        label_upper = label.upper()
        is_ok = label_upper == "OK"
        detection_time = time.time() - start_time
        self.detect_time_lbl.config(text=f"Detection Time: {detection_time:.3f}s")

        details = self.reading_result_text.get("1.0", tk.END).strip()
        if is_ok:
            self.result_box.config(text="GOOD", bg=self.colors["green"], fg="white")
            self.add_history("OK", confidence, detection_time, details=details)
        else:
            self.result_box.config(text="NG", bg=self.colors["red"], fg="white")
            self.add_history("NG", confidence, detection_time, details=details)
            self.last_ng_frame = frame.copy()
            if self.is_unlocked:
                self.show_small_image(self.last_ng_frame, self.ng_image_label, 300, 140)

        cv2.putText(frame, f"{label_upper} {confidence:.2f}%", (40, 70), cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 255, 0) if is_ok else (0, 0, 255), 4)
        self.last_result_image = frame.copy()
        self.show_large_preview(frame)

    def get_ai_ok_ng_result(self, result, frame):
        names = result.names if hasattr(result, "names") else {}
        ok_confidence_limit = 20.0
        ng_confidence_limit = 50.0
        ok_words = ("OK", "GOOD", "PASS", "ACCEPT", "ACCEPTED")
        ng_words = ("NG", "NOK", "NOTGOOD", "NOT_GOOD", "DEFECT", "DEFECTIVE", "FAIL", "FAILED", "REJECT", "REJECTED", "BAD", "SCRATCH", "DAMAGE", "DAMAGED", "MISSING", "WRONG", "ERROR")

        def normalize_label(value):
            return str(value).upper().replace(" ", "").replace("-", "_")

        if getattr(result, "probs", None) is not None:
            top_index = int(result.probs.top1)
            confidence = float(result.probs.top1conf) * 100
            class_name = str(names.get(top_index, top_index))
            normalized = normalize_label(class_name)
            self.reading_result_text.delete("1.0", tk.END)
            self.reading_result_text.insert(tk.END, f"AI Class: {class_name}\nConfidence: {confidence:.2f}%\n")
            is_ng_class = any(word in normalized for word in ng_words)
            is_ok_class = any(word in normalized for word in ok_words)
            if is_ng_class and confidence > ng_confidence_limit:
                return "NG", confidence, frame
            if is_ok_class and confidence >= ok_confidence_limit:
                return "OK", confidence, frame
            return "NG", confidence, frame

        boxes = getattr(result, "boxes", None)
        if boxes is None or len(boxes) == 0:
            self.reading_result_text.delete("1.0", tk.END)
            self.reading_result_text.insert(tk.END, "AI Class: No detection\nResult: OK\n")
            cv2.putText(frame, "NO DEFECT", (40, 130), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 255, 0), 3)
            return "OK", 100.0, frame

        detections = []
        detected_lines = []

        for box in boxes:
            cls_id = int(box.cls[0])
            confidence = float(box.conf[0]) * 100
            class_name = str(names.get(cls_id, cls_id))
            normalized = normalize_label(class_name)
            detected_lines.append(f"{class_name}: {confidence:.2f}%")
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            is_ng_class = any(word in normalized for word in ng_words)
            is_ok_class = any(word in normalized for word in ok_words)

            if is_ok_class and confidence >= ok_confidence_limit:
                result_label = "OK"
            elif is_ng_class and confidence > ng_confidence_limit:
                result_label = "NG"
            elif not is_ok_class and not is_ng_class and confidence > ng_confidence_limit:
                result_label = "NG"
            else:
                result_label = "LOW"

            detections.append({
                "box": (x1, y1, x2, y2),
                "class_name": class_name,
                "confidence": confidence,
                "result_label": result_label,
            })

        self.reading_result_text.delete("1.0", tk.END)
        self.reading_result_text.insert(tk.END, "AI Detected:\n")
        self.reading_result_text.insert(tk.END, "\n".join(detected_lines))

        ng_detections = [item for item in detections if item["result_label"] == "NG"]
        ok_detections = [item for item in detections if item["result_label"] == "OK"]

        if ng_detections:
            self.draw_final_ai_boxes(frame, ng_detections, "NG", (0, 0, 255))
            return "NG", max(item["confidence"] for item in ng_detections), frame

        if ok_detections:
            self.draw_final_ai_boxes(frame, ok_detections, "OK", (0, 255, 0))
            return "OK", max(item["confidence"] for item in ok_detections), frame

        best_detection = max(detections, key=lambda item: item["confidence"])
        self.draw_final_ai_boxes(frame, [best_detection], "NG", (0, 0, 255))
        return "NG", best_detection["confidence"], frame

    def draw_final_ai_boxes(self, frame, detections, final_label, color):
        for item in detections:
            x1, y1, x2, y2 = item["box"]
            confidence = item["confidence"]
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 3)
            cv2.putText(
                frame,
                f"{final_label} {confidence:.1f}%",
                (x1, max(y1 - 10, 30)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                color,
                2
            )

    def scan_barcode_from_frame(self, frame):
        if frame is None or zxingcpp is None:
            return None
        cv2.imwrite("results/debug/barcode_input_original.jpg", frame)
        h, w = frame.shape[:2]
        crops = [
            ("full", frame),
            ("center", frame[int(h * 0.15):int(h * 0.85), int(w * 0.10):int(w * 0.90)]),
            ("middle", frame[int(h * 0.25):int(h * 0.75), int(w * 0.15):int(w * 0.85)])
        ]
        for crop_name, crop in crops:
            if crop.size == 0:
                continue
            results = zxingcpp.read_barcodes(crop)
            if results:
                return results
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            variants = {
                f"{crop_name}_gray": gray,
                f"{crop_name}_gray_2x": cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC),
                f"{crop_name}_gray_3x": cv2.resize(gray, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC),
                f"{crop_name}_equalized": cv2.equalizeHist(gray),
                f"{crop_name}_otsu": cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1],
                f"{crop_name}_adaptive": cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 5),
            }
            blur = cv2.GaussianBlur(gray, (0, 0), 3)
            variants[f"{crop_name}_sharpen"] = cv2.addWeighted(gray, 2.0, blur, -1.0, 0)
            for name, img in variants.items():
                cv2.imwrite(f"results/debug/{name}.png", img)
                results = zxingcpp.read_barcodes(img)
                if results:
                    return results
        return None

    def run_barcode_reading(self):
        if self.current_frame is None:
            return
        if zxingcpp is None:
            self.result_box.config(text="ZXING MISSING", bg=self.colors["red"], fg="white")
            self.reading_result_text.delete("1.0", tk.END)
            self.reading_result_text.insert(tk.END, "Run: pip install zxing-cpp\n")
            return
        start_time = time.time()
        frame = self.current_frame.copy()
        results = self.scan_barcode_from_frame(frame)
        detection_time = time.time() - start_time
        self.detect_time_lbl.config(text=f"Detection Time: {detection_time:.3f}s")
        self.reading_result_text.delete("1.0", tk.END)

        if results:
            self.result_box.config(text="BARCODE OK", bg=self.colors["green"], fg="white")
            first = results[0]
            value = str(first.text)
            fmt = str(first.format)
            self.reading_result_text.insert(tk.END, "Barcode Detected\n\n")
            self.reading_result_text.insert(tk.END, f"Format: {fmt}\nValue: {value}\n\n")
            for i, r in enumerate(results, start=1):
                self.reading_result_text.insert(tk.END, f"{i}. {r.format} : {r.text}\n")
            cv2.putText(frame, value[:40], (40, 80), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 255, 0), 3)
            cv2.imwrite(f"results/barcode/barcode_{time.strftime('%Y%m%d_%H%M%S')}.jpg", frame)
            self.add_history("OK", 100.0, detection_time, details=f"Barcode {fmt}: {value}")
        else:
            self.result_box.config(text="NO BARCODE", bg=self.colors["red"], fg="white")
            details = "No barcode / QR detected.\nDebug images saved in results/debug folder."
            self.reading_result_text.insert(tk.END, details)
            cv2.imwrite(f"results/barcode/not_detected_{time.strftime('%Y%m%d_%H%M%S')}.jpg", frame)
            self.add_history("NG", 0.0, detection_time, details=details)

        self.last_result_image = frame.copy()
        self.show_large_preview(frame)

    def run_ocr_reading(self):
        if self.current_frame is None:
            return
        if easyocr is None:
            self.result_box.config(text="OCR MISSING", bg=self.colors["red"], fg="white")
            self.reading_result_text.delete("1.0", tk.END)
            self.reading_result_text.insert(tk.END, "Run: pip install easyocr\n")
            return
        if self.ocr_reader is None:
            self.status_lbl.config(text="Loading OCR...", fg=self.colors["orange"])
            self.root.update()
            try:
                self.ocr_reader = easyocr.Reader(["en"], gpu=True, model_storage_directory="models", download_enabled=True)
                self.status_lbl.config(text="GPU OCR Loaded", fg=self.colors["green"])
            except Exception as e:
                print("GPU failed:", e)
                self.ocr_reader = easyocr.Reader(["en"], gpu=False)
                self.status_lbl.config(text="CPU OCR Loaded", fg=self.colors["red"])

        start_time = time.time()
        frame = self.current_frame.copy()
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        small = cv2.resize(gray, None, fx=0.5, fy=0.5)
        results = self.ocr_reader.readtext(small, detail=1, paragraph=False)
        display = cv2.cvtColor(small, cv2.COLOR_GRAY2BGR)
        detected_texts = []

        for bbox, text, score in results:
            if score > 0.45:
                detected_texts.append(text)
                pt1 = tuple(map(int, bbox[0]))
                pt2 = tuple(map(int, bbox[2]))
                cv2.rectangle(display, pt1, pt2, (0, 255, 0), 2)
                cv2.putText(display, text, (pt1[0], pt1[1] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

        detection_time = time.time() - start_time
        self.detect_time_lbl.config(text=f"Detection Time: {detection_time:.3f}s")
        if detected_texts:
            final_text = " ".join(detected_texts)
            self.result_box.config(text="OCR OK", bg=self.colors["green"], fg="white")
            self.reading_result_text.delete("1.0", tk.END)
            self.reading_result_text.insert(tk.END, final_text)
            self.add_history("OK", 100.0, detection_time, details=f"OCR: {final_text}")
            cv2.imwrite(f"results/ocr/ocr_{time.strftime('%Y%m%d_%H%M%S')}.jpg", display)
        else:
            self.result_box.config(text="NO OCR", bg=self.colors["red"], fg="white")
            self.reading_result_text.delete("1.0", tk.END)
            self.reading_result_text.insert(tk.END, "No text detected")
            self.add_history("NG", 0, detection_time, details="No text detected")

        current_time = time.time()
        if not hasattr(self, "prev_ocr_time"):
            self.prev_ocr_time = current_time
        fps = 1 / max(current_time - self.prev_ocr_time, 0.001)
        self.prev_ocr_time = current_time
        cv2.putText(display, f"FPS: {int(fps)}", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 0, 0), 2)
        self.last_result_image = display.copy()
        self.show_large_preview(display)

    def add_history(self, label, confidence, detection_time, details=""):
        if label == "OK":
            self.good_count += 1
        else:
            self.ng_count += 1
            if self.current_frame is not None:
                self.last_ng_frame = self.current_frame.copy()
                if self.is_unlocked:
                    self.show_small_image(self.last_ng_frame, self.ng_image_label, 300, 140)

        now = datetime.now()
        item = {
            "date": now.strftime("%Y-%m-%d"),
            "time": now.strftime("%H:%M:%S"),
            "mode": self.reading_mode,
            "result": label,
            "confidence": confidence,
            "detection_time": detection_time,
            "details": details.strip()
        }
        self.report_rows.append(item.copy())
        self.result_history.insert(0, item)
        self.result_history = self.result_history[:10]
        self.update_history()
        self.draw_result_dots()
        self.counter_lbl.config(text=f"Good: {self.good_count}\nNot Good: {self.ng_count}")

    def draw_result_dots(self):
        self.dot_canvas.delete("all")
        start_x = 35
        y1 = 20
        y2 = 45
        r = 8
        for i in range(10):
            if i < len(self.result_history):
                color = self.colors["green"] if self.result_history[i]["result"] == "OK" else self.colors["red"]
            else:
                color = "#fef3c7"
            x = start_x + (i % 5) * 45
            y = y1 if i < 5 else y2
            self.dot_canvas.create_oval(x - r, y - r, x + r, y + r, fill=color, outline=self.colors["header"])

    def update_history(self):
        if not hasattr(self, "history_text"):
            return
        self.history_text.delete("1.0", tk.END)
        self.history_text.insert(tk.END, "TIME      MODE      RESULT   CONF    TIME\n")
        self.history_text.insert(tk.END, "-" * 42 + "\n")
        for item in self.result_history:
            self.history_text.insert(
                tk.END,
                f"{item['time']}   {item['mode']:<8}  {item['result']:<5}   {item['confidence']:.2f}%  {item['detection_time']:.3f}s\n"
            )

    def get_report_days(self):
        selected = self.report_range_var.get()
        if selected == "1 Day":
            return 1
        if selected == "7 Days":
            return 7
        if selected == "15 Days":
            return 15
        if selected == "30 Days":
            return 30
        return None

    def get_report_range_label(self):
        selected = self.report_range_var.get()
        if selected == "All":
            return "All Data"
        return f"Last {selected}"

    def get_filtered_report_rows(self):
        days = self.get_report_days()
        if days is None:
            return list(self.report_rows)

        start_date = datetime.now().date() - timedelta(days=days - 1)
        filtered_rows = []
        for row in self.report_rows:
            try:
                row_date = datetime.strptime(row["date"], "%Y-%m-%d").date()
            except Exception:
                filtered_rows.append(row)
                continue
            if row_date >= start_date:
                filtered_rows.append(row)
        return filtered_rows

    def open_report_window(self):
        rows = self.get_filtered_report_rows()
        ok_count = sum(1 for row in rows if row["result"] == "OK")
        ng_count = sum(1 for row in rows if row["result"] != "OK")
        range_label = self.get_report_range_label()

        win = tk.Toplevel(self.root)
        win.title("Inspection Report")
        win.geometry("980x560")
        win.configure(bg=self.colors["app_bg"])

        top = tk.Frame(win, bg=self.colors["header"], height=58)
        top.pack(fill="x")
        top.pack_propagate(False)
        tk.Label(top, text="INSPECTION REPORT", bg=self.colors["header"], fg=self.colors["cream"], font=("Segoe UI", 18, "bold")).pack(side="left", padx=18)
        self.make_button(top, "Export Report", self.export_report, self.colors["orange"]).pack(side="right", padx=18, pady=10)

        range_bar = tk.Frame(win, bg=self.colors["panel"])
        range_bar.pack(fill="x", padx=14, pady=(14, 0))
        tk.Label(
            range_bar,
            text="Range:",
            bg=self.colors["panel"],
            fg=self.colors["muted"],
            font=("Segoe UI", 10, "bold")
        ).pack(side="left", padx=(12, 6), pady=8)
        for label in ["All", "1 Day", "7 Days", "15 Days", "30 Days"]:
            self.make_button(
                range_bar,
                label,
                lambda value=label, window=win: self.refresh_report_window(window, value),
                self.colors["orange"] if label == self.report_range_var.get() else self.colors["header"]
            ).pack(side="left", padx=4, pady=8)

        summary = tk.Label(
            win,
            text=f"Range: {range_label}    Total: {len(rows)}    Good: {ok_count}    Not Good: {ng_count}",
            bg=self.colors["panel"],
            fg=self.colors["text"],
            font=("Segoe UI", 12, "bold"),
            anchor="w",
            padx=14,
            pady=10
        )
        summary.pack(fill="x", padx=14, pady=(8, 0))

        frame = tk.Frame(win, bg=self.colors["panel"])
        frame.pack(fill="both", expand=True, padx=14, pady=14)
        text = tk.Text(frame, font=("Consolas", 10), bg=self.colors["input"], fg=self.colors["text"], relief="flat", bd=0)
        scroll = tk.Scrollbar(frame, command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        text.insert(tk.END, "DATE        TIME      MODE      RESULT   CONFIDENCE   DETECTION   DETAILS\n")
        text.insert(tk.END, "-" * 110 + "\n")
        for row in rows:
            details = row["details"].replace("\n", " ")[:80]
            text.insert(
                tk.END,
                f"{row['date']}  {row['time']}  {row['mode']:<8}  {row['result']:<6}  {row['confidence']:>8.2f}%  {row['detection_time']:>8.3f}s   {details}\n"
            )
        text.config(state="disabled")

    def refresh_report_window(self, window, range_value):
        self.report_range_var.set(range_value)
        window.destroy()
        self.open_report_window()

    def export_report(self):
        rows = self.get_filtered_report_rows()
        if not rows:
            messagebox.showinfo("Report", "No inspection data available for report.")
            return

        stamp = time.strftime("%Y%m%d_%H%M%S")
        range_name = self.report_range_var.get().lower().replace(" ", "_")
        csv_path = os.path.abspath(f"reports/inspection_report_{range_name}_{stamp}.csv")
        html_path = os.path.abspath(f"reports/inspection_report_{range_name}_{stamp}.html")
        ok_count = sum(1 for row in rows if row["result"] == "OK")
        ng_count = sum(1 for row in rows if row["result"] != "OK")
        range_label = self.get_report_range_label()

        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["date", "time", "mode", "result", "confidence", "detection_time", "details"])
            writer.writeheader()
            writer.writerows(rows)

        rows_html = "\n".join(
            "<tr>"
            f"<td>{escape(row['date'])}</td>"
            f"<td>{escape(row['time'])}</td>"
            f"<td>{escape(row['mode'])}</td>"
            f"<td class='{row['result'].lower()}'>{escape(row['result'])}</td>"
            f"<td>{row['confidence']:.2f}%</td>"
            f"<td>{row['detection_time']:.3f}s</td>"
            f"<td>{escape(row['details'])}</td>"
            "</tr>"
            for row in rows
        )

        html = f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Inspection Report</title>
<style>
body {{ font-family: Segoe UI, Arial, sans-serif; margin: 28px; color: #431407; background: #fff7ed; }}
h1 {{ color: #7c2d12; margin-bottom: 4px; }}
.summary {{ display: flex; gap: 18px; margin: 18px 0; }}
.box {{ background: #ffedd5; border: 1px solid #fb923c; padding: 12px 18px; border-radius: 8px; font-weight: 700; }}
table {{ width: 100%; border-collapse: collapse; background: #fffaf0; }}
th {{ background: #c2410c; color: white; text-align: left; }}
td, th {{ border: 1px solid #fdba74; padding: 8px; font-size: 13px; vertical-align: top; }}
.ok {{ color: #15803d; font-weight: 700; }}
.ng {{ color: #b91c1c; font-weight: 700; }}
</style>
</head>
<body>
<h1>Ingenious Techzoid Inspection Report</h1>
<div>Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</div>
<div>Range: {escape(range_label)}</div>
<div class="summary">
<div class="box">Total: {len(rows)}</div>
<div class="box">Good: {ok_count}</div>
<div class="box">Not Good: {ng_count}</div>
</div>
<table>
<thead><tr><th>Date</th><th>Time</th><th>Mode</th><th>Result</th><th>Confidence</th><th>Detection Time</th><th>Details</th></tr></thead>
<tbody>
{rows_html}
</tbody>
</table>
</body>
</html>"""
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)

        messagebox.showinfo("Report Saved", f"CSV Report:\n{csv_path}\n\nHTML Report:\n{html_path}")
        webbrowser.open(html_path)

    def clear_report_data(self):
        if messagebox.askyesno("Clear Report", "Clear all report rows and counters?"):
            self.good_count = 0
            self.ng_count = 0
            self.result_history.clear()
            self.report_rows.clear()
            self.counter_lbl.config(text="Good: 0\nNot Good: 0")
            self.update_history()
            self.draw_result_dots()
            self.result_box.config(text="WAIT", bg=self.colors["panel_3"], fg=self.colors["text"])
            self.status_lbl.config(text="Status: Report data cleared", fg=self.colors["orange"])

    def reset_counter(self):
        self.good_count = 0
        self.ng_count = 0
        self.result_history.clear()
        self.circle_burst_results = []
        self.circle_final_result_locked = False
        self.previous_radii = []
        self.counter_lbl.config(text="Good: 0\nNot Good: 0")
        self.result_box.config(text="WAIT", bg=self.colors["panel_3"], fg=self.colors["text"])
        self.detect_time_lbl.config(text="Detection Time: 0.000s")
        self.circle_status_lbl.config(text="")
        self.reading_result_text.delete("1.0", tk.END)
        self.reading_result_text.insert(tk.END, "Barcode / OCR value will appear here...")
        self.update_history()
        self.draw_result_dots()

    def save_result_image(self):
        if self.last_result_image is not None:
            img = self.last_result_image
        elif self.current_frame is not None:
            img = self.current_frame
        else:
            messagebox.showwarning("Warning", "No image to save")
            return
        filename = f"results/result_{time.strftime('%Y%m%d_%H%M%S')}.jpg"
        cv2.imwrite(filename, img)
        messagebox.showinfo("Saved", f"Image saved:\n{filename}")

    def on_close(self):
        self.stop_camera()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = OKNGSoftware(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()
