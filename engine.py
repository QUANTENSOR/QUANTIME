from QUANTIME.data_manager import QTData_Manager
from QUANTIME.account import QTAccount
from QUANTIME.broker import QTBroker
from QUANTIME.position import QTPosition
from QUANTIME.strategy import QTStrategy


class QTEngine:

	def __init__(self):
		self.account = QTAccount()
		self.broker = QTBroker()
		self.position = QTPosition()
		self.data_manager = QTData_Manager()
		self.strategy = None

	def add_data(self, data, data_type):
		self.data_manager.add_data(data=data, data_type=data_type)

	def add_datas(self):
		self.data_manager.add_datas()

	def set_cash(self, cash):
		self.account.set_cash(cash=cash)

	def set_commission(self, commission):
		self.broker.set_commission(commission=commission)

	def set_slippage(self, slippage):
		self.broker.set_slippage(slippage=slippage)

	def add_strategy(self, strategy:QTStrategy(params, datas, broker_settings)):
		self.strategy = strategy

	def run(self):
		params = self.strategy.params
		datas = self.data_manager.data_pool

		data_use = self.strategy.data_use(datas=datas, i=0)

		for i in data_use.index:
			xxxxxxxxxxxxxx
			self.strategy.next(params, data, broker_settings)
			xxxxxxxxxxxxxx -> bar_changes()
			self.account.next()
			self.position.next()









