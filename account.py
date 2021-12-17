import numpy as np
import pandas as pd
pd.set_option('expand_frame_repr', False)
pd.set_option('display.max_rows', 20000)


class QTAccount:
	
	def __init__(self, init_settings=None):
		"""
		账户信息的初始化定义
		"""
		
		if not init_settings:
			init_settings = {'date': 'init', 'cash': 0}
		
		self.df = pd.DataFrame(data=None,
		                       index=[0],
		                       columns=['date',  # 日期
		                                'total_asset',  # 总资产
		                                'market_value',  # 总市值
		                                'float_profit_loss',  # 浮动盈亏
		                                'daily_profit_loss',  # 当日盈亏
		                                'cash',  # 现金
		                                ]
		                       )
		self.df.loc[0, 'date'] = init_settings['date']
		self.df.loc[0, 'cash'] = init_settings['cash']
		self.df.loc[0, 'total_asset'] = init_settings['cash']
		self.df.loc[0, 'market_value'] = 0
		self.df.loc[0, 'float_profit_loss'] = 0
		self.df.loc[0, 'daily_profit_loss'] = 0
		
	def init_set(self, init_settings):
		"""账户的初始化设置"""
		self.set_cash(cash=init_settings['cash'])  # 现金设置
	
	def set_cash(self, cash):
		"""更改最后一行的 cash 数据"""
		self.df.loc[self.df.index[-1], 'cash'] = cash
	
	def set_date(self, date):
		"""更改最后一行的 date 数据"""
		self.df.loc[self.df.index[-1], 'date'] = date
	
	def update(self, new_line: pd.Series):
		"""新增一行数据"""
		self.df = self.df.append(other=new_line, ignore_index=True)
	
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


if __name__ == '__main__':
	qt_account_01 = QTAccount()
	print(qt_account_01.df)
	
	given_init_settings = {'date': '2021-01-01', 'cash': 10000}
	qt_account_02 = QTAccount(init_settings=given_init_settings)
	print(qt_account_02.df)
