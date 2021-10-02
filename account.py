

class QTAccount:

	def __init__(self):

		"""
		账户信息的初始化定义
		"""

		self.total_asset = []  # 总资产
		self.market_value = []  # 总市值
		self.float_profit_loss = []  # 浮动盈亏
		self.daily_profit_loss = []  # 当日盈亏
		self.cash = []  # 可用现金

	def long(self, price, volume):
		"""
		发起多单委托
		"""
		pass

	def short(self, price, volume):
		"""
		发起空单委托
		"""
		pass

	def clear(self, volume):
		"""
		发起清仓委托
		"""
		pass



