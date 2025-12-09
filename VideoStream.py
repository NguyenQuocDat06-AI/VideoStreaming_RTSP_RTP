class VideoStream:
	"""
	Video stream reader that parses MJPEG files.
	
	Supports two formats:
	1. Proprietary format: 5-byte header + JPEG data
	2. Standard MJPEG: Concatenated JPEG images (FFD8...FFD9)
	"""
	
	def __init__(self, filename):
		self.filename = filename
		self.frameNum = 0
		self.frames = []  # List of all frames extracted from video file
		
		try:
			with open(filename, 'rb') as f:
				data = f.read()  # Read entire file into memory
		except Exception as e:
			print(f"Error opening file '{filename}': {e}")
			raise IOError
		
		# Try parsing as standard MJPEG first
		if self._parseStandardMJPEG(data):
			print(f"VideoStream: Loaded {len(self.frames)} frames from {filename} (Standard MJPEG format)")
		else:
			# Fallback to proprietary format
			if self._parseProprietaryFormat(data):
				print(f"VideoStream: Loaded {len(self.frames)} frames from {filename} (Proprietary format)")
			else:
				print(f"Warning: No frames extracted from {filename}")
	
	def _parseStandardMJPEG(self, data):
		"""
		Parse standard MJPEG format (concatenated JPEG images).
		JPEG structure: FFD8 (Start of Image) ... FFD9 (End of Image)
		
		Returns True if at least one frame was extracted.
		"""
		SOI = b'\xff\xd8'  # Start of Image marker
		EOI = b'\xff\xd9'  # End of Image marker
		
		start = 0
		frames_found = 0
		
		while True:
			# Find start of next JPEG image
			start_index = data.find(SOI, start)
			if start_index == -1:
				break  # No more images
			
			# Find end of this JPEG image
			end_index = data.find(EOI, start_index)
			if end_index == -1:
				# Incomplete frame at end of file
				print(f"Warning: Incomplete frame at position {start_index}")
				break
			
			# Extract complete frame (including SOI and EOI markers)
			frame = data[start_index : end_index + 2]
			
			# Validate minimum JPEG size (typically > 100 bytes)
			if len(frame) > 100:
				self.frames.append(frame)
				frames_found += 1
			else:
				print(f"Warning: Skipping too-small frame at position {start_index} (size: {len(frame)})")
			
			# Move to next position
			start = end_index + 2
		
		return frames_found > 0
	
	def _parseProprietaryFormat(self, data):
		"""
		Parse proprietary MJPEG format with 5-byte headers.
		Format: [5-byte length header][JPEG data]
		
		Returns True if at least one frame was extracted.
		"""
		pos = 0
		frames_found = 0
		
		while pos < len(data) - 5:
			try:
				# Read 5-byte header to get frame length
				frame_length_bytes = data[pos:pos+5]
				
				# Convert bytes to integer (big-endian)
				frame_length = int.from_bytes(frame_length_bytes, byteorder='big')
				
				# Validate frame length
				if frame_length <= 0 or frame_length > 10 * 1024 * 1024:  # Max 10MB per frame
					print(f"Warning: Invalid frame length {frame_length} at position {pos}")
					break
				
				# Extract frame data
				frame_start = pos + 5
				frame_end = frame_start + frame_length
				
				if frame_end > len(data):
					print(f"Warning: Frame extends beyond file end at position {pos}")
					break
				
				frame = data[frame_start:frame_end]
				
				# Validate JPEG structure
				if frame.startswith(b'\xff\xd8') and frame.endswith(b'\xff\xd9'):
					self.frames.append(frame)
					frames_found += 1
				else:
					print(f"Warning: Invalid JPEG structure at position {pos}")
				
				pos = frame_end
				
			except Exception as e:
				print(f"Error parsing proprietary format at position {pos}: {e}")
				break
		
		return frames_found > 0

	def nextFrame(self):
		"""
		Get next frame from video stream.
		
		Returns:
			bytes: Next frame data, or None if end of stream
		"""
		if self.frameNum < len(self.frames):
			frame = self.frames[self.frameNum]
			self.frameNum += 1
			return frame
		return None
	
	def frameNbr(self):
		"""
		Get current frame number (1-indexed).
		
		Returns:
			int: Current frame number
		"""
		return self.frameNum
	
	def totalFrames(self):
		"""
		Get total number of frames in video.
		
		Returns:
			int: Total frame count
		"""
		return len(self.frames)
	
	def reset(self):
		"""Reset stream to beginning"""
		self.frameNum = 0
	
	def seek(self, frameNumber):
		"""
		Seek to specific frame.
		
		Args:
			frameNumber: Frame number to seek to (0-indexed)
		"""
		if 0 <= frameNumber < len(self.frames):
			self.frameNum = frameNumber
		else:
			print(f"Warning: Frame {frameNumber} out of range [0, {len(self.frames)-1}]")