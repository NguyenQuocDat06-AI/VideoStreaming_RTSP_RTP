from random import randint
import sys, traceback, threading, socket, time

from VideoStream import VideoStream
from RtpPacket import RtpPacket

class ServerWorker:
	# RTSP Commands
	SETUP = 'SETUP'
	PLAY = 'PLAY'
	PAUSE = 'PAUSE'
	TEARDOWN = 'TEARDOWN'
	
	# Server States
	INIT = 0
	READY = 1
	PLAYING = 2
	state = INIT

	# Response Codes
	OK_200 = 0
	FILE_NOT_FOUND_404 = 1
	CON_ERR_500 = 2
	
	# MTU Configuration
	# Ethernet MTU = 1500 bytes
	# IP header = 20 bytes, UDP header = 8 bytes, RTP header = 12 bytes
	# Safe payload size = 1500 - 20 - 8 - 12 = 1460 bytes
	MTU_SIZE = 1500
	IP_UDP_HEADER_SIZE = 28  # IP (20) + UDP (8)
	RTP_HEADER_SIZE = 12
	MAX_RTP_PAYLOAD = MTU_SIZE - IP_UDP_HEADER_SIZE - RTP_HEADER_SIZE  # 1460 bytes
	
	def __init__(self, clientInfo):
		self.clientInfo = clientInfo
		self.seqNum = 0  # Global RTP sequence number
		self.frameTimestamp = 0  # RTP timestamp (90kHz clock for video)
		
		# Statistics tracking
		self.stats = {
			'total_packets_sent': 0,
			'total_bytes_sent': 0,
			'total_frames_sent': 0,
			'fragmented_frames': 0,
			'start_time': time.time(),
			'last_stats_time': time.time()
		}
		
	def run(self):
		"""Start RTSP request handler thread"""
		threading.Thread(target=self.recvRtspRequest).start()
	
	def recvRtspRequest(self):
		"""Receive and process RTSP requests from client"""
		connSocket = self.clientInfo['rtspSocket'][0]
		while True:            
			try:
				data = connSocket.recv(256)
				if data:
					print("Data received:\n" + data.decode("utf-8"))
					self.processRtspRequest(data.decode("utf-8"))
			except Exception as e:
				print(f"Error receiving RTSP request: {e}")
				break
	
	def processRtspRequest(self, data):
		"""Parse and handle RTSP request"""
		request = data.split('\n')
		line1 = request[0].split(' ')
		requestType = line1[0]
		filename = line1[1]
		seq = request[1].split(' ')
		
		if requestType == self.SETUP:
			if self.state == self.INIT:
				print("Processing SETUP request...")
				try:
					# Open video file stream
					self.clientInfo['videoStream'] = VideoStream(filename)
					self.state = self.READY
					
					# Generate random session ID
					self.clientInfo['session'] = randint(100000, 999999)
					
					# Parse client RTP port from Transport header
					try:
						self.clientInfo['rtpPort'] = request[2].split(' ')[3]
					except IndexError:
						print("Warning: Could not parse RTP port from Transport header")
					
					self.replyRtsp(self.OK_200, seq[1])
					print(f"SETUP successful - Session: {self.clientInfo['session']}")
					
				except IOError as e:
					print(f"Error: File '{filename}' not found")
					self.replyRtsp(self.FILE_NOT_FOUND_404, seq[1])
		
		elif requestType == self.PLAY:
			if self.state == self.READY:
				print("Processing PLAY request...")
				self.state = self.PLAYING
				
				# Create UDP socket for RTP if not exists
				if "rtpSocket" not in self.clientInfo:
					self.clientInfo["rtpSocket"] = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
					
					# Optimize socket for high-performance streaming
					try:
						# Large send buffer for 4K frames (8MB)
						self.clientInfo["rtpSocket"].setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 8*1024*1024)
						# Non-blocking mode for better performance
						self.clientInfo["rtpSocket"].setblocking(False)
						print("RTP socket optimized for 4K streaming")
					except Exception as e:
						print(f"Socket optimization failed: {e}")
						# Fallback to smaller buffer sizes
						try:
							self.clientInfo["rtpSocket"].setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4*1024*1024)
						except:
							try:
								self.clientInfo["rtpSocket"].setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 2*1024*1024)
							except:
								pass

				self.replyRtsp(self.OK_200, seq[1])
				
				# Start RTP streaming thread
				self.clientInfo['event'] = threading.Event()
				self.clientInfo['worker'] = threading.Thread(target=self.sendRtp) 
				self.clientInfo['worker'].start()
				print("RTP streaming started")
		
		elif requestType == self.PAUSE:
			if self.state == self.PLAYING:
				print("Processing PAUSE request...")
				self.state = self.READY
				self.clientInfo['event'].set()  # Stop streaming
				self.replyRtsp(self.OK_200, seq[1])
		
		elif requestType == self.TEARDOWN:
			print("Processing TEARDOWN request...")
			self.clientInfo['event'].set()  # Stop streaming
			self.replyRtsp(self.OK_200, seq[1])
			
			# Close RTP socket
			if "rtpSocket" in self.clientInfo:
				self.clientInfo['rtpSocket'].close()
				del self.clientInfo['rtpSocket']
			
			self._printFinalStatistics()
			
	def sendRtp(self):
		"""
		Send RTP packets over UDP with MTU-aware fragmentation.
		Maintains 30 FPS for smooth HD/4K playback.
		"""
		BASE_FRAME_INTERVAL = 1.0 / 30.0  # 30 FPS = 0.0333s per frame
		next_frame_time = time.time()
		
		while True:
			# Calculate wait time until next frame
			current_time = time.time()
			wait_time = next_frame_time - current_time
			
			# Wait if we're ahead of schedule
			if wait_time > 0.001:  # Only wait if more than 1ms
				self.clientInfo['event'].wait(wait_time)
			
			# Check if pause/teardown was requested
			if self.clientInfo['event'].isSet(): 
				break 
			
			# Update next frame time
			next_frame_time = max(current_time, next_frame_time) + BASE_FRAME_INTERVAL
			
			frame_start_time = time.time()
			data = self.clientInfo['videoStream'].nextFrame()
			
			if data: 
				frameNumber = self.clientInfo['videoStream'].frameNbr()
				try:
					address = self.clientInfo['rtspSocket'][1][0]
					port = int(self.clientInfo['rtpPort'])
					
					# Update RTP timestamp (90kHz clock for video)
					self.frameTimestamp = int(frame_start_time * 90000)
					
					# Fragment frame if it exceeds MTU
					if len(data) > self.MAX_RTP_PAYLOAD:
						packets_sent = self._sendFragmentedFrame(data, frameNumber, address, port)
						self.stats['fragmented_frames'] += 1
					else:
						# Single packet frame
						packet = self.makeRtp(data, frameNumber, 1)
						self.clientInfo['rtpSocket'].sendto(packet, (address, port))
						packets_sent = 1
						self.stats['total_bytes_sent'] += len(packet)
					
					self.stats['total_packets_sent'] += packets_sent
					self.stats['total_frames_sent'] += 1
					
					# Print statistics every 5 seconds
					if current_time - self.stats['last_stats_time'] >= 5.0:
						self._printStatistics()
						self.stats['last_stats_time'] = current_time
						
				except Exception as e:
					print(f"Connection Error: {e}")
					continue
			else:
				# End of video file
				print("End of video stream")
				break
	
	def _sendFragmentedFrame(self, data, frameNumber, address, port):
		"""
		Fragment and send a frame that exceeds MTU.
		Optimized for large 4K frames (2-5MB).
		"""
		packets_sent = 0
		start = 0
		rtp_socket = self.clientInfo['rtpSocket']
		address_port = (address, port)
		data_len = len(data)
		
		# Batch sending for better performance with large frames
		# 4K frames can require 1500+ packets
		batch_size = 50  # Send in batches to reduce overhead
		packet_batch = []
		
		while start < data_len:
			end = min(start + self.MAX_RTP_PAYLOAD, data_len)
			payload_chunk = data[start:end]
			
			# Marker bit: 1 for last fragment, 0 otherwise
			marker = 1 if end >= data_len else 0
			
			# Create RTP packet
			packet = self.makeRtp(payload_chunk, frameNumber, marker)
			packet_batch.append((packet, len(packet)))
			
			# Send batch when full or at end of frame
			if len(packet_batch) >= batch_size or marker:
				for pkt, pkt_len in packet_batch:
					try:
						rtp_socket.sendto(pkt, address_port)
						self.stats['total_bytes_sent'] += pkt_len
						packets_sent += 1
					except BlockingIOError:
						# Socket buffer full, wait briefly
						time.sleep(0.00001)  # 10 microseconds
						try:
							rtp_socket.sendto(pkt, address_port)
							self.stats['total_bytes_sent'] += pkt_len
							packets_sent += 1
						except:
							print(f"Warning: Dropped packet in frame {frameNumber}")
					except Exception as e:
						print(f"Warning: Error sending packet: {e}")
				
				packet_batch.clear()
			
			start = end
		
		return packets_sent
	
	def _printStatistics(self):
		"""Print network usage and performance statistics"""
		elapsed = time.time() - self.stats['start_time']
		if elapsed > 0:
			avg_bandwidth_mbps = (self.stats['total_bytes_sent'] * 8) / (elapsed * 1000000)
			packets_per_sec = self.stats['total_packets_sent'] / elapsed
			frames_per_sec = self.stats['total_frames_sent'] / elapsed
			
			print(f"\n{'='*50}")
			print(f"  Server Streaming Statistics")
			print(f"{'='*50}")
			print(f"  Frames Sent:        {self.stats['total_frames_sent']}")
			print(f"  Fragmented Frames:  {self.stats['fragmented_frames']}")
			print(f"  Total Packets:      {self.stats['total_packets_sent']}")
			print(f"  Total Data:         {self.stats['total_bytes_sent'] / (1024*1024):.2f} MB")
			print(f"  Avg Bandwidth:      {avg_bandwidth_mbps:.2f} Mbps")
			print(f"  Packets/sec:        {packets_per_sec:.1f}")
			print(f"  Frames/sec:         {frames_per_sec:.1f}")
			print(f"{'='*50}\n")
	
	def _printFinalStatistics(self):
		"""Print final statistics on teardown"""
		print(f"\n{'='*50}")
		print(f"  Final Streaming Statistics")
		print(f"{'='*50}")
		elapsed = time.time() - self.stats['start_time']
		if elapsed > 0:
			avg_bandwidth_mbps = (self.stats['total_bytes_sent'] * 8) / (elapsed * 1000000)
			print(f"  Total Frames:       {self.stats['total_frames_sent']}")
			print(f"  Fragmented Frames:  {self.stats['fragmented_frames']}")
			print(f"  Total Packets:      {self.stats['total_packets_sent']}")
			print(f"  Total Data:         {self.stats['total_bytes_sent'] / (1024*1024):.2f} MB")
			print(f"  Session Duration:   {elapsed:.1f}s")
			print(f"  Avg Bandwidth:      {avg_bandwidth_mbps:.2f} Mbps")
		print(f"{'='*50}\n")

	def makeRtp(self, payload, frameNbr, marker):
		"""
		Create RTP packet with proper header fields.
		
		Args:
			payload: Frame data (or fragment)
			frameNbr: Frame number (for debugging, not used in header)
			marker: Marker bit (1 = last fragment of frame)
		
		Returns:
			Complete RTP packet (header + payload)
		"""
		# RTP Header Fields
		version = 2          # RTP version 2
		padding = 0          # No padding
		extension = 0        # No extension
		cc = 0               # No CSRC identifiers
		pt = 26              # Payload type 26 = MJPEG
		seqnum = self.seqNum # Sequence number
		ssrc = 0x12345678    # Synchronization source identifier
		
		# Increment sequence number for next packet (wrap at 65536)
		self.seqNum = (self.seqNum + 1) % 65536
		
		# Create and encode RTP packet
		rtpPacket = RtpPacket()
		rtpPacket.encode(version, padding, extension, cc, seqnum, marker, pt, ssrc, 
		                 payload, self.frameTimestamp)
		
		return rtpPacket.getPacket()
		
	def replyRtsp(self, code, seq):
		"""Send RTSP reply to client"""
		if code == self.OK_200:
			reply = 'RTSP/1.0 200 OK\nCSeq: ' + seq + '\nSession: ' + str(self.clientInfo['session'])
			connSocket = self.clientInfo['rtspSocket'][0]
			connSocket.send(reply.encode())
		elif code == self.FILE_NOT_FOUND_404:
			print("404 NOT FOUND")
		elif code == self.CON_ERR_500:
			print("500 CONNECTION ERROR")