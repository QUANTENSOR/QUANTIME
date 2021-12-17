from QUANTIME.account import QTAccount
from QUANTIME.broker import QTBroker
from QUANTIME.data_manager import QTData_Manager


class QTStrategy:

	def __init__(self):
		self.account = None
		self.broker = None
		self.position = None
		self.data_manager = None
		self.data = None
		
		self.indicators = {}
		self.params = {}  # 参数
		self.signals = []  # 信号
		
	def generate_indicators(self):
		"""生成指标"""
		pass
	
	def generate_signals(self):
		"""生成信号"""
		pass
	
	def operation(self):
		"""根据信号操作"""
		pass
	
	def run_backtest(self):
		"""运行回测 主函数"""
		pass

	
	
		
		

