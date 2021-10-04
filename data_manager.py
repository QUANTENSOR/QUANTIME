import pandas as pd


class QTData_Manager:

	def __init__(self):
		self.data_pool = []

	def add_data(self, data, data_type):
		if data_type == pd.DataFrame:
			self.data_pool.append(data)

	def add_datas(self):
		pass
