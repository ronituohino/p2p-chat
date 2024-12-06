from client.ui import ChatApp
from client.service import (
	serve,
	add_node_discovery_source,
	create_group,
	request_to_join_group,
	leave_group,
	send_message,
)
import sys
import logging

from structs.client import Node, Group
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
		nds_groups = add_node_discovery_source(nds_ip)
		return nds_groups

	# Called when contacting nds to create a new group
	# Creation of a group already requires nds server set, so nds_ip should be known.
	## TODO: Error handling
	async def create_group(self, name, nds_ip) -> Group | None:
		new_group = create_group(group_name=name, nds_ip=nds_ip)
		return new_group

	# Called when contacting leader of group to join
	## TODO: SERVER SIDE IMPLEMENTATION, UI is ready
	async def join_group(self, leader_ip) -> Group | None:
		group = request_to_join_group(leader_ip)
		return group

	# Called when contacting leader of group to leave
	## TODO: SERVER SIDE IMPLEMENTATION, UI is ready
	async def leave_group(self, group_id) -> None:
		leave_group(group_id)

	# TODOOO!!!
	async def send_message(self, msg, group_id):
		logging.info(f"Sending message {msg} to group {group_id}")
		send_message(msg, group_id)

	# Called when a message needs to be added to local display
	def receive_message(self, source_name, msg) -> None:
		msg = f"{source_name}: {msg}"
		self.ui.chat.write(msg)


def main():
	logging.basicConfig(filename="client.log", level=logging.INFO)

	if len(sys.argv) > 1:
		name = sys.argv[1]
		net = Networking()
		app = ChatApp(net=net, serve=serve, node_name=name)
		app.run()
	else:
		print("Please provide your name using a CLI argument.")


if __name__ == "__main__":
	main()
