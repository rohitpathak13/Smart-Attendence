# Face Recognition Based Attendance Monitoring System

A Python-based desktop application that automates attendance using facial recognition technology. The system captures student face images, trains an LBPH (Local Binary Pattern Histogram) face recognition model, and records attendance automatically through a webcam. Attendance records are stored in CSV format, providing an efficient and contactless alternative to manual attendance systems. The application includes a graphical user interface (GUI) built with Tkinter for easy interaction. The project performs face detection, image collection, model training, and attendance tracking. :contentReference[oaicite:0]{index=0} :contentReference[oaicite:1]{index=1}

---

## Features

- Student registration with unique ID and name
- Face image capture using webcam
- Face detection using Haar Cascade Classifier
- Face recognition using LBPH Face Recognizer
- Automatic attendance marking
- Attendance stored in CSV files
- Password protection for training the recognition model
- User-friendly graphical interface built with Tkinter
- Displays attendance records in real time

---

## Technologies Used

- Python 3.x
- OpenCV
- Tkinter
- NumPy
- Pandas
- Pillow (PIL)

---

## Project Structure

```
Face-Recognition-Based-Attendance-Monitoring-System/
│
├── main.py
├── haarcascade_frontalface_default.xml
├── TrainingImage/
├── TrainingImageLabel/
├── StudentDetails/
├── Attendance/
└── README.md
```

---

## Installation

### 1. Clone the Repository

```bash
git clone https://github.com/your-username/Face-Recognition-Based-Attendance-Monitoring-System.git
cd Face-Recognition-Based-Attendance-Monitoring-System
```

### 2. Install Required Libraries

```bash
pip install opencv-contrib-python
pip install numpy
pip install pandas
pip install pillow
```

Or install all dependencies at once:

```bash
pip install opencv-contrib-python numpy pandas pillow
```

---

## How to Run

Run the application using:

```bash
python main.py
```

---

## Working Procedure

### Step 1: Register Student

- Enter Student ID.
- Enter Student Name.
- Click **Take Images**.
- Around 100 face images will be captured and saved.

### Step 2: Train the Model

- Click **Save Profile**.
- Enter the training password if prompted.
- The system trains the LBPH face recognition model.

### Step 3: Mark Attendance

- Click **Take Attendance**.
- The webcam detects and recognizes registered faces.
- Attendance is automatically recorded with:
  - Student ID
  - Student Name
  - Date
  - Time

---

## Output

Attendance files are generated automatically inside the **Attendance** folder.

Example:

```
Attendance/
└── Attendance_25-07-2026.csv
```

Student details are stored in:

```
StudentDetails/
└── StudentDetails.csv
```

The trained recognition model is saved in:

```
TrainingImageLabel/
└── Trainner.yml
```

---

## Dependencies

- OpenCV (opencv-contrib-python)
- NumPy
- Pandas
- Pillow
- Tkinter (Included with Python)

---

## Future Enhancements

- MySQL/Firebase database integration
- Deep learning-based face recognition
- Web-based attendance portal
- Email and SMS notifications
- QR Code attendance support
- Cloud storage integration
- Multi-camera support
- Attendance analytics dashboard

---

## License

This project is intended for educational and academic purposes.

---

## Acknowledgements

- OpenCV Documentation
- Python Documentation
- NumPy Documentation
- Pandas Documentation
- Pillow Documentation

---

## Author

**Face Recognition Based Attendance Monitoring System**

Developed using **Python**, **OpenCV**, and **Tkinter** for automated attendance management.