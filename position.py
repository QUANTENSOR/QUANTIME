import pandas as pd


class QTPosition:

	def __init__(self):
		"""
		持仓信息的初始化定义
		"""
		self.position = pd.DataFrame(data=None,
									 index=None,
									 columns=['code',  # 股票代码
											  'name',  # 股票名字
											  'market_value',  # 持仓市值
											  'returns',  # 浮动盈亏
											  'hold_vol',  # 持仓股数
											  'ava_vol',  # 可用股数
											  'cost',  # 成本
											  'price'  # 现价
											  'daily_profit_loss',  # 当日盈亏
											  'position_ratio',  # 个股仓位
											  'hold_days',  # 持股天数
											  ]
									 )
		self.position_pool = []

	def get_position(self):
		return self.position

	def next(self):
		self.position_pool.append(self.position)


if __name__ == '__main__':
	pos = QTPosition()
	print(pos.get_position())

