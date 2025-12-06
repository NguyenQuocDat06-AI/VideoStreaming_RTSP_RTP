from random import randint
import sys, traceback, threading, socket, time
from collections import deque

from VideoStream import VideoStream
from RtpPacket import RtpPacket

class ServerWorker:
	SETUP = 'SETUP'
	PLAY = 'PLAY'
	PAUSE = 'PAUSE'
	TEARDOWN = 'TEARDOWN'
	
	INIT = 0
	READY = 1
	PLAYING = 2
	state = INIT

	OK_200 = 0
	FILE_NOT_FOUND_404 = 1
	CON_ERR_500 = 2
	
	# MTU settings: Ethernet MTU = 1500, minus IP header (20) and UDP header (8) = 1472
	# Use 1400 for safety margin
	MTU_SIZE = 1500
	IP_UDP_HEADER_SIZE = 28  # IP (20) + UDP (8)
	MAX_RTP_PAYLOAD = MTU_SIZE - IP_UDP_HEADER_SIZE - 12  # RTP header = 12 bytes
	
	clientInfo = {}
	
	# Statistics tracking
	stats = {
		'total_packets_sent': 0,
		'total_bytes_sent': 0,
		'total_frames_sent': 0,
		'fragmented_frames': 0,
		'start_time': None,
		'last_stats_time': None
	}
	
	def __init__(self, clientInfo):
		self.clientInfo = clientInfo
		self.seqNum = 0  # Global sequence number for all packets
		self.frameTimestamp = 0  # RTP timestamp (90kHz clock)
		self.adaptiveQuality = 1.0  # Adaptive quality factor (0.0-1.0)
		self.stats['start_time'] = time.time()
		self.stats['last_stats_time'] = time.time()
		
	def run(self):
		threading.Thread(target=self.recvRtspRequest).start()
	
	def recvRtspRequest(self):
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
		request = data.split('\n')
		line1 = request[0].split(' ')
		requestType = line1[0]
		filename = line1[1]
		seq = request[1].split(' ')
		
		if requestType == self.SETUP:
			if self.state == self.INIT:
				print("processing SETUP\n")
				try:
					self.clientInfo['videoStream'] = VideoStream(filename)
					self.state = self.READY
				except IOError:
					self.replyRtsp(self.FILE_NOT_FOUND_404, seq[1])
				
				self.clientInfo['session'] = randint(100000, 999999)
				self.replyRtsp(self.OK_200, seq[1])
				try:
					self.clientInfo['rtpPort'] = request[2].split(' ')[3]
				except IndexError:
					print("Error parsing RTP port.")
		
		elif requestType == self.PLAY:
			if self.state == self.READY:
				print("processing PLAY\n")
				self.state = self.PLAYING
				if "rtpSocket" not in self.clientInfo:
					self.clientInfo["rtpSocket"] = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
					try:
						# Optimize socket for high-performance 4K streaming
						# 4K frames can be 2-5MB each, so we need larger send buffers
						self.clientInfo["rtpSocket"].setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 8*1024*1024)  # 8MB send buffer for 4K
						# Disable Nagle algorithm for UDP (not applicable but good practice)
						# Set socket to non-blocking mode for better performance
						self.clientInfo["rtpSocket"].setblocking(False)
					except:
						# Fallback if optimization fails
						try:
							self.clientInfo["rtpSocket"].setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4*1024*1024)
						except:
							try:
								self.clientInfo["rtpSocket"].setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 2*1024*1024)
							except:
								pass

				self.replyRtsp(self.OK_200, seq[1])
				self.clientInfo['event'] = threading.Event()
				self.clientInfo['worker']= threading.Thread(target=self.sendRtp) 
				self.clientInfo['worker'].start()
		
		elif requestType == self.PAUSE:
			if self.state == self.PLAYING:
				print("processing PAUSE\n")
				self.state = self.READY
				self.clientInfo['event'].set()
				self.replyRtsp(self.OK_200, seq[1])
		
		elif requestType == self.TEARDOWN:
			print("processing TEARDOWN\n")
			self.clientInfo['event'].set()
			self.replyRtsp(self.OK_200, seq[1])
			if "rtpSocket" in self.clientInfo:
				self.clientInfo['rtpSocket'].close()
				del self.clientInfo['rtpSocket']
			
	def sendRtp(self):
		"""Send RTP packets over UDP with efficient MTU-aware fragmentation and adaptive control."""
		# Optimized frame rate: 30 FPS for smooth HD playback
		BASE_FRAME_INTERVAL = 1.0 / 30.0  # 30 FPS (0.0333s per frame)
		next_frame_time = time.time()
		
		# Pre-allocate RTP packet object to reduce allocation overhead
		rtpPacket = RtpPacket()
		
		while True:
			# Calculate time until next frame should be sent
			current_time = time.time()
			wait_time = next_frame_time - current_time
			
			if wait_time > 0.001:  # Only wait if more than 1ms (optimization)
				# Wait only if we're ahead of schedule
				self.clientInfo['event'].wait(wait_time)
			
			if self.clientInfo['event'].isSet(): 
				break 
			
			# Update next frame time (maintain consistent frame rate)
			next_frame_time = max(current_time, next_frame_time) + BASE_FRAME_INTERVAL
			
			frame_start_time = time.time()
			data = self.clientInfo['videoStream'].nextFrame()
			
			if data: 
				frameNumber = self.clientInfo['videoStream'].frameNbr()
				try:
					address = self.clientInfo['rtspSocket'][1][0]
					port = int(self.clientInfo['rtpPort'])
					
					# Update RTP timestamp (90kHz clock)
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
					# On error, skip this frame and continue
					continue
	
	def _sendFragmentedFrame(self, data, frameNumber, address, port):
		"""Efficiently fragment and send a frame that exceeds MTU - optimized for 4K large frames."""
		packets_sent = 0
		start = 0
		rtp_socket = self.clientInfo['rtpSocket']
		address_port = (address, port)
		data_len = len(data)
		
		# For very large 4K frames (2-5MB), batch send for better performance
		# 4K frames can be 1500+ packets, so batching reduces overhead
		batch_size = 50  # Send in batches to avoid overwhelming the socket
		packet_batch = []
		
		while start < data_len:
			end = min(start + self.MAX_RTP_PAYLOAD, data_len)
			payload_chunk = data[start:end]
			
			# Marker bit: 1 for last fragment of frame, 0 otherwise
			marker = 1 if end >= data_len else 0
			
			# Create RTP packet
			packet = self.makeRtp(payload_chunk, frameNumber, marker)
			packet_batch.append((packet, len(packet)))
			
			# Send batch when it reaches batch_size or at end of frame
			if len(packet_batch) >= batch_size or marker:
				for pkt, pkt_len in packet_batch:
					try:
						rtp_socket.sendto(pkt, address_port)
						self.stats['total_bytes_sent'] += pkt_len
						packets_sent += 1
					except BlockingIOError:
						# Socket buffer full, wait a tiny bit
						time.sleep(0.00001)  # 10 microseconds
						try:
							rtp_socket.sendto(pkt, address_port)
							self.stats['total_bytes_sent'] += pkt_len
							packets_sent += 1
						except:
							pass  # Skip if still can't send
					except:
						pass  # Skip on error
				packet_batch.clear()
			
			start = end
		
		return packets_sent
	
	def _printStatistics(self):
		"""Print network usage and performance statistics."""
		elapsed = time.time() - self.stats['start_time']
		if elapsed > 0:
			avg_bandwidth_mbps = (self.stats['total_bytes_sent'] * 8) / (elapsed * 1000000)
			packets_per_sec = self.stats['total_packets_sent'] / elapsed
			frames_per_sec = self.stats['total_frames_sent'] / elapsed
			
			print(f"\n=== Server Statistics ===")
			print(f"Total Frames Sent: {self.stats['total_frames_sent']}")
			print(f"Fragmented Frames: {self.stats['fragmented_frames']}")
			print(f"Total Packets: {self.stats['total_packets_sent']}")
			print(f"Total Bytes: {self.stats['total_bytes_sent'] / (1024*1024):.2f} MB")
			print(f"Average Bandwidth: {avg_bandwidth_mbps:.2f} Mbps")
			print(f"Packets/sec: {packets_per_sec:.1f}")
			print(f"Frames/sec: {frames_per_sec:.1f}")
			print(f"=======================\n")

	def makeRtp(self, payload, frameNbr, marker):
		"""Create RTP packet with proper sequence numbering for fragmentation."""
		version = 2
		padding = 0
		extension = 0
		cc = 0
		pt = 26  # MJPEG payload type
		seqnum = self.seqNum
		ssrc = 0x12345678  # Synchronization source identifier
		
		# Increment sequence number for next packet
		self.seqNum = (self.seqNum + 1) % 65536
		
		rtpPacket = RtpPacket()
		rtpPacket.encode(version, padding, extension, cc, seqnum, marker, pt, ssrc, payload, self.frameTimestamp)
		return rtpPacket.getPacket()
		
	def replyRtsp(self, code, seq):
		if code == self.OK_200:
			reply = 'RTSP/1.0 200 OK\nCSeq: ' + seq + '\nSession: ' + str(self.clientInfo['session'])
			connSocket = self.clientInfo['rtspSocket'][0]
			connSocket.send(reply.encode())
		elif code == self.FILE_NOT_FOUND_404:
			print("404 NOT FOUND")
		elif code == self.CON_ERR_500:
			print("500 CONNECTION ERROR")