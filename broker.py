import pandas as pd


class QTBroker:
	
	def __init__(self):  # [C-M-P]
		self.commission = None
		self.min_size = None
		self.pct_limit = None
		self.dict = None
		
	def init_set(self, init_settings):
		"""券商的初始化设置"""
		self.commission = init_settings['commission']
		self.min_size = init_settings['min_size']
		self.pct_limit = init_settings['pct_limit']
		self.dict = {
			'commission': self.commission,
			'min_size': self.min_size,
			'pct_limit': self.pct_limit,
		}

	def get_order(self, order):
		"""
		获取订单
		"""
		pass
	
	def judge_order(self, order):
		"""
		:param order:
		:return:
		"""
		
		"""
		判断订单是否能够成交
		判断订单能够成交多少手数 不能够成交多少手数
		给出成功成交或失败成交的具体信息和原因
		"""
		pass
	
	def deal_order(self, order):
		"""
		订单撮合成交
		"""
		pass


if __name__ == '__main__':
	
	qt_broker_01 = QTBroker()
	print(qt_broker_01)
	
	given_init_settings = {
		'commission': 3 / 1000,
		'min_size': 20,
		'pct_limit': 5 / 100,
	}
	qt_broker_02 = QTBroker(init_settings=given_init_settings)
	print(qt_broker_02)
