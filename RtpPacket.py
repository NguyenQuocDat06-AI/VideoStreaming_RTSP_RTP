import sys
from time import time

HEADER_SIZE = 12  # RTP header is always 12 bytes

class RtpPacket:
	"""
	RTP Packet implementation following RFC 3550.
	
	RTP Header Format (12 bytes):
	 0                   1                   2                   3
	 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
	+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
	|V=2|P|X|  CC   |M|     PT      |       sequence number         |
	+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
	|                           timestamp                           |
	+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
	|           synchronization source (SSRC) identifier            |
	+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
	
	V  = Version (2 bits): Should be 2
	P  = Padding (1 bit): Set to 1 if packet contains padding
	X  = Extension (1 bit): Set to 1 if header is followed by extension
	CC = CSRC count (4 bits): Number of CSRC identifiers that follow
	M  = Marker (1 bit): Interpretation depends on payload type
	PT = Payload type (7 bits): Identifies payload format (26 for MJPEG)
	"""
	
	header = bytearray(HEADER_SIZE)
	
	def __init__(self):
		pass
	
	def encode(self, version, padding, extension, cc, seqnum, marker, pt, ssrc, payload, timestamp=None):
		"""
		Encode the RTP packet with header fields and payload.
		
		Args:
			version: RTP version (should be 2)
			padding: Padding flag (0 or 1)
			extension: Extension flag (0 or 1)
			cc: CSRC count (0-15)
			seqnum: Sequence number (0-65535)
			marker: Marker bit (0 or 1)
			pt: Payload type (0-127, use 26 for MJPEG)
			ssrc: Synchronization source identifier
			payload: Payload data (bytes)
			timestamp: RTP timestamp (optional, uses current time if None)
		"""
		if timestamp is None:
			# Use 90kHz clock for video (standard for RTP video)
			timestamp = int(time() * 90000)
		
		header = bytearray(HEADER_SIZE)
		
		# Byte 0: V(2) + P(1) + X(1) + CC(4)
		header[0] = (version << 6) | (padding << 5) | (extension << 4) | cc
		
		# Byte 1: M(1) + PT(7)
		header[1] = (marker << 7) | pt
		
		# Bytes 2-3: Sequence number (16 bits, big-endian)
		header[2] = (seqnum >> 8) & 0xFF
		header[3] = seqnum & 0xFF
		
		# Bytes 4-7: Timestamp (32 bits, big-endian)
		header[4] = (timestamp >> 24) & 0xFF
		header[5] = (timestamp >> 16) & 0xFF
		header[6] = (timestamp >> 8) & 0xFF
		header[7] = timestamp & 0xFF
		
		# Bytes 8-11: SSRC (32 bits, big-endian)
		header[8] = (ssrc >> 24) & 0xFF
		header[9] = (ssrc >> 16) & 0xFF
		header[10] = (ssrc >> 8) & 0xFF
		header[11] = ssrc & 0xFF
		
		self.header = header
		self.payload = payload
	
	def decode(self, byteStream):
		"""
		Decode RTP packet from byte stream.
		
		Args:
			byteStream: Complete RTP packet (header + payload)
		"""
		self.header = bytearray(byteStream[:HEADER_SIZE])
		self.payload = byteStream[HEADER_SIZE:]
	
	def version(self):
		"""
		Extract RTP version from header.
		
		Returns:
			int: RTP version (should be 2)
		"""
		return int(self.header[0] >> 6)
	
	def seqNum(self):
		"""
		Extract sequence number from header.
		
		Returns:
			int: Sequence number (0-65535)
		"""
		seqNum = self.header[2] << 8 | self.header[3]
		return int(seqNum)
	
	def timestamp(self):
		"""
		Extract timestamp from header.
		
		Returns:
			int: RTP timestamp (90kHz clock for video)
		"""
		timestamp = (self.header[4] << 24 | 
		             self.header[5] << 16 | 
		             self.header[6] << 8 | 
		             self.header[7])
		return int(timestamp)
	
	def payloadType(self):
		"""
		Extract payload type from header.
		
		Returns:
			int: Payload type (26 for MJPEG)
		"""
		pt = self.header[1] & 127  # Mask out marker bit
		return int(pt)
	
	def getPayload(self):
		"""
		Get packet payload.
		
		Returns:
			bytes: Payload data
		"""
		return self.payload
	
	def getPacket(self):
		"""
		Get complete packet (header + payload).
		
		Returns:
			bytes: Complete RTP packet
		"""
		return self.header + self.payload
	
	def getMarker(self):
		"""
		Extract marker bit from header.
		
		The marker bit is used to mark significant events in the packet stream.
		For video: 1 = last packet of a frame, 0 = more packets coming
		
		Returns:
			int: Marker bit value (0 or 1)
		"""
		return (self.header[1] >> 7) & 1
	
	def getSSRC(self):
		"""
		Extract SSRC identifier from header.
		
		Returns:
			int: Synchronization source identifier
		"""
		ssrc = (self.header[8] << 24 | 
		        self.header[9] << 16 | 
		        self.header[10] << 8 | 
		        self.header[11])
		return int(ssrc)
	
	def __str__(self):
		"""String representation of RTP packet for debugging"""
		return (f"RTP Packet:\n"
		        f"  Version: {self.version()}\n"
		        f"  Sequence: {self.seqNum()}\n"
		        f"  Timestamp: {self.timestamp()}\n"
		        f"  Payload Type: {self.payloadType()}\n"
		        f"  Marker: {self.getMarker()}\n"
		        f"  SSRC: {hex(self.getSSRC())}\n"
		        f"  Payload Size: {len(self.payload)} bytes")