import os
import cv2
import yaml
import shutil
import random
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from PIL import Image, ImageTk

try:
    from ultralytics import YOLO
except Exception:
    YOLO = None


# ================= GLOBALS =================

image_folder = ""
image_files = []
current_index = 0

classes = []
boxes = []  # [class_id, x1, y1, x2, y2]

drawing = False
start_x, start_y = 0, 0
current_image = None
display_image = None

scale_x = 1
scale_y = 1

ANNOTATION_DIR = "annotations"
DATASET_DIR = "yolo_dataset"

COLORS = {
    "app_bg": "#fff7ed",
    "panel": "#ffedd5",
    "panel_2": "#fed7aa",
    "panel_3": "#fdba74",
    "border": "#fb923c",
    "text": "#431407",
    "muted": "#9a3412",
    "green": "#16a34a",
    "red": "#dc2626",
    "orange": "#c2410c",
    "orange_2": "#ea580c",
    "amber": "#f59e0b",
    "purple": "#b45309",
    "input": "#fffaf0",
    "white": "#ffffff",
    "header": "#7c2d12",
    "cream": "#fffaf0",
}

training_running = False


# ================= UI HELPERS =================

def lighten_color(color):
    color = color.lstrip("#")
    if len(color) != 6:
        return color
    r = min(int(color[0:2], 16) + 24, 255)
    g = min(int(color[2:4], 16) + 18, 255)
    b = min(int(color[4:6], 16) + 10, 255)
    return f"#{r:02x}{g:02x}{b:02x}"


def make_button(parent, text, command, bg=None, fg=None, width=None, height=None):
    bg = bg or COLORS["orange"]
    btn = tk.Button(
        parent,
        text=text,
        command=command,
        bg=bg,
        fg=fg or COLORS["white"],
        activebackground=lighten_color(bg),
        activeforeground=COLORS["white"],
        relief="flat",
        bd=0,
        cursor="hand2",
        font=("Segoe UI", 10, "bold"),
        padx=12,
        pady=9,
        width=width,
        height=height,
        takefocus=False
    )
    btn.default_bg = bg
    btn.bind("<Enter>", lambda event: btn.config(bg=lighten_color(btn.default_bg)))
    btn.bind("<Leave>", lambda event: btn.config(bg=btn.default_bg))
    return btn


def make_panel(parent, title):
    return tk.LabelFrame(
        parent,
        text=f"  {title}  ",
        font=("Segoe UI", 10, "bold"),
        bg=COLORS["panel"],
        fg=COLORS["text"],
        bd=1,
        relief="solid",
        highlightthickness=1,
        highlightbackground=COLORS["border"],
        labelanchor="n",
        padx=10,
        pady=10
    )


def make_scroll_area(panel):
    holder = tk.Frame(panel, bg=COLORS["panel"])
    holder.pack(fill="both", expand=True)

    canvas = tk.Canvas(holder, bg=COLORS["panel"], bd=0, highlightthickness=0)
    scrollbar = tk.Scrollbar(
        holder,
        orient="vertical",
        command=canvas.yview,
        bg=COLORS["panel_3"],
        troughcolor=COLORS["cream"],
        activebackground=COLORS["border"],
        relief="flat",
        width=14
    )
    body = tk.Frame(canvas, bg=COLORS["panel"])
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


def style_entry(entry):
    entry.configure(
        bg=COLORS["input"],
        fg=COLORS["text"],
        insertbackground=COLORS["text"],
        relief="flat",
        bd=0,
        font=("Segoe UI", 10)
    )
    return entry


def safe_ui(callback):
    root.after(0, callback)


def show_info(title, message):
    safe_ui(lambda: messagebox.showinfo(title, message))


def show_error(title, message):
    safe_ui(lambda: messagebox.showerror(title, message))


def set_training_progress(value, status=None):
    value = max(0, min(100, int(value)))

    def update():
        training_progress_var.set(value)
        training_percent_label.config(text=f"{value}%")
        if status:
            training_status_label.config(text=status)

    safe_ui(update)


def set_training_button_state(is_running):
    def update():
        start_training_btn.config(state="disabled" if is_running else "normal")
        create_dataset_btn.config(state="disabled" if is_running else "normal")

    safe_ui(update)


# ================= HELPERS =================

def log(msg):
    def update():
        log_box.insert(tk.END, msg + "\n")
        log_box.see(tk.END)
    safe_ui(update)


def load_classes():
    global classes

    cls_text = class_entry.get().strip()
    if not cls_text:
        messagebox.showerror("Error", "Please enter class names")
        return False

    classes = [c.strip() for c in cls_text.split(",") if c.strip()]
    class_list_box.delete(0, tk.END)

    for c in classes:
        class_list_box.insert(tk.END, c)

    log(f"Classes loaded: {classes}")
    return True


def select_folder():
    global image_folder, image_files, current_index

    image_folder = filedialog.askdirectory(title="Select Image Folder")
    if not image_folder:
        return

    image_files = [
        f for f in os.listdir(image_folder)
        if f.lower().endswith((".jpg", ".jpeg", ".png", ".bmp"))
    ]
    image_files.sort()
    current_index = 0

    if not image_files:
        messagebox.showerror("Error", "No images found in folder")
        return

    os.makedirs(ANNOTATION_DIR, exist_ok=True)
    folder_label.config(text=image_folder)
    log(f"Loaded {len(image_files)} images")
    load_image()


def load_image():
    global current_image, display_image, boxes

    if not image_files:
        return

    img_path = os.path.join(image_folder, image_files[current_index])
    current_image = cv2.imread(img_path)
    if current_image is None:
        log(f"Could not load image: {img_path}")
        return

    boxes = load_existing_annotation(img_path)
    image_name_label.config(
        text=f"{current_index + 1}/{len(image_files)} - {image_files[current_index]}"
    )
    show_image()


def show_image(temp_box=None):
    global display_image, scale_x, scale_y

    if current_image is None:
        return

    img = current_image.copy()
    h, w = img.shape[:2]

    for box in boxes:
        cls_id, x1, y1, x2, y2 = box
        color = (0, 180, 0)
        cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
        label = classes[cls_id] if cls_id < len(classes) else str(cls_id)
        cv2.putText(img, label, (x1, max(y1 - 8, 20)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

    if temp_box:
        x1, y1, x2, y2 = temp_box
        cv2.rectangle(img, (x1, y1), (x2, y2), (255, 120, 0), 2)

    canvas_w = preview_canvas.winfo_width()
    canvas_h = preview_canvas.winfo_height()
    if canvas_w <= 1:
        canvas_w = 900
    if canvas_h <= 1:
        canvas_h = 600

    scale = min(canvas_w / w, canvas_h / h)
    new_w = max(1, int(w * scale))
    new_h = max(1, int(h * scale))

    scale_x = w / new_w
    scale_y = h / new_h

    resized = cv2.resize(img, (new_w, new_h))
    resized = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)

    pil_img = Image.fromarray(resized)
    display_image = ImageTk.PhotoImage(pil_img)

    preview_canvas.delete("all")
    preview_canvas.create_image(canvas_w // 2, canvas_h // 2, image=display_image, anchor="center")
    preview_canvas.create_rectangle(
        (canvas_w - new_w) // 2,
        (canvas_h - new_h) // 2,
        (canvas_w + new_w) // 2,
        (canvas_h + new_h) // 2,
        outline=COLORS["border"],
        width=2
    )

    preview_canvas.image_x = (canvas_w - new_w) // 2
    preview_canvas.image_y = (canvas_h - new_h) // 2
    preview_canvas.image_w = new_w
    preview_canvas.image_h = new_h


def get_canvas_image_xy(event):
    img_x = getattr(preview_canvas, "image_x", 0)
    img_y = getattr(preview_canvas, "image_y", 0)
    img_w = getattr(preview_canvas, "image_w", 1)
    img_h = getattr(preview_canvas, "image_h", 1)

    x = event.x - img_x
    y = event.y - img_y

    if x < 0 or y < 0 or x > img_w or y > img_h:
        return None, None

    return int(x * scale_x), int(y * scale_y)


def mouse_down(event):
    global drawing, start_x, start_y

    if current_image is None:
        return

    x, y = get_canvas_image_xy(event)
    if x is None:
        return

    drawing = True
    start_x, start_y = x, y


def mouse_move(event):
    if not drawing:
        return

    x, y = get_canvas_image_xy(event)
    if x is None:
        return

    show_image((start_x, start_y, x, y))


def choose_class_popup():
    if not classes:
        messagebox.showerror("Error", "Please load classes first")
        return None

    popup = tk.Toplevel(root)
    popup.title("Select Class")
    popup.geometry("280x330")
    popup.configure(bg=COLORS["app_bg"])
    popup.resizable(False, False)
    popup.grab_set()

    selected_class = {"id": None}

    tk.Label(
        popup,
        text="Select class for this box",
        font=("Segoe UI", 11, "bold"),
        bg=COLORS["app_bg"],
        fg=COLORS["text"]
    ).pack(pady=(16, 8))

    listbox = tk.Listbox(
        popup,
        height=9,
        font=("Segoe UI", 10),
        bg=COLORS["input"],
        fg=COLORS["text"],
        selectbackground=COLORS["orange_2"],
        selectforeground=COLORS["white"],
        relief="flat",
        bd=0
    )
    listbox.pack(fill="both", expand=True, padx=18, pady=6)

    for cls in classes:
        listbox.insert(tk.END, cls)
    listbox.selection_set(0)

    def confirm():
        sel = listbox.curselection()
        if not sel:
            messagebox.showwarning("Warning", "Please select class")
            return
        selected_class["id"] = sel[0]
        popup.destroy()

    make_button(popup, "OK", confirm, COLORS["green"], width=16).pack(pady=14)
    popup.bind("<Return>", lambda event: confirm())
    popup.wait_window()
    return selected_class["id"]


def mouse_up(event):
    global drawing

    if not drawing:
        return

    drawing = False
    x, y = get_canvas_image_xy(event)

    if x is None:
        show_image()
        return

    x1, y1 = min(start_x, x), min(start_y, y)
    x2, y2 = max(start_x, x), max(start_y, y)

    if abs(x2 - x1) < 10 or abs(y2 - y1) < 10:
        show_image()
        return

    cls_id = choose_class_popup()
    if cls_id is None:
        show_image()
        return

    boxes.append([cls_id, x1, y1, x2, y2])
    show_image()
    log(f"Box added: {classes[cls_id]} [{x1}, {y1}, {x2}, {y2}]")


def save_annotation():
    if current_image is None:
        return

    os.makedirs(ANNOTATION_DIR, exist_ok=True)
    img_path = os.path.join(image_folder, image_files[current_index])
    img_name = os.path.splitext(os.path.basename(img_path))[0]
    txt_path = os.path.join(ANNOTATION_DIR, img_name + ".txt")

    h, w = current_image.shape[:2]
    with open(txt_path, "w", encoding="utf-8") as f:
        for box in boxes:
            cls_id, x1, y1, x2, y2 = box
            cx = ((x1 + x2) / 2) / w
            cy = ((y1 + y2) / 2) / h
            bw = (x2 - x1) / w
            bh = (y2 - y1) / h
            f.write(f"{cls_id} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}\n")

    log(f"Saved annotation: {txt_path}")


def load_existing_annotation(img_path):
    if current_image is None:
        return []

    img_name = os.path.splitext(os.path.basename(img_path))[0]
    txt_path = os.path.join(ANNOTATION_DIR, img_name + ".txt")

    if not os.path.exists(txt_path):
        return []

    h, w = current_image.shape[:2]
    loaded_boxes = []

    with open(txt_path, "r", encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) != 5:
                continue

            cls_id = int(parts[0])
            cx, cy, bw, bh = map(float, parts[1:])
            x1 = int((cx - bw / 2) * w)
            y1 = int((cy - bh / 2) * h)
            x2 = int((cx + bw / 2) * w)
            y2 = int((cy + bh / 2) * h)
            loaded_boxes.append([cls_id, x1, y1, x2, y2])

    return loaded_boxes


def next_image():
    global current_index

    if not image_files:
        return

    save_annotation()
    if current_index < len(image_files) - 1:
        current_index += 1
        load_image()


def prev_image():
    global current_index

    if not image_files:
        return

    save_annotation()
    if current_index > 0:
        current_index -= 1
        load_image()


def undo_box():
    if boxes:
        boxes.pop()
        show_image()
        log("Last box removed")


def clear_boxes():
    boxes.clear()
    show_image()
    log("Boxes cleared for current image")


# ================= DATASET SPLIT =================

def create_dataset():
    if not image_folder:
        messagebox.showerror("Error", "Select image folder first")
        return

    if not load_classes():
        return

    save_annotation()

    try:
        train_ratio = float(train_entry.get())
        val_ratio = float(val_entry.get())
        test_ratio = float(test_entry.get())
    except ValueError:
        messagebox.showerror("Error", "Train/Val/Test ratio must be numbers")
        return

    total = train_ratio + val_ratio + test_ratio
    if round(total, 2) != 1.0:
        messagebox.showerror("Error", "Train + Val + Test ratio must be 1.0")
        return

    if os.path.exists(DATASET_DIR):
        shutil.rmtree(DATASET_DIR)

    folders = [
        "images/train", "images/val", "images/test",
        "labels/train", "labels/val", "labels/test"
    ]

    for folder in folders:
        os.makedirs(os.path.join(DATASET_DIR, folder), exist_ok=True)

    all_imgs = image_files.copy()
    random.shuffle(all_imgs)

    train_end = int(len(all_imgs) * train_ratio)
    val_end = train_end + int(len(all_imgs) * val_ratio)

    split_data = {
        "train": all_imgs[:train_end],
        "val": all_imgs[train_end:val_end],
        "test": all_imgs[val_end:]
    }

    for split, files in split_data.items():
        for img_file in files:
            src_img = os.path.join(image_folder, img_file)
            img_name = os.path.splitext(img_file)[0]
            src_lbl = os.path.join(ANNOTATION_DIR, img_name + ".txt")

            dst_img = os.path.join(DATASET_DIR, "images", split, img_file)
            dst_lbl = os.path.join(DATASET_DIR, "labels", split, img_name + ".txt")

            shutil.copy(src_img, dst_img)

            if os.path.exists(src_lbl):
                shutil.copy(src_lbl, dst_lbl)
            else:
                open(dst_lbl, "w", encoding="utf-8").close()

    data_yaml = {
        "path": os.path.abspath(DATASET_DIR),
        "train": "images/train",
        "val": "images/val",
        "test": "images/test",
        "names": classes
    }

    yaml_path = os.path.join(DATASET_DIR, "data.yaml")
    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.dump(data_yaml, f, sort_keys=False)

    log("Dataset created successfully")
    log(f"Train: {len(split_data['train'])}")
    log(f"Val: {len(split_data['val'])}")
    log(f"Test: {len(split_data['test'])}")
    log(f"YAML: {yaml_path}")
    messagebox.showinfo("Success", "YOLO dataset created successfully")


# ================= YOLO TRAINING =================

def train_yolo_thread():
    global training_running

    if training_running:
        messagebox.showinfo("Training", "Training is already running")
        return

    training_running = True
    set_training_button_state(True)
    set_training_progress(0, "Preparing training...")
    threading.Thread(target=train_yolo, daemon=True).start()


def train_yolo():
    global training_running

    try:
        if YOLO is None:
            show_error("Error", "Ultralytics not installed")
            return

        yaml_path = os.path.join(DATASET_DIR, "data.yaml")
        if not os.path.exists(yaml_path):
            show_error("Error", "Create dataset first")
            return

        try:
            epochs = int(epoch_entry.get())
            imgsz = int(img_size_entry.get())
            batch = int(batch_entry.get())
            model_name = model_entry.get().strip() or "yolov8n.pt"
        except ValueError:
            show_error("Error", "Epochs, image size, and batch must be numbers")
            return

        log("Training started...")
        log(f"Model: {model_name}")
        log(f"Epochs: {epochs}")
        log(f"Image Size: {imgsz}")
        log(f"Batch: {batch}")
        set_training_progress(3, "Loading model...")

        model = YOLO(model_name)

        def on_train_epoch_end(trainer):
            epoch = getattr(trainer, "epoch", 0) + 1
            total_epochs = max(epochs, 1)
            percent = 5 + int((epoch / total_epochs) * 94)
            set_training_progress(percent, f"Training epoch {epoch}/{total_epochs}...")
            log(f"Epoch complete: {epoch}/{total_epochs}")

        try:
            model.add_callback("on_train_epoch_end", on_train_epoch_end)
        except Exception:
            log("Progress callback not available; completion will still be shown.")

        set_training_progress(5, "Training running...")

        model.train(
            data=yaml_path,
            epochs=epochs,
            imgsz=imgsz,
            batch=batch,
            project="runs",
            name="custom_yolov8_train"
        )

        set_training_progress(100, "Training completed")
        log("Training completed successfully")
        show_info("Done", "YOLOv8 training completed")

    except Exception as e:
        log(f"Training error: {e}")
        set_training_progress(0, "Training failed")
        show_error("Error", str(e))
    finally:
        training_running = False
        set_training_button_state(False)


# ================= UI =================

root = tk.Tk()
root.title("Ingenious Techzoid - YOLOv8 Annotation & Training")
root.geometry("1380x820")
root.minsize(1180, 720)
root.configure(bg=COLORS["app_bg"])

style = ttk.Style()
style.theme_use("default")
style.configure(
    "Orange.Horizontal.TProgressbar",
    troughcolor=COLORS["input"],
    background=COLORS["orange_2"],
    bordercolor=COLORS["border"],
    lightcolor=COLORS["orange_2"],
    darkcolor=COLORS["orange"]
)

header = tk.Frame(root, bg=COLORS["header"], height=70)
header.pack(fill="x")
header.pack_propagate(False)

tk.Label(
    header,
    text="INGENIOUS TECHZOID",
    font=("Segoe UI", 23, "bold"),
    bg=COLORS["header"],
    fg=COLORS["cream"]
).pack(side="left", padx=(28, 10))

tk.Label(
    header,
    text="YOLOv8 Annotation & Training",
    font=("Segoe UI", 12, "bold"),
    bg=COLORS["header"],
    fg="#fde68a"
).pack(side="right", padx=28)

main_frame = tk.Frame(root, bg=COLORS["app_bg"])
main_frame.pack(fill="both", expand=True, padx=14, pady=14)

control_shell = make_panel(main_frame, "Controls")
control_shell.pack(side="left", fill="y", padx=(0, 12))
control_shell.configure(width=340)
control_shell.pack_propagate(False)
control_frame = make_scroll_area(control_shell)

preview_frame = make_panel(main_frame, "Image Preview / Annotation Screen")
preview_frame.pack(side="right", fill="both", expand=True)

# Folder
make_button(control_frame, "Select Image Folder", select_folder, COLORS["orange_2"], width=26, height=1).pack(fill="x", pady=(2, 8))

folder_label = tk.Label(
    control_frame,
    text="No folder selected",
    bg=COLORS["cream"],
    fg=COLORS["muted"],
    wraplength=280,
    font=("Segoe UI", 8),
    padx=8,
    pady=8,
    anchor="w",
    justify="left"
)
folder_label.pack(fill="x", pady=(0, 10))

# Classes
tk.Label(control_frame, text="Classes comma separated", bg=COLORS["panel"], fg=COLORS["muted"], font=("Segoe UI", 9, "bold")).pack(anchor="w")
class_entry = style_entry(tk.Entry(control_frame))
class_entry.pack(fill="x", pady=(3, 6), ipady=7)
class_entry.insert(0, "OK,NG,screw,missing")

make_button(control_frame, "Load Classes", load_classes, COLORS["green"], width=26).pack(fill="x", pady=4)

class_list_box = tk.Listbox(
    control_frame,
    height=4,
    bg=COLORS["input"],
    fg=COLORS["text"],
    selectbackground=COLORS["orange_2"],
    selectforeground=COLORS["white"],
    relief="flat",
    bd=0,
    font=("Segoe UI", 9)
)
class_list_box.pack(fill="x", pady=(5, 8))

# Navigation
nav_frame = tk.Frame(control_frame, bg=COLORS["panel"])
nav_frame.pack(fill="x", pady=3)
make_button(nav_frame, "Previous", prev_image, COLORS["header"], width=12).pack(side="left", fill="x", expand=True, padx=(0, 4))
make_button(nav_frame, "Next", next_image, COLORS["header"], width=12).pack(side="right", fill="x", expand=True, padx=(4, 0))

make_button(control_frame, "Save Annotation", save_annotation, COLORS["purple"], width=26).pack(fill="x", pady=4)
make_button(control_frame, "Undo Last Box", undo_box, COLORS["amber"], width=26).pack(fill="x", pady=4)
make_button(control_frame, "Clear Boxes", clear_boxes, COLORS["red"], width=26).pack(fill="x", pady=4)

# Dataset split
tk.Label(control_frame, text="Dataset Split", bg=COLORS["panel"], fg=COLORS["text"], font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(12, 4))

split_frame = tk.Frame(control_frame, bg=COLORS["panel"])
split_frame.pack(fill="x")

for idx, label in enumerate(["Train", "Val", "Test"]):
    tk.Label(split_frame, text=label, bg=COLORS["panel"], fg=COLORS["muted"], font=("Segoe UI", 9, "bold")).grid(row=0, column=idx, sticky="w")

train_entry = style_entry(tk.Entry(split_frame, width=8))
val_entry = style_entry(tk.Entry(split_frame, width=8))
test_entry = style_entry(tk.Entry(split_frame, width=8))
train_entry.grid(row=1, column=0, padx=(0, 6), ipady=6, sticky="ew")
val_entry.grid(row=1, column=1, padx=3, ipady=6, sticky="ew")
test_entry.grid(row=1, column=2, padx=(6, 0), ipady=6, sticky="ew")
split_frame.columnconfigure((0, 1, 2), weight=1)

train_entry.insert(0, "0.7")
val_entry.insert(0, "0.2")
test_entry.insert(0, "0.1")

create_dataset_btn = make_button(control_frame, "Create YOLO Dataset", create_dataset, COLORS["orange"], width=26)
create_dataset_btn.pack(fill="x", pady=8)

# Training
tk.Label(control_frame, text="YOLOv8 Training", bg=COLORS["panel"], fg=COLORS["text"], font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(8, 4))

train_opt_frame = tk.Frame(control_frame, bg=COLORS["panel"])
train_opt_frame.pack(fill="x")

labels = ["Model", "Epochs", "Img Size", "Batch"]
for row, label in enumerate(labels):
    tk.Label(train_opt_frame, text=label, bg=COLORS["panel"], fg=COLORS["muted"], font=("Segoe UI", 9, "bold")).grid(row=row, column=0, sticky="w", pady=3)

model_entry = style_entry(tk.Entry(train_opt_frame))
epoch_entry = style_entry(tk.Entry(train_opt_frame))
img_size_entry = style_entry(tk.Entry(train_opt_frame))
batch_entry = style_entry(tk.Entry(train_opt_frame))

for row, entry in enumerate([model_entry, epoch_entry, img_size_entry, batch_entry]):
    entry.grid(row=row, column=1, sticky="ew", padx=(8, 0), pady=3, ipady=5)

train_opt_frame.columnconfigure(1, weight=1)
model_entry.insert(0, "yolov8n.pt")
epoch_entry.insert(0, "50")
img_size_entry.insert(0, "640")
batch_entry.insert(0, "8")

start_training_btn = make_button(control_frame, "Start Training", train_yolo_thread, COLORS["green"], width=26, height=1)
start_training_btn.pack(fill="x", pady=(10, 8))

progress_frame = tk.Frame(control_frame, bg=COLORS["panel"])
progress_frame.pack(fill="x", pady=(0, 8))

training_status_label = tk.Label(
    progress_frame,
    text="Training not started",
    bg=COLORS["panel"],
    fg=COLORS["muted"],
    font=("Segoe UI", 9, "bold"),
    anchor="w"
)
training_status_label.pack(side="left", fill="x", expand=True)

training_percent_label = tk.Label(
    progress_frame,
    text="0%",
    bg=COLORS["panel"],
    fg=COLORS["orange"],
    font=("Segoe UI", 10, "bold")
)
training_percent_label.pack(side="right")

training_progress_var = tk.IntVar(value=0)
training_progress = ttk.Progressbar(
    control_frame,
    variable=training_progress_var,
    maximum=100,
    mode="determinate",
    style="Orange.Horizontal.TProgressbar"
)
training_progress.pack(fill="x", pady=(0, 10))

# Log
tk.Label(control_frame, text="Log", bg=COLORS["panel"], fg=COLORS["text"], font=("Segoe UI", 10, "bold")).pack(anchor="w")
log_box = tk.Text(
    control_frame,
    height=8,
    width=36,
    font=("Consolas", 8),
    bg=COLORS["input"],
    fg=COLORS["text"],
    insertbackground=COLORS["text"],
    relief="flat",
    bd=0
)
log_box.pack(fill="both", expand=True, pady=(4, 0))

# Preview
image_name_label = tk.Label(
    preview_frame,
    text="No Image Loaded",
    bg=COLORS["panel"],
    fg=COLORS["text"],
    font=("Segoe UI", 12, "bold")
)
image_name_label.pack(fill="x", pady=(0, 6))

preview_canvas = tk.Canvas(
    preview_frame,
    bg=COLORS["cream"],
    width=950,
    height=650,
    cursor="cross",
    bd=0,
    highlightthickness=1,
    highlightbackground=COLORS["border"]
)
preview_canvas.pack(fill="both", expand=True, padx=2, pady=2)

preview_canvas.bind("<ButtonPress-1>", mouse_down)
preview_canvas.bind("<B1-Motion>", mouse_move)
preview_canvas.bind("<ButtonRelease-1>", mouse_up)
preview_canvas.bind("<Configure>", lambda event: show_image())

load_classes()
root.mainloop()
