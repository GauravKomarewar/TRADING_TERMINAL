from shoonya_platform.brokers.shoonya.client import ShoonyaClient
from shoonya_platform.core.config import Config
import json

config = Config()
client = ShoonyaClient(config=config)
client.login()

position_ = client.get_positions()
print(position_)
print(type(position_))

limit_ = client.get_limits()
print(limit_)
print(type(limit_))