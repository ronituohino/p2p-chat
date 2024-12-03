import threading
import concurrent.futures

from modules.ui.ui import ChatApp
from modules.service.server import (
	serve,
	fetch_groups,
	add_node_discovery_source,
	create_group,
	request_to_join_group,
	request_to_leave_group,
	get_messages,
)
import asyncio
from typing import List

### CLIENT ENTRYPOINT


class Networking:
	def __init__(self) -> None:
		self.ui = None

	# Internal function that's called in UI when it is properly loaded
	def register_ui(self, ui):
		self.ui = ui

	## API

	# Called when contacting nds to get the groups of that network
	async def add_discovery_source(self, nds_ip):
		add_node_discovery_source(nds_ip)
		groups = fetch_groups()

	# Called when contacting nds to create a new group
	## TODO: UI SUPPORT
	async def create_group(self, name, nds_ip):
		create_group(
			group_name=name, nds_ip=nds_ip
		)  # Creation of a group already requires nds server set, so nds_ip should be known.
		groups = fetch_groups()

	# Called when contacting leader of group to join
	## either ip of leader, or nds_id + group_id
	## TODO: UI SUPPORT
	async def join_group(self, group_id, ip):
		group = request_to_join_group(leader_ip=ip, group_id=REQUIRED)

	# Called when contacting leader of group to leave
	## TODO: UI SUPPORT
	async def leave_group(self, group_id, ip) -> None:
		request_to_leave_group(leader_ip=ip, group_id=REQUIRED)

	async def send_message(self, group_id):
		pass

	# Called when a message needs to be added to local display
	def receive_message(self, source_name, msg) -> None:
		msg = f"{source_name}: {msg}"
		self.ui.chat.write(msg)


def main():
	net = Networking()
	app = ChatApp(net=net, serve=serve, port=50001, node_name="node", node_ip="127.0.0.1")
	# app.run_async() available, uses asyncio
  	# this one uses gevent, which has its own event loop
	# asyncio-gevent library could be used maybe? I tried, but didn't get it to work
	# also thought about switching tinyrpc to something else but not sure if it would help
	app.run()


if __name__ == "__main__":
	main()