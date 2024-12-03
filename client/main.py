from typing import Optional
from modules.ui.ui import ChatApp
from structs import Group
from modules.service.server import (
	serve,
	fetch_groups,
	add_node_discovery_source,
	create_group,
	request_to_join_group,
	request_to_leave_group,
)

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
		groups = fetch_groups(nds_ip)

		return map(
			lambda g: Group(
				name=g["group_name"], group_id=g["group_id"], leader_ip=g["leader_ip"]
			),
			groups,
		)

	# Called when contacting nds to create a new group
	# Creation of a group already requires nds server set, so nds_ip should be known.
	## TODO: Error handling
	async def create_group(self, name, nds_ip) -> Optional[Group]:
		new_group = create_group(group_name=name, nds_ip=nds_ip)
		if new_group is None:
			print("Failed to create group!")
			return
		return new_group

	# Called when contacting leader of group to join
	## TODO: SERVER SIDE IMPLEMENTATION, UI is ready
	async def join_group(self, group_id, leader_ip) -> Optional[Group]:
		group = request_to_join_group(leader_ip, group_id)
		if group is None:
			print("Failed to join group!")
			return
		return group

	# Called when contacting leader of group to leave
	## TODO: SERVER SIDE IMPLEMENTATION, UI is ready
	async def leave_group(self, group_id, leader_ip) -> None:
		request_to_leave_group(leader_ip, group_id)

	async def send_message(self, group_id):
		pass

	# Called when a message needs to be added to local display
	def receive_message(self, source_name, msg) -> None:
		msg = f"{source_name}: {msg}"
		self.ui.chat.write(msg)


def main():
	net = Networking()
	app = ChatApp(
		net=net, serve=serve, port=50001, node_name="node", node_ip="127.0.0.1"
	)
	app.run()


if __name__ == "__main__":
	main()
