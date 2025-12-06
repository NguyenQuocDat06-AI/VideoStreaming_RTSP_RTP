
# Video Streaming Application (RTSP & RTP)

This project demonstrates a **Real-Time Video Streaming System** implemented in Python. It uses the **RTSP** (Real-Time Streaming Protocol) for session control and **RTP** (Real-Time Transport Protocol) for transmitting **MJPEG** video data.

## 📦 Prerequisites

Before running the application, ensure you have **Python 3.x** installed.

### 1. Install Dependencies
The project uses the `Pillow` library to handle image processing.

```bash
pip install Pillow
````

### 2\. Download Video Assets (Required)

The application requires specific `.Mjpeg` video files to function correctly. You must download these files manually if they are not present in your folder.

📥 **[Download MJPEG Video Files (Google Drive)](https://drive.google.com/drive/folders/1m8ZY1JiYOXiQIrgd0CRz3JWyM8agRPmz?usp=drive_link)**

> **⚠️ Important:** After downloading, extract or move the files (e.g., `movie.Mjpeg`, `4K.Mjpeg`) directly into the **root folder** of this project (the same folder where `Server.py` is located).

-----

## 🚀 How to Run (Manual Method)

To stream video, you need to open two terminal windows: one for the **Server** and one for the **Client**.

### Step 1: Start the Server

Open your terminal (Command Prompt or Git Bash) and run the `Server.py` script. You need to specify a port number (port must be greater than 1024).

**Syntax:**

```bash
python Server.py <server_port>
```

**Example:**

```bash
python Server.py 5555
```

*The server is now listening for incoming RTSP connections on port 5555.*

### Step 2: Start the Client

Open a **new** terminal window (keep the server running in the first one) and run the `ClientLauncher.py` script.

**Syntax:**

```bash
python ClientLauncher.py <server_host> <server_port> <RTP_port> <video_file>
```

**Parameters:**

  * `<server_host>`: The IP address of the server. Use `localhost` or `127.0.0.1` for local testing.
  * `<server_port>`: The port the Server is listening on (must match the port used in Step 1).
  * `<RTP_port>`: The local port where the Client will receive the video stream (e.g., `5600`).
  * `<video_file>`: The name of the video file to request (e.g., `movie.Mjpeg`).

**Example:**

```bash
python ClientLauncher.py localhost 5555 5600 movie.Mjpeg
