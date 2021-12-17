import pandas as pd
pd.set_option('expand_frame_repr', False)
pd.set_option('display.max_rows', 20000)


class QTPosition:

	def __init__(self):
		"""
		持仓信息的初始化定义
		"""

		self.df = pd.DataFrame(data=None,
							   columns=['code',  # 股票代码
							  		    'name',  # 股票名字
							  		    'market_value',  # 持仓市值
							  		    'returns',  # 浮动盈亏
							  		    'hold_vol',  # 持仓股数
							  		    'ava_vol',  # 可用股数
							  		    'cost',  # 成本
							  		    'price',  # 现价
							  		    'daily_profit_loss',  # 当日盈亏
							  		    'position_ratio',  # 个股仓位
							  		    'hold_days',  # 持股天数
							  		    ]
							   )

	def update(self, new_line: pd.Series):
		"""新增一行数据"""
		self.df = self.df.append(other=new_line, ignore_index=True)
		

if __name__ == '__main__':
	
	qt_position_01 = QTPosition()
	print(qt_position_01.df)
	
