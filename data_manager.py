

class QTData_Manager:

	def __init__(self):
		self.data = None

	def add_data(self, data):
		"""添加单个 pd.DataFrame 数据集"""
		self.data = data

	def add_datas(self):
		"""添加多个 pd.DataFrame 数据集"""
		pass
	
	def add_datas_dir(self, dir_path):
		"""根据文件夹路径 添加多个 pd.DataFrame 数据集"""
		pass
