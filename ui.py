from client.ui import ChatApp
from structs.nds import NDS_Group
from structs.client import Group, Node

import asyncio

import logging

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
		return Group(
			name=name,
			group_id="-1",
			leader_id="0",
			self_id="0",
			vector_clock=0,
			peers={0: Node(node_id=0, name="jakey", ip="123")},
			nds_ip="213",
		)

	# Called when contacting leader of network to join
	## either ip of leader, or nds_id + group_id
	async def join_group(self, leader_ip) -> Group | None:
		await asyncio.sleep(1)
		print("Network: joined group, leader ip - ", leader_ip)
		return Group(
			group_id="123",
			name="bestgroup!",
			nds_ip="123124",
			leader_id="0",
			self_id="1",
			peers={
				0: Node(node_id="0", ip="123", name="Jaakko"),
				1: Node(node_id="1", ip="551", name="p3kk4"),
				2: Node(node_id="2", ip="413", name="kklP"),
			},
			vector_clock=12,
		)

	# Called when contacting leader of network to leave
	async def leave_group(self, group_id) -> None:
		await asyncio.sleep(1)
		print("Network: left group_id - ", group_id)

	async def send_message(self, msg, group_id) -> bool:
		logging.info("Message sent: ", msg)
		await asyncio.sleep(1)
		print("Message sent: ", msg)
		return True

	# Called when a message needs to be added to local display
	def receive_message(self, source_name, msg) -> None:
		self.ui.chat.write(msg)


# Stub Networking 'serve' command
async def repeater(net: StubNetworking):
	await asyncio.sleep(1)  # Wait for 1s just in case so that ui has time to init
	for i in range(100):
		await asyncio.sleep(1)
		net.receive_message(str(i), str(i))


def main():
	logging.basicConfig(filename="ui.log", level=logging.INFO)

	if len(sys.argv) > 1:
		name = sys.argv[1]
		net = StubNetworking()
		app = ChatApp(net=net, serve=None, node_name=name)
		app.run()
	else:
		print("Please provide your name using a CLI argument.")


if __name__ == "__main__":
	main()
