from tkinter import *
import tkinter.messagebox
from PIL import Image, ImageTk
import socket, threading, sys, traceback, os, io, time, gc
import queue 

from RtpPacket import RtpPacket

CACHE_FILE_NAME = "cache-"
CACHE_FILE_EXT = ".jpg"

class Client:
	INIT = 0
	READY = 1
	PLAYING = 2
	state = INIT
	
	SETUP = 0
	PLAY = 1
	PAUSE = 2
	TEARDOWN = 3
	
	# Tăng FPS lên 30 để mượt hơn (chuẩn video thường là 30 hoặc 60)
	FPS = 30 
	FRAME_INTERVAL = 1.0 / FPS 
	
	# Tăng ngưỡng buffer lên để Caching hiệu quả hơn với video 4K
	BUFFER_THRESHOLD = 40 
	
	def __init__(self, master, serveraddr, serverport, rtpport, filename):
		self.master = master
		self.master.protocol("WM_DELETE_WINDOW", self.handler)
		self.createWidgets()
		self.serverAddr = serveraddr
		self.serverPort = int(serverport)
		self.rtpPort = int(rtpport)
		self.fileName = filename
		self.rtspSeq = 0
		self.sessionId = 0
		self.requestSent = -1
		self.teardownAcked = 0
		
		self.frameNbr = 0
		self.currentFrameData = bytearray()
		self.frameBuffer = queue.Queue()
		self.totalFrames = 0
		self.stopEvent = threading.Event() 
		self.isBuffering = False
		self.downloadComplete = False
		self.connectToServer()

	def createWidgets(self):
		self.master.geometry("800x600")

		self.controlFrame = Frame(self.master)
		self.controlFrame.pack(side=BOTTOM, fill=X, padx=5, pady=5)
		
		self.statusLabel = Label(self.controlFrame, text="Status: Idle", fg="blue", font=("Helvetica", 10))
		self.statusLabel.pack(side=TOP, fill=X, pady=2)
		
		btnConfig = {'width': 15, 'padx': 3, 'pady': 3}
		
		self.setup = Button(self.controlFrame, text="Setup", command=self.setupMovie, **btnConfig)
		self.setup.pack(side=LEFT, padx=2)
		
		self.start = Button(self.controlFrame, text="Play", command=self.playMovie, **btnConfig)
		self.start.pack(side=LEFT, padx=2)
		
		self.pause = Button(self.controlFrame, text="Pause", command=self.pauseMovie, **btnConfig)
		self.pause.pack(side=LEFT, padx=2)
		
		self.teardown = Button(self.controlFrame, text="Teardown", command=self.exitClient, **btnConfig)
		self.teardown.pack(side=LEFT, padx=2)

		self.videoFrame = Frame(self.master)
		self.videoFrame.pack(side=TOP, fill=BOTH, expand=True, padx=5, pady=5)
		
		self.label = Label(self.videoFrame, bg="black")
		self.label.pack(fill=BOTH, expand=True)

	def setupMovie(self):
		if self.state == self.INIT:
			self.sendRtspRequest(self.SETUP)
	
	def exitClient(self):
		self.sendRtspRequest(self.TEARDOWN)
		self.stopEvent.set()
		try: 
			self.rtpSocket.shutdown(socket.SHUT_RDWR)
			self.rtpSocket.close()
		except: pass
		
		self.master.destroy()
		try:
			os.remove(CACHE_FILE_NAME + str(self.sessionId) + CACHE_FILE_EXT)
		except OSError: pass
		os._exit(0)

	def pauseMovie(self):
		if self.state == self.PLAYING:
			self.state = self.READY
			self.statusLabel.configure(text="Paused", fg="red")
			gc.collect()

	def playMovie(self):
		if self.state == self.READY:
			self.stopEvent.clear()
			# Không reset buffer ở đây để giữ lại các frame đã cache nếu có
			# self.currentFrameData = bytearray() 
			
			if not hasattr(self, 'networkThread') or not self.networkThread.is_alive():
				self.networkThread = threading.Thread(target=self.runNetworkLoop)
				self.networkThread.daemon = True
				self.networkThread.start()
				
			if not hasattr(self, 'displayThread') or not self.displayThread.is_alive():
				self.displayThread = threading.Thread(target=self.runDisplayLoop)
				self.displayThread.daemon = True
				self.displayThread.start()

			# Chỉ gửi lệnh PLAY nếu chưa có dữ liệu trong buffer hoặc đang cần thêm
			if self.frameBuffer.qsize() < self.BUFFER_THRESHOLD or self.downloadComplete:
				self.sendRtspRequest(self.PLAY)
			
			self.state = self.PLAYING
			if self.frameBuffer.qsize() > 0 or self.downloadComplete:
				# Nếu có sẵn hàng HOẶC đã tải xong hết -> Chạy luôn
				self.isBuffering = False 
				self.statusLabel.configure(text=f"Playing (Buffer: {self.frameBuffer.qsize()})", fg="green")
			else:
				self.isBuffering = True 
				self.statusLabel.configure(text="Buffering...", fg="orange")

	def runNetworkLoop(self):
		while not self.stopEvent.is_set():
			try:
				# Tăng kích thước nhận gói tin UDP để tránh bị drop packet với 4K
				data = self.rtpSocket.recv(65535)
				if data:
					rtpPacket = RtpPacket()
					rtpPacket.decode(data)
					
					self.currentFrameData.extend(rtpPacket.getPayload())
					
					if rtpPacket.getMarker():
						# Marker bit = 1 nghĩa là kết thúc 1 frame ảnh
						if len(self.currentFrameData) > 0:
							# Kiểm tra header/footer JPEG cơ bản
							if self.currentFrameData.startswith(b'\xff\xd8') and self.currentFrameData.endswith(b'\xff\xd9'):
								# Đưa frame hoàn chỉnh vào buffer
								self.frameBuffer.put(bytes(self.currentFrameData))
						
						self.currentFrameData = bytearray()
			except socket.timeout:
				if (self.state == self.PLAYING):
					self.downloadComplete = True
				continue
			except:
				if self.teardownAcked == 1 or self.stopEvent.is_set():
					break

	def runDisplayLoop(self):
		while not self.stopEvent.is_set():
			# 1. Đo thời gian bắt đầu vòng lặp
			start_time = time.time()

			if self.state != self.PLAYING:
				time.sleep(0.01)
				continue
			
			bufferSize = self.frameBuffer.qsize()
			
			# --- LOGIC CACHING ---
			# Nếu đang trong trạng thái Buffering (nạp cache)
			if self.isBuffering:
				if bufferSize >= self.BUFFER_THRESHOLD or self.downloadComplete:
					self.isBuffering = False
					self.master.after(0, lambda: self.statusLabel.configure(text=f"Playing (Buffer: {bufferSize})", fg="green"))
				else:
					# Chưa đủ cache, đợi thêm một chút rồi kiểm tra lại
					self.master.after(0, lambda: self.statusLabel.configure(text=f"Buffering... ({bufferSize}/{self.BUFFER_THRESHOLD})", fg="orange"))
					time.sleep(0.05)
					continue
			
			# Nếu hết sạch buffer trong lúc đang play -> Quay lại buffering
			if self.frameBuffer.empty():
				if self.downloadComplete:
					# Đã tải xong mà hết buffer -> Hết phim
					self.master.after(0, lambda: self.statusLabel.configure(text="Finished", fg="blue"))
					self.state = self.READY
					continue
				else:
					# Chưa tải xong mà hết buffer -> Mạng lag -> Buffering
					self.isBuffering = True
					continue

			# --- HIỂN THỊ ẢNH ---
			try:
				frameData = self.frameBuffer.get_nowait()
				self.updateMovie(frameData)
			except queue.Empty:
				pass

			# 2. TÍNH TOÁN THỜI GIAN NGỦ ĐỂ KHÔNG BỊ SLOW MOTION
			# Thời gian đã trôi qua cho việc giải nén và resize ảnh
			process_time = time.time() - start_time
			
			# Thời gian cần ngủ = Khoảng cách giữa các frame chuẩn - Thời gian đã xử lý
			delay = self.FRAME_INTERVAL - process_time
			
			if delay > 0:
				time.sleep(delay)
			else:
				# Nếu xử lý quá lâu (lâu hơn cả 1 frame), không ngủ nữa để đuổi kịp tiến độ
				pass

	def updateMovie(self, imageBytes):
		try:
			# Sử dụng io.BytesIO để đọc ảnh từ RAM (nhanh hơn ghi ra đĩa)
			img = Image.open(io.BytesIO(imageBytes))
			
			w = self.videoFrame.winfo_width()
			h = self.videoFrame.winfo_height()
			
			if w < 10 or h < 10: 
				w, h = 640, 480
			
			img.thumbnail((w, h), Image.Resampling.LANCZOS)
			
			photo = ImageTk.PhotoImage(img)
			
			# Cập nhật UI trên luồng chính (Main Thread)
			self.master.after(0, lambda p=photo: self._update_label(p))
		except Exception as e:
			print(f"Frame error: {e}")
			pass
		
	def _update_label(self, photo):
		self.label.configure(image=photo)
		self.label.image = photo

	def connectToServer(self):
		self.rtspSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		try:
			self.rtspSocket.connect((self.serverAddr, self.serverPort))
		except:
			tkinter.messagebox.showwarning('Connection Failed', 'Connection to \'%s\' failed.' %self.serverAddr)
	
	def sendRtspRequest(self, requestCode):
		if requestCode == self.SETUP and self.state == self.INIT:
			threading.Thread(target=self.recvRtspReply).start()
			self.rtspSeq += 1
			request = 'SETUP ' + self.fileName + ' RTSP/1.0\r\n'
			request += 'CSeq: ' + str(self.rtspSeq) + '\r\n'
			request += 'Transport: RTP/UDP; client_port= ' + str(self.rtpPort) + '\r\n'
			request += '\r\n'
			self.requestSent = self.SETUP
		
		elif requestCode == self.PLAY:
			self.rtspSeq += 1
			request = 'PLAY ' + self.fileName + ' RTSP/1.0\r\n'
			request += 'CSeq: ' + str(self.rtspSeq) + '\r\n'
			request += 'Session: ' + str(self.sessionId) + '\r\n'
			request += '\r\n'
			self.requestSent = self.PLAY
		
		elif requestCode == self.PAUSE:
			self.rtspSeq += 1
			request = 'PAUSE ' + self.fileName + ' RTSP/1.0\r\n'
			request += 'CSeq: ' + str(self.rtspSeq) + '\r\n'
			request += 'Session: ' + str(self.sessionId) + '\r\n'
			request += '\r\n' 
			self.requestSent = self.PAUSE
			
		elif requestCode == self.TEARDOWN:
			self.rtspSeq += 1
			request = 'TEARDOWN ' + self.fileName + ' RTSP/1.0\r\n'
			request += 'CSeq: ' + str(self.rtspSeq) + '\r\n'
			request += 'Session: ' + str(self.sessionId) + '\r\n'
			request += '\r\n' 
			self.requestSent = self.TEARDOWN
		else:
			return
		
		try:
			self.rtspSocket.send(request.encode())
			print('\nData sent:\n' + request)
		except: pass
	
	def recvRtspReply(self):
		while True:
			try:
				reply = self.rtspSocket.recv(1024)
				if reply: 
					self.parseRtspReply(reply.decode("utf-8"))
				if self.requestSent == self.TEARDOWN:
					self.rtspSocket.shutdown(socket.SHUT_RDWR)
					self.rtspSocket.close()
					break
			except:
				break
	
	def parseRtspReply(self, data):
		try:
			lines = data.split('\n')
			seqNum = int(lines[1].split(' ')[1])
			if seqNum == self.rtspSeq:
				session = int(lines[2].split(' ')[1])
				if self.sessionId == 0:
					self.sessionId = session
				if self.sessionId == session:
					if int(lines[0].split(' ')[1]) == 200: 
						if self.requestSent == self.SETUP:
							self.state = self.READY 
							self.openRtpPort() 
							if not hasattr(self, 'networkThread') or not self.networkThread.is_alive():
								self.networkThread = threading.Thread(target=self.runNetworkLoop)
								self.networkThread.daemon = True
								self.networkThread.start()
							self.statusLabel.configure(text="Ready to Play", fg="blue")
						elif self.requestSent == self.PLAY:
							self.state = self.PLAYING 
						elif self.requestSent == self.PAUSE:
							pass
						elif self.requestSent == self.TEARDOWN:
							self.state = self.INIT 
							self.teardownAcked = 1 
							self.stopEvent.set()
							self.statusLabel.configure(text="Session Ended", fg="black")
		except:
			pass
	
	def openRtpPort(self):
		self.rtpSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
		self.rtpSocket.settimeout(0.5) 
		try:
			# Tăng bộ đệm nhận của Socket để chứa frame 4K lớn
			self.rtpSocket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 10*1024*1024)
			self.rtpSocket.bind(('', self.rtpPort))
		except:
			tkinter.messagebox.showwarning('Unable to Bind', 'Unable to bind PORT=%d' %self.rtpPort)

	def handler(self):
		self.pauseMovie()
		if tkinter.messagebox.askokcancel("Quit?", "Are you sure you want to quit?"):
			self.exitClient()
		else: 
			self.playMovie()