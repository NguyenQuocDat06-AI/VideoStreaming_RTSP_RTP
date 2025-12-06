class VideoStream:
	def __init__(self, filename):
		self.filename = filename
		self.frameNum = 0
		self.frames = [] # Danh sách chứa tất cả các frame đã được tách
		
		try:
			with open(filename, 'rb') as f:
				data = f.read() # Đọc toàn bộ file vào bộ nhớ
		except:
			raise IOError
			
		# --- LOGIC TÁCH FRAME THEO CHUẨN JPEG (FF D8 ... FF D9) ---
		# Dấu hiệu nhận biết
		SOI = b'\xff\xd8' # Start of Image
		EOI = b'\xff\xd9' # End of Image
		
		start = 0
		while True:
			# 1. Tìm vị trí bắt đầu của ảnh (FF D8)
			start_index = data.find(SOI, start)
			if start_index == -1:
				break # Không còn ảnh nào nữa
			
			# 2. Tìm vị trí kết thúc của ảnh (FF D9)
			# Tìm EOI bắt đầu từ sau vị trí SOI
			end_index = data.find(EOI, start_index)
			if end_index == -1:
				break # File bị cắt cụt, dừng lại
				
			# 3. Trích xuất frame
			# Slice từ start_index đến end_index + 2 (để lấy cả 2 byte FF D9)
			frame = data[start_index : end_index + 2]
			self.frames.append(frame)
			
			# 4. Cập nhật vị trí tìm kiếm cho vòng lặp sau
			# Bắt đầu tìm từ sau frame vừa lấy được
			start = end_index + 2
			
		print(f"VideoStream: Loaded {len(self.frames)} frames from {filename}")

	def nextFrame(self):
		"""Get next frame."""
		# Chỉ đơn giản là lấy frame từ danh sách đã tách sẵn
		if self.frameNum < len(self.frames):
			frame = self.frames[self.frameNum]
			self.frameNum += 1
			return frame
		return None
		
	def frameNbr(self):
		"""Get frame number."""
		return self.frameNum