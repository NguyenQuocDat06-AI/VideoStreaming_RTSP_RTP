import sys
from time import time
HEADER_SIZE = 12

class RtpPacket:	
	header = bytearray(HEADER_SIZE)
	
	def __init__(self):
		pass
		
	def encode(self, version, padding, extension, cc, seqnum, marker, pt, ssrc, payload, timestamp=None):
		"""Encode the RTP packet with header fields and payload.
		If timestamp is None, uses current time."""
		if timestamp is None:
			timestamp = int(time() * 90000)  # RTP timestamp: 90kHz clock
		header = bytearray(HEADER_SIZE)
		
		# Fill the header bytearray with RTP header fields
		header[0] = (version << 6) | (padding << 5) | (extension << 4) | cc
		header[1] = (marker << 7) | pt
		header[2] = (seqnum >> 8) & 0xFF
		header[3] = seqnum & 0xFF
		header[4] = (timestamp >> 24) & 0xFF
		header[5] = (timestamp >> 16) & 0xFF
		header[6] = (timestamp >> 8) & 0xFF
		header[7] = timestamp & 0xFF
		header[8] = (ssrc >> 24) & 0xFF
		header[9] = (ssrc >> 16) & 0xFF
		header[10] = (ssrc >> 8) & 0xFF
		header[11] = ssrc & 0xFF

		self.header = header
		self.payload = payload
	
	def decode(self, byteStream):
		"""Decode the RTP packet."""
		self.header = bytearray(byteStream[:HEADER_SIZE])
		self.payload = byteStream[HEADER_SIZE:]
	
	def version(self):
		return int(self.header[0] >> 6)
	
	def seqNum(self):
		seqNum = self.header[2] << 8 | self.header[3]
		return int(seqNum)
	
	def timestamp(self):
		timestamp = self.header[4] << 24 | self.header[5] << 16 | self.header[6] << 8 | self.header[7]
		return int(timestamp)
	
	def payloadType(self):
		pt = self.header[1] & 127
		return int(pt)
	
	def getPayload(self):
		return self.payload
		
	def getPacket(self):
		return self.header + self.payload
		
	def getMarker(self):
		"""Trả về giá trị bit Marker (M). 1 = Gói cuối của frame, 0 = Còn nữa."""
		return (self.header[1] >> 7) & 1