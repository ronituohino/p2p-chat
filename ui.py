from client.ui import ChatApp
from structs.nds import NDS_Group
from structs.client import Group, Node

import asyncio

import sys

### UI DEVELOPMENT ENTRYPOINT


# Stub Networking class, returns sample values
class StubNetworking:
	def __init__(self) -> None:
		self.ui = None

	# Internal function that's called in UI when it is properly loaded
	def register_ui(self, ui):
		self.ui = ui

	## API

	# Called when contacting nds to get the groups of that network
	async def add_discovery_source(self, nds_ip) -> list[NDS_Group] | None:
		print("dis + " + nds_ip)
		await asyncio.sleep(1)
		return [
			NDS_Group(name="best server", group_id="1", leader_ip="temp_ip"),
			NDS_Group(name="PropagandaChat", group_id="1", leader_ip="temp_ip"),
		]

	# Called when contacting nds to create a new group
	async def create_group(self, name, nds_ip) -> Group:
		print("connecting to: " + nds_ip + " -to create group: " + name)
		await asyncio.sleep(1)
		return Group(name, group_id="-1", leader_ip="temp_ip")

	# Called when contacting leader of network to join
	## either ip of leader, or nds_id + group_id
	async def join_group(self, group_id, leader_ip) -> list[Node]:
		await asyncio.sleep(1)
		print("Network: joined group_id - ", group_id, "leader ip - ", leader_ip)
		return [Node("Jaakko"), Node("p3kk4"), Node("kklP")]

	# Called when contacting leader of network to leave
	async def leave_group(self, group_id, leader_ip) -> None:
		await asyncio.sleep(1)
		print("Network: left group_id - ", group_id, "leader ip - ", leader_ip)

	# Called when a message needs to be added to local display
	def receive_message(self, source_name, msg) -> None:
		self.ui.chat.write(msg)


# Stub Networking 'serve' command
async def repeater(net: StubNetworking):
	await asyncio.sleep(1)  # Wait for 1s just in case so that ui has time to init
	for i in range(100):
		await asyncio.sleep(1)
		net.receive_message(str(i), str(i))


async def main():
	if len(sys.argv) > 1:
		name = sys.argv[1]
		net = StubNetworking()
		app = ChatApp(net=net, serve=None, node_name=name)

		task1 = asyncio.create_task(app.run_async())
		# task2 = asyncio.create_task(repeater(net=net))

		await task1
		# await task2
	else:
		print("Please provide your name using a CLI argument.")


if __name__ == "__main__":
	asyncio.run(main())
