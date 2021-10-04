

class QTAccount:

	def __init__(self):

		"""
		账户信息的初始化定义
		"""

		self.total_asset: float = 0  # 总资产
		self.market_value: float = 0  # 总市值
		self.float_profit_loss: float = 0  # 浮动盈亏
		self.daily_profit_loss: float = 0  # 当日盈亏
		self.cash: float = 0  # 可用现金

	def set_cash(self, cash):
		self.cash = cash

	def buy(self, price, volume):
		"""
		发起多单委托
		"""
		pass

	def sell(self, price, volume):
		"""
		发起空单委托
		"""
		pass

	def clear(self, volume):
		"""
		发起平仓委托
		"""
		pass



