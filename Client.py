from tkinter import *
import tkinter.messagebox
from PIL import Image, ImageTk
import socket, threading, sys, traceback, os, io, time, gc
import queue 

from RtpPacket import RtpPacket

CACHE_FILE_NAME = "cache-"
CACHE_FILE_EXT = ".jpg"

class Client:
	# RTSP States
	INIT = 0
	READY = 1
	PLAYING = 2
	state = INIT
	
	# RTSP Commands
	SETUP = 0
	PLAY = 1
	PAUSE = 2
	TEARDOWN = 3
	
	# Video playback settings
	FPS = 30  # Target 30 FPS for smooth HD playback
	FRAME_INTERVAL = 1.0 / FPS 
	
	# Buffer threshold for caching (higher for 4K videos)
	BUFFER_THRESHOLD = 40  # Pre-buffer 40 frames before playing
	
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
		
		# Frame tracking and buffering
		self.frameNbr = 0
		self.currentFrameData = bytearray()  # Accumulates RTP fragments
		self.frameBuffer = queue.Queue()     # Complete frames ready to display
		self.totalFrames = 0
		self.stopEvent = threading.Event() 
		self.isBuffering = False
		
		self.connectToServer()

	def createWidgets(self):
		"""Create GUI widgets"""
		self.master.geometry("800x600")

		# Control panel at bottom
		self.controlFrame = Frame(self.master)
		self.controlFrame.pack(side=BOTTOM, fill=X, padx=5, pady=5)
		
		# Status label
		self.statusLabel = Label(self.controlFrame, text="Status: Idle", fg="blue", font=("Helvetica", 10))
		self.statusLabel.pack(side=TOP, fill=X, pady=2)
		
		# Control buttons
		btnConfig = {'width': 15, 'padx': 3, 'pady': 3}
		
		self.setup = Button(self.controlFrame, text="Setup", command=self.setupMovie, **btnConfig)
		self.setup.pack(side=LEFT, padx=2)
		
		self.start = Button(self.controlFrame, text="Play", command=self.playMovie, **btnConfig)
		self.start.pack(side=LEFT, padx=2)
		
		self.pause = Button(self.controlFrame, text="Pause", command=self.pauseMovie, **btnConfig)
		self.pause.pack(side=LEFT, padx=2)
		
		self.teardown = Button(self.controlFrame, text="Teardown", command=self.exitClient, **btnConfig)
		self.teardown.pack(side=LEFT, padx=2)

		# Video display frame
		self.videoFrame = Frame(self.master)
		self.videoFrame.pack(side=TOP, fill=BOTH, expand=True, padx=5, pady=5)
		
		self.label = Label(self.videoFrame, bg="black")
		self.label.pack(fill=BOTH, expand=True)

	def setupMovie(self):
		"""Handle Setup button click"""
		if self.state == self.INIT:
			self.sendRtspRequest(self.SETUP)
	
	def exitClient(self):
		"""Handle Teardown button click - cleanup and exit"""
		self.sendRtspRequest(self.TEARDOWN)
		self.stopEvent.set()
		
		# Close RTP socket
		try: 
			self.rtpSocket.shutdown(socket.SHUT_RDWR)
			self.rtpSocket.close()
		except: 
			pass
		
		self.master.destroy()
		
		# Clean up cache file
		try:
			os.remove(CACHE_FILE_NAME + str(self.sessionId) + CACHE_FILE_EXT)
		except OSError: 
			pass
			
		os._exit(0)

	def pauseMovie(self):
		"""Handle Pause button click"""
		if self.state == self.PLAYING:
			self.sendRtspRequest(self.PAUSE)
			self.state = self.READY
			self.statusLabel.configure(text="Paused", fg="red")
			gc.collect()  # Force garbage collection

	def playMovie(self):
		"""Handle Play button click"""
		if self.state == self.READY:
			self.stopEvent.clear()
			
			# Start network thread if not running
			if not hasattr(self, 'networkThread') or not self.networkThread.is_alive():
				self.networkThread = threading.Thread(target=self.runNetworkLoop)
				self.networkThread.daemon = True
				self.networkThread.start()
			
			# Start display thread if not running
			if not hasattr(self, 'displayThread') or not self.displayThread.is_alive():
				self.displayThread = threading.Thread(target=self.runDisplayLoop)
				self.displayThread.daemon = True
				self.displayThread.start()

			# Send PLAY request only if buffer needs more data
			if self.frameBuffer.qsize() < self.BUFFER_THRESHOLD:
				self.sendRtspRequest(self.PLAY)
			
			self.state = self.PLAYING
			# Start buffering mode when Play is pressed
			self.isBuffering = True 
			self.statusLabel.configure(text="Buffering...", fg="orange")

	def runNetworkLoop(self):
		"""Network thread: Receive RTP packets and reassemble frames"""
		while not self.stopEvent.is_set():
			try:
				# Receive UDP packet (increased buffer for 4K frames)
				data = self.rtpSocket.recv(65535)
				if data:
					rtpPacket = RtpPacket()
					rtpPacket.decode(data)
					
					# Accumulate payload data
					self.currentFrameData.extend(rtpPacket.getPayload())
					
					# Check if this is the last fragment of a frame
					if rtpPacket.getMarker():
						# Marker bit = 1 means end of frame
						if len(self.currentFrameData) > 0:
							# Validate JPEG structure (starts with FFD8, ends with FFD9)
							if self.currentFrameData.startswith(b'\xff\xd8') and \
							   self.currentFrameData.endswith(b'\xff\xd9'):
								# Put complete frame into buffer
								self.frameBuffer.put(bytes(self.currentFrameData))
						
						# Reset for next frame
						self.currentFrameData = bytearray()
			except socket.timeout:
				continue
			except Exception as e:
				if self.teardownAcked == 1 or self.stopEvent.is_set():
					break
				# Uncomment for debugging: print(f"Network error: {e}")

	def runDisplayLoop(self):
		"""Display thread: Show frames at consistent frame rate with buffering"""
		while not self.stopEvent.is_set():
			start_time = time.time()

			if self.state != self.PLAYING:
				time.sleep(0.01)
				continue
			
			bufferSize = self.frameBuffer.qsize()
			
			# --- CACHING LOGIC ---
			# If in buffering mode (building cache)
			if self.isBuffering:
				if bufferSize >= self.BUFFER_THRESHOLD:
					# Buffer is full, start playing
					self.isBuffering = False
					self.master.after(0, lambda: self.statusLabel.configure(
						text=f"Playing (Buffer: {bufferSize})", fg="green"))
				else:
					# Still buffering, wait for more frames
					self.master.after(0, lambda bs=bufferSize: self.statusLabel.configure(
						text=f"Buffering... ({bs}/{self.BUFFER_THRESHOLD})", fg="orange"))
					time.sleep(0.05)
					continue
			
			# If buffer is empty during playback, go back to buffering mode
			if self.frameBuffer.empty():
				self.isBuffering = True
				continue

			# --- DISPLAY FRAME ---
			try:
				frameData = self.frameBuffer.get_nowait()
				self.updateMovie(frameData)
			except queue.Empty:
				pass

			# --- FRAME RATE CONTROL ---
			# Calculate time spent processing
			process_time = time.time() - start_time
			
			# Sleep for remaining time to maintain target FPS
			delay = self.FRAME_INTERVAL - process_time
			
			if delay > 0:
				time.sleep(delay)
			# If processing took too long, don't sleep (catch up)

	def updateMovie(self, imageBytes):
		"""Decode and display a single frame"""
		try:
			# Use io.BytesIO to read image from memory (faster than disk)
			img = Image.open(io.BytesIO(imageBytes))
			
			# Get video frame dimensions
			w = self.videoFrame.winfo_width()
			h = self.videoFrame.winfo_height()
			
			if w < 10 or h < 10:  # Default size if window not ready
				w, h = 640, 480
			
			# Resize image to fit window
			# Use BILINEAR for good balance of speed and quality
			# (LANCZOS is slower but higher quality, NEAREST is fastest but lower quality)
			img.thumbnail((w, h), Image.Resampling.BILINEAR)
			
			photo = ImageTk.PhotoImage(img)
			
			# Update UI on main thread
			self.master.after(0, lambda p=photo: self._update_label(p))
		except Exception as e:
			# Skip corrupted frames silently
			# Uncomment for debugging: print(f"Frame decode error: {e}")
			pass
		
	def _update_label(self, photo):
		"""Update label with new photo (called on main thread)"""
		self.label.configure(image=photo)
		self.label.image = photo  # Keep reference to prevent garbage collection

	def connectToServer(self):
		"""Establish TCP connection to RTSP server"""
		self.rtspSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		try:
			self.rtspSocket.connect((self.serverAddr, self.serverPort))
		except:
			tkinter.messagebox.showwarning('Connection Failed', 
				'Connection to \'%s\' failed.' % self.serverAddr)
	
	def sendRtspRequest(self, requestCode):
		"""Send RTSP request to server"""
		if requestCode == self.SETUP and self.state == self.INIT:
			# Start thread to receive RTSP replies
			threading.Thread(target=self.recvRtspReply).start()
			
			self.rtspSeq += 1
			request = 'SETUP ' + self.fileName + ' RTSP/1.0\r\n'
			request += 'CSeq: ' + str(self.rtspSeq) + '\r\n'
			request += 'Transport: RTP/UDP; client_port= ' + str(self.rtpPort) + '\r\n'
			request += '\r\n'
			self.requestSent = self.SETUP
		
		elif requestCode == self.PLAY and self.state == self.READY:
			self.rtspSeq += 1
			request = 'PLAY ' + self.fileName + ' RTSP/1.0\r\n'
			request += 'CSeq: ' + str(self.rtspSeq) + '\r\n'
			request += 'Session: ' + str(self.sessionId) + '\r\n'
			request += '\r\n'
			self.requestSent = self.PLAY
		
		elif requestCode == self.PAUSE and self.state == self.PLAYING:
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
		except Exception as e:
			print(f"Error sending RTSP request: {e}")
	
	def recvRtspReply(self):
		"""Receive RTSP replies from server"""
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
		"""Parse RTSP reply and update client state"""
		try:
			lines = data.split('\n')
			seqNum = int(lines[1].split(' ')[1])
			
			# Verify sequence number matches
			if seqNum == self.rtspSeq:
				session = int(lines[2].split(' ')[1])
				
				# Store session ID from first reply
				if self.sessionId == 0:
					self.sessionId = session
				
				# Verify session ID matches
				if self.sessionId == session:
					responseCode = int(lines[0].split(' ')[1])
					
					if responseCode == 200:  # OK
						if self.requestSent == self.SETUP:
							self.state = self.READY 
							self.openRtpPort() 
							
							# Start network thread after RTP port is open
							if not hasattr(self, 'networkThread') or not self.networkThread.is_alive():
								self.networkThread = threading.Thread(target=self.runNetworkLoop)
								self.networkThread.daemon = True
								self.networkThread.start()
							
							self.statusLabel.configure(text="Ready to Play", fg="blue")
							
						elif self.requestSent == self.PLAY:
							self.state = self.PLAYING 
							# Status is updated in runDisplayLoop based on buffer state
							
						elif self.requestSent == self.PAUSE:
							self.state = self.READY
							
						elif self.requestSent == self.TEARDOWN:
							self.state = self.INIT 
							self.teardownAcked = 1 
							self.stopEvent.set()
							self.statusLabel.configure(text="Session Ended", fg="black")
					else:
						print(f"RTSP Error: Response code {responseCode}")
		except Exception as e:
			print(f"Error parsing RTSP reply: {e}")
	
	def openRtpPort(self):
		"""Open UDP socket for receiving RTP packets"""
		self.rtpSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
		self.rtpSocket.settimeout(0.5)  # 500ms timeout
		
		try:
			# Increase receive buffer for 4K frames (10MB)
			self.rtpSocket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 10*1024*1024)
			self.rtpSocket.bind(('', self.rtpPort))
		except Exception as e:
			tkinter.messagebox.showwarning('Unable to Bind', 
				'Unable to bind PORT=%d' % self.rtpPort)

	def handler(self):
		"""Handle window close event"""
		self.pauseMovie()
		if tkinter.messagebox.askokcancel("Quit?", "Are you sure you want to quit?"):
			self.exitClient()
		else: 
			self.playMovie()