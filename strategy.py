from QUANTIME.engine import QTEngine


class QTStrategy(QTEngine):

	def __init__(self):
		QTEngine.__init__(self)
		self.params = self.strategy.params
		self.datas = self.data_manager.data_pool
		self.broker_settings = self.strategy.broker_settings

	def data_use(self, datas, i):
		return datas[i]

	def next(self):
		pass

	def buy(self):
		self.account.cash -= xxxxxxx
		self.position.xxx += xxxxxxx
		pass

	def sell(self):
		pass


