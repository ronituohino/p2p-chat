from modules.ui.ui import ChatApp, Group, Node
from client.modules.service.server  import fetch_groups, add_node_discovery_source, create_group, request_to_join_group, request_to_leave_group
from typing import List

import asyncio

### CLIENT ENTRYPOINT


class Networking:
	def __init__(self) -> None:
		self.ui = None

	# Internal function that's called in UI when it is properly loaded
	def register_ui(self, ui):
		self.ui = ui

	## API

	# Called when contacting nds to get the groups of that network
	async def add_discovery_source(self, nds_ip) -> List[Group]:
		add_node_discovery_source(nds_ip)
		groups = fetch_groups()

	# Called when contacting nds to create a new group
	## TODO: UI SUPPORT
	async def create_group(self, name, nds_ip) -> Group:
		create_group(group_name=name, nds_ip=nds_ip)  # Creation of a group already requires nds server set, so nds_ip should be known.
		groups = fetch_groups
		
	# Called when contacting leader of network to join
	## either ip of leader, or nds_id + group_id
	## TODO: UI SUPPORT
	async def join_group(self, ip) -> List[Node]:
		group = request_to_join_group(leader_ip=ip, group_id=REQUIRED)

	# Called when contacting leader of network to leave
	## TODO: UI SUPPORT
	async def leave_group(self, ip) -> None:
		request_to_leave_group(leader_ip=ip, group_id=REQUIRED)

	# Called when a message needs to be added to local display
	def receive_message(self, msg) -> None:
		self.ui.chat.write(msg)


async def main():
	net = Networking()
	app = ChatApp(net=net)

	task1 = asyncio.create_task(app.run_async())
	## TODO: add actual rpc server as async
	# task2 = asyncio.create_task()

	await task1
	# await task2


if __name__ == "__main__":
	asyncio.run(main())
