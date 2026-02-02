from shoonya_platform.brokers.shoonya.client import ShoonyaClient
from shoonya_platform.core.config import Config
import json

config = Config()
client = ShoonyaClient(config=config)
client.ensure_login()

api = client.api  # underlying NorenApi instance

raw = api.get_positions()
print(raw)
print(type(raw))