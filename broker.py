

class QTBroker:

	def __init__(self):
		self.commission = 0
		self.slippage = 0

	def set_commission(self, commission):
		self.commission = commission

	def set_slippage(self, slippage):
		self.slippage = slippage

	def get_order(self, order):
		"""
		获取订单
		"""
		pass

	def judge_order(self, order):
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





