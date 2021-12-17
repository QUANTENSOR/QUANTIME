import numpy as np
import pandas as pd
pd.set_option('expand_frame_repr', False)
pd.set_option('display.max_rows', 20000)

from QUANTIME.data_manager import QTData_Manager
from QUANTIME.account import QTAccount
from QUANTIME.broker import QTBroker
from QUANTIME.strategy import QTStrategy
from QUANTIME.position import QTPosition
from QUANTIME.indicators import *


class QTEngine:

	def __init__(self):
		"""QUANTIME引擎初始化"""
		self.account = QTAccount()
		self.broker = QTBroker()
		self.data_manager = QTData_Manager()
		self.position = QTPosition()
		self.strategy = None

	def add_data(self, data):
		"""添加单个 pd.DataFrame 数据集"""
		self.data_manager.add_data(data=data)
		
	def set_account(self, account_settings):
		"""账户设置"""
		self.account.init_set(init_settings=account_settings)

	def set_broker(self, broker_settings):
		"""券商设置"""
		self.broker.init_set(init_settings=broker_settings)
		
	def add_strategy(self, strategy: QTStrategy):
		"""添加策略"""
		self.strategy = strategy
		self.strategy.account = self.account
		self.strategy.broker = self.broker
		self.strategy.position = self.position
		self.strategy.data_manager = self.data_manager
		
	def run(self):
		"""运行策略"""
		self.strategy.generate_indicators()
		self.strategy.generate_signals()
		self.strategy.run_backtest()
	
	
	
class My_Strategy(QTStrategy):
	
	def __init__(self):
		super().__init__()
		self.params = {
			'period_fast': 5,
			'period_slow': 20,
		}  # [策略自定义]
		
	def generate_indicators(self):
		self.data = self.data_manager.data  # [策略自定义]
		self.indicators['MA_fast'] = SMA(x=self.data['close'], n=self.params['period_fast'])
		self.indicators['MA_slow'] = SMA(x=self.data['close'], n=self.params['period_slow'])
	
	def generate_signals(self):
		MA_fast = self.indicators['MA_fast']
		MA_slow = self.indicators['MA_slow']
		MA_cross = CROSSUP(x=MA_fast, y=MA_slow)
		self.signals = MA_cross
		assert len(self.data) == len(self.signals)
		
	def operation(self):
		for signal in self.signals:
			if signal == 1:
				self.clear()
				self.buy(size=)
			elif signal == -1:
				self.clear()
				self.sell(size=)
			elif np.isnan(signal):
				self.hold()
				
			
				
		
	def run_backtest(self):
		pass
		
		
		
		

if __name__ == '__main__':

	# engine init
	era = QTEngine()
	
	# data feed
	df_localhost = pd.read_csv(filepath_or_buffer=r'./data_example/hs300etf_day.csv',
	                           usecols=['date', 'code', 'open', 'close'])
	era.add_data(data=df_localhost)
	
	# account init
	account_settings = {
		'cash': 12345600,
	}
	era.set_account(account_settings=account_settings)
	
	# broker init
	broker_settings = {
		'commission': 3 / 1000,
		'min_size': 200,
		'pct_limit': 20 / 100,
	}
	era.set_broker(broker_settings=broker_settings)

	# strategy init
	my_strategy = My_Strategy()
	era.add_strategy(strategy=my_strategy)
	
	# back-testing
	era.run()
	exit()
	
	# strategy evaluation
	# era.evaluate()
	
	





