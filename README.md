# 🎥 Video Streaming with RTSP and RTP

## Tổng Quan Đồ Án

Đồ án streaming video sử dụng giao thức RTSP (Real-Time Streaming Protocol) để điều khiển và RTP (Real-time Transport Protocol) để truyền tải dữ liệu video.

### Điểm Nổi Bật

✅ **RTSP Protocol** - Implement đầy đủ SETUP, PLAY, PAUSE, TEARDOWN  
✅ **RTP Packetization** - Đóng gói video frames theo chuẩn RFC 3550  
✅ **HD/4K Support** - MTU-aware fragmentation cho large frames  
✅ **Client-Side Caching** - Buffer 40 frames để giảm jitter  
✅ **Statistics Tracking** - Monitor bandwidth, packets, FPS real-time  
✅ **Multi-threading** - Tách biệt network và display threads  

---

## 📋 Yêu Cầu Hệ Thống

### Python Version
- Python 3.7 trở lên

### Dependencies
```bash
pip install pillow
```

### Cấu Trúc File
```
project/
├── Client.py           # Client implementation
├── ClientLauncher.py   # Client startup script
├── Server.py           # Server main
├── ServerWorker.py     # Server worker thread
├── RtpPacket.py        # RTP packet handler
├── VideoStream.py      # Video file parser
└── movie.Mjpeg         # Sample video file
```

---

## 🚀 Cách Sử Dụng

### 1. Khởi Động Server

```bash
python Server.py <server_port>
```

**Ví dụ:**
```bash
python Server.py 5554
```

- `server_port`: Port để lắng nghe RTSP connections (> 1024)
- Chuẩn RTSP port là 554, nhưng cần dùng port > 1024

### 2. Khởi Động Client

```bash
python ClientLauncher.py <server_host> <server_port> <RTP_port> <video_file>
```

**Ví dụ:**
```bash
python ClientLauncher.py localhost 5554 25000 movie.Mjpeg
```

**Tham số:**
- `server_host`: Địa chỉ server (localhost, IP address, domain)
- `server_port`: Port RTSP của server (phải khớp với server)
- `RTP_port`: Port để nhận RTP packets (> 1024, khác server_port)
- `video_file`: Tên file video (movie.Mjpeg)

---

## 🎮 Điều Khiển Client

### Giao Diện Người Dùng

```
┌────────────────────────────────────┐
│                                    │
│        [Video Display Area]        │
│                                    │
└────────────────────────────────────┘
  Status: Ready to Play
  [Setup] [Play] [Pause] [Teardown]
```

### Các Nút Điều Khiển

1. **Setup**
   - Thiết lập session với server
   - Mở RTP socket để nhận data
   - Chuyển state: INIT → READY

2. **Play**
   - Bắt đầu streaming video
   - Kích hoạt buffering (cache 40 frames)
   - Chuyển state: READY → PLAYING

3. **Pause**
   - Tạm dừng playback
   - Giữ buffer để resume nhanh
   - Chuyển state: PLAYING → READY

4. **Teardown**
   - Kết thúc session
   - Đóng tất cả connections
   - Chuyển state: → INIT

---

## 🏗️ Kiến Trúc Hệ Thống

### Luồng Hoạt Động

```
Client                           Server
  │                                │
  ├─── SETUP (TCP) ──────────────>│
  │<─── 200 OK + Session ─────────┤
  │                                │
  ├─── PLAY (TCP) ───────────────>│
  │<─── 200 OK ────────────────────┤
  │                                │
  │<─── RTP Packets (UDP) ─────────┤ (30 FPS)
  │<─── RTP Packets (UDP) ─────────┤
  │<─── RTP Packets (UDP) ─────────┤
  │                                │
  ├─── PAUSE (TCP) ──────────────>│
  │<─── 200 OK ────────────────────┤
  │                                │
  ├─── TEARDOWN (TCP) ───────────>│
  │<─── 200 OK ────────────────────┤
```

### Protocol Stack

```
┌──────────────────────────────┐
│   Application (Video Player) │
├──────────────────────────────┤
│   RTSP (Control - TCP)       │
│   RTP (Data - UDP)           │
├──────────────────────────────┤
│   TCP / UDP                  │
├──────────────────────────────┤
│   IP                         │
├──────────────────────────────┤
│   Ethernet                   │
└──────────────────────────────┘
```

---

## 🔧 Chi Tiết Kỹ Thuật

### 1. RTSP Protocol Implementation

#### SETUP Request
```
SETUP movie.Mjpeg RTSP/1.0
CSeq: 1
Transport: RTP/UDP; client_port=25000
```

#### SETUP Response
```
RTSP/1.0 200 OK
CSeq: 1
Session: 123456
```

#### State Transitions
```
INIT ──[SETUP/200]──> READY ──[PLAY/200]──> PLAYING
                        ^                      │
                        └────[PAUSE/200]───────┘
```

### 2. RTP Packetization

#### Header Structure (12 bytes)
```
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|V=2|P|X|  CC   |M|     PT      |       sequence number         |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                           timestamp                           |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                            SSRC                               |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
```

**Field Descriptions:**
- **V** (Version): 2
- **P** (Padding): 0
- **X** (Extension): 0
- **CC** (CSRC Count): 0
- **M** (Marker): 1 for last packet of frame, 0 otherwise
- **PT** (Payload Type): 26 for MJPEG
- **Sequence Number**: Increments for each packet (0-65535)
- **Timestamp**: 90kHz clock for video
- **SSRC**: Synchronization source ID

### 3. MTU Fragmentation

#### Why Fragment?
- Ethernet MTU = 1500 bytes
- IP header = 20 bytes
- UDP header = 8 bytes
- RTP header = 12 bytes
- **Max payload = 1460 bytes**

#### Fragmentation Strategy
```python
if frame_size > 1460:
    # Split into chunks
    chunk_1 (M=0) ────> packet_1
    chunk_2 (M=0) ────> packet_2
    chunk_3 (M=0) ────> packet_3
    ...
    chunk_N (M=1) ────> packet_N (last fragment)
```

**Large Frame Example (4K = 3MB):**
- 3MB frame ÷ 1460 bytes = ~2100 packets
- All packets have same timestamp
- All packets have same frame number (in application layer)
- Only last packet has M=1

### 4. Client-Side Caching

#### Buffer Logic
```python
BUFFER_THRESHOLD = 40 frames

State: BUFFERING
    if buffer_size < 40:
        Display: "Buffering... (15/40)"
        Wait for more frames
    else:
        State: PLAYING

State: PLAYING
    if buffer_size > 0:
        Get frame from buffer
        Display frame at 30 FPS
    else:
        State: BUFFERING  # Rebuffer
```

#### Benefits
- Reduces jitter and stuttering
- Smooth playback even with network fluctuations
- Quick resume from pause

---

## 📊 Statistics & Monitoring

### Server Statistics (printed every 5 seconds)
```
==================================================
  Server Streaming Statistics
==================================================
  Frames Sent:        150
  Fragmented Frames:  145
  Total Packets:      315000
  Total Data:         450.25 MB
  Avg Bandwidth:      15.2 Mbps
  Packets/sec:        1050.5
  Frames/sec:         30.0
==================================================
```

### Client Status Display
```
Status: Buffering... (35/40)    # During buffering
Status: Playing (Buffer: 42)    # During playback
Status: Paused                  # During pause
```

---

## 🎯 Tính Năng Nâng Cao

### 1. HD Video Support (✅ Implemented)
- **Fragmentation**: Automatic splitting for frames > MTU
- **Large Buffers**: 8-10MB socket buffers
- **Optimized Sending**: Batch sending for 4K frames
- **Performance**: Maintains 30 FPS even with 3-5MB frames

### 2. Client-Side Caching (✅ Implemented)
- **Pre-buffering**: 40 frames before playback starts
- **Queue Management**: Thread-safe frame buffer
- **Smooth Playback**: Eliminates jitter
- **Status Feedback**: Real-time buffer status display

### 3. Error Handling
- **Packet Loss**: Silently skip corrupted frames
- **Network Issues**: Timeout and retry mechanisms
- **Socket Errors**: Graceful degradation
- **File Validation**: JPEG structure verification

---

## 🐛 Troubleshooting

### Problem: "Unable to Bind PORT"
**Solution:**
- Port đã được sử dụng
- Chọn port khác (> 1024)
- Kill process đang dùng port: `netstat -ano | findstr PORT`

### Problem: "Connection Failed"
**Solution:**
- Kiểm tra server đang chạy
- Kiểm tra địa chỉ IP và port
- Tắt firewall hoặc mở port

### Problem: Video bị lag/stutter
**Solution:**
- Tăng BUFFER_THRESHOLD (default: 40)
- Giảm FPS nếu máy yếu
- Kiểm tra băng thông mạng

### Problem: Không hiển thị video
**Solution:**
- Kiểm tra format video file (phải là MJPEG)
- Xem console log để debug
- Verify JPEG markers (FFD8...FFD9)

---

## 📝 Video Format Support

### 1. Proprietary Format (movie.Mjpeg)
```
[5-byte length][JPEG data][5-byte length][JPEG data]...
```

### 2. Standard MJPEG
```
[FFD8...FFD9][FFD8...FFD9][FFD8...FFD9]...
```

### Test Videos
- **Standard MJPEG samples:**
  - https://filesamples.com/formats/mjpeg
  - https://sample-files-online.com/samples/mjpeg

---

## 🎓 Grading Rubric

| No. | Requirement                    | Points | Status |
|-----|--------------------------------|--------|--------|
| 1   | RTSP + RTP Implementation      | 4.0    | ✅     |
| 2   | HD Video Streaming             | 3.0    | ✅     |
| 3   | Client-Side Caching            | 2.5    | ✅     |
| 4   | Report                         | 0.5    | ⏳     |
| **Total** |                          | **10** |        |

---

## 📚 References

- **RFC 2326** - Real Time Streaming Protocol (RTSP)
- **RFC 3550** - RTP: A Transport Protocol for Real-Time Applications
- **RFC 2435** - RTP Payload Format for JPEG-compressed Video

---

## 👥 Team Information

**Nhóm:** 3 sinh viên  
**Submission:** MSSV1_MSSV2_MSSV3.zip

---

## 📄 License

Đồ án môn học - Mạng Máy Tính

---

