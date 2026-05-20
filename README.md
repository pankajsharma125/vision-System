Ingenious Techzoid Vision Inspection Software
Industrial vision inspection tools for AI OK/NG detection, barcode/QR reading, OCR reading, size detection, annotation, dataset creation, and YOLOv8 model training.

Software Included
1. OK/NG Inspection Software
File: okng_software_secure.py

Main inspection application with:

Hikrobot/MVS industrial camera support
Live camera preview
AI OK/NG inspection using YOLO models
Barcode and QR reading
OCR text reading
Circle/size detection
Trigger mode and continuous camera mode
Good/Not Good counters
Last 10 result history
Last NG image preview
CSV and HTML report export
Password protected advanced mode
Password stored as encrypted hash instead of plain text
Default advanced-mode password:

4036
2. YOLO Annotation and Training Tool
File: yolo_annotation_training_orange.py

Training utility with:

Image folder loading
Manual bounding-box annotation
Class selection popup
YOLO .txt annotation save/load
Train/validation/test dataset split
data.yaml creation
YOLOv8 training from the UI
Training progress bar with percentage
Orange themed UI with scrollable left control panel
Requirements
Install Python 3.9 or newer.

Install dependencies:

pip install -r requirements.txt
For Hikrobot camera support, install the official MVS SDK and make sure this SDK path exists:

C:\Program Files (x86)\MVS\Development\Samples\Python\MvImport
If MVS SDK is not installed, non-camera features may still open, but camera functions will fail.

How To Run
Run the inspection software:

python okng_software_secure.py
Run the annotation and training tool:

python yolo_annotation_training_orange.py
Folder Output
The inspection software creates these folders automatically:

results/
results/ng/
results/trigger/
results/barcode/
results/ocr/
results/debug/
results/uploaded/
results/circle/
reports/
The training tool creates:

annotations/
yolo_dataset/
runs/
Basic Workflow
Use yolo_annotation_training_orange.py to annotate images.
Create a YOLO dataset from the UI.
Train a YOLOv8 model.
Use the trained model in okng_software_secure.py.
Run inspection using camera or uploaded images.
Export reports when needed.
Notes
ultralytics, easyocr, and zxing-cpp are optional at import time, but required for their respective features.
OCR may run on GPU if supported; otherwise it falls back to CPU.
Camera features require Hikrobot/MVS SDK and compatible camera hardware.
Reports are exported as both CSV and HTML.
