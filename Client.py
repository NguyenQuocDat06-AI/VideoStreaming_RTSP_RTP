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
	
	FPS = 25
	FRAME_INTERVAL = 1.0 / FPS 
	BUFFER_THRESHOLD = 20
	
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
		
		self.connectToServer()

	def createWidgets(self):
		# 1. Đặt kích thước cửa sổ ban đầu hợp lý (800x600)
		# Giúp cửa sổ không bị bung quá to khi gặp video HD/4K
		self.master.geometry("800x600")

		# 2. QUAN TRỌNG: Tạo khung điều khiển và PACK TRƯỚC (side=BOTTOM)
		# Điều này đảm bảo các nút bấm luôn được dành chỗ trước và nằm ở đáy
		self.controlFrame = Frame(self.master)
		self.controlFrame.pack(side=BOTTOM, fill=X, padx=5, pady=5)
		
		# Status Label nằm trong controlFrame
		self.statusLabel = Label(self.controlFrame, text="Status: Idle", fg="blue", font=("Helvetica", 10))
		self.statusLabel.pack(side=TOP, fill=X, pady=2)
		
		# Các nút bấm
		btnConfig = {'width': 15, 'padx': 3, 'pady': 3}
		
		self.setup = Button(self.controlFrame, text="Setup", command=self.setupMovie, **btnConfig)
		self.setup.pack(side=LEFT, padx=2)
		
		self.start = Button(self.controlFrame, text="Play", command=self.playMovie, **btnConfig)
		self.start.pack(side=LEFT, padx=2)
		
		self.pause = Button(self.controlFrame, text="Pause", command=self.pauseMovie, **btnConfig)
		self.pause.pack(side=LEFT, padx=2)
		
		self.teardown = Button(self.controlFrame, text="Teardown", command=self.exitClient, **btnConfig)
		self.teardown.pack(side=LEFT, padx=2)

		# 3. Tạo khung Video và PACK SAU (side=TOP, expand=True)
		# Nó sẽ chiếm toàn bộ khoảng trống CÒN LẠI phía trên
		self.videoFrame = Frame(self.master)
		self.videoFrame.pack(side=TOP, fill=BOTH, expand=True, padx=5, pady=5)
		
		# Label hiển thị ảnh
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
			self.statusLabel.configure(text="Paused (Buffering...)", fg="red")
			gc.collect()

	def playMovie(self):
		if self.state == self.READY:
			self.stopEvent.clear()
			self.currentFrameData = bytearray()
			
			if not hasattr(self, 'networkThread') or not self.networkThread.is_alive():
				self.networkThread = threading.Thread(target=self.runNetworkLoop)
				self.networkThread.daemon = True
				self.networkThread.start()
				
			if not hasattr(self, 'displayThread') or not self.displayThread.is_alive():
				self.displayThread = threading.Thread(target=self.runDisplayLoop)
				self.displayThread.daemon = True
				self.displayThread.start()

			if self.frameBuffer.empty():
				self.sendRtspRequest(self.PLAY)
			
			self.state = self.PLAYING
			self.isBuffering = True 

	def runNetworkLoop(self):
		while not self.stopEvent.is_set():
			try:
				data = self.rtpSocket.recv(65535)
				if data:
					rtpPacket = RtpPacket()
					rtpPacket.decode(data)
					
					self.currentFrameData.extend(rtpPacket.getPayload())
					
					if rtpPacket.getMarker():
						if len(self.currentFrameData) > 0:
							if self.currentFrameData.startswith(b'\xff\xd8') and self.currentFrameData.endswith(b'\xff\xd9'):
								self.frameBuffer.put(bytes(self.currentFrameData))
						
						self.currentFrameData = bytearray()
			except socket.timeout:
				continue
			except:
				if self.teardownAcked == 1 or self.stopEvent.is_set():
					break

	def runDisplayLoop(self):
		while not self.stopEvent.is_set():
			if self.state != self.PLAYING:
				time.sleep(0.1)
				continue
			
			bufferSize = self.frameBuffer.qsize()
			
			if self.isBuffering:
				if bufferSize >= self.BUFFER_THRESHOLD:
					self.isBuffering = False
					self.master.after(0, lambda: self.statusLabel.configure(text="Playing", fg="green"))
				else:
					time.sleep(0.05)
					continue
			
			if not self.frameBuffer.empty():
				try:
					frameData = self.frameBuffer.get_nowait()
					self.updateMovie(frameData)
					time.sleep(self.FRAME_INTERVAL)
				except queue.Empty:
					pass
			else:
				self.isBuffering = True
				self.master.after(0, lambda: self.statusLabel.configure(text="Buffering...", fg="orange"))

	def updateMovie(self, imageBytes):
		try:
			img = Image.open(io.BytesIO(imageBytes))
			
			# Lấy kích thước của KHUNG CHỨA (videoFrame) để resize ảnh vào đó
			w = self.videoFrame.winfo_width()
			h = self.videoFrame.winfo_height()
			
			# Nếu khung chưa kịp hiển thị (kích thước < 10), dùng kích thước mặc định 640x480
			if w < 10 or h < 10: 
				w, h = 640, 480
			
			# Resize ảnh cho vừa khít khung chứa
			img = img.resize((w, h), Image.Resampling.LANCZOS)
			
			photo = ImageTk.PhotoImage(img)
			self.master.after(0, lambda p=photo: self._update_label(p))
		except: pass
		
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
							self.statusLabel.configure(text="Playing", fg="green")
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