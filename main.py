from client.ui import ChatApp
from client.service import (
	serve,
	add_node_discovery_source,
	create_group,
	request_to_join_group,
	request_to_leave_group,
	send_message,
)
import sys
import logging

from structs.client import Group
### CLIENT ENTRYPOINT


class Networking:
	def __init__(self) -> None:
		self.ui = None

	# Internal function that's called in UI when it is properly loaded
	def register_ui(self, ui):
		self.ui = ui

	### API

	## OUTBOUND

	# Called when contacting nds to get the groups of that network
	async def add_discovery_source(self, nds_ip):
		nds_groups = add_node_discovery_source(nds_ip)
		return nds_groups

	# Called when contacting nds to create a new group
	# Creation of a group already requires nds server set, so nds_ip should be known.
	async def create_group(self, name, nds_ip) -> Group | None:
		new_group = create_group(group_name=name, nds_ip=nds_ip)
		return new_group

	# Called when contacting leader of group to join
	async def join_group(self, leader_ip, group_id) -> Group | None:
		group = request_to_join_group(leader_ip, group_id)
		return group

	# Simply sets the active group to None, other systems should react accordingly
	async def leave_group(self, group: Group) -> None:
		return request_to_leave_group(group)

	# Called when sending a message to the active group
	async def send_message(self, msg) -> bool:
		return send_message(msg)

	## INBOUND

	def refresh_chat(self, messages, self_id):
		"""Fetch messages and refresh the chat display"""
		logging.info(f"Refreshing chat with messages: {len(messages)}")
		self.ui.chat.clear_chat()
		if not messages:
			logging.warning("No messages to refresh.")
			return

		messages = sorted(messages, key=lambda msg: msg["logical_clock"])
		for msg_data in messages:
			if msg_data["source_id"] == self_id:
				name = "@me"
			else:
				name = msg_data["source_name"]
			msg = f"{name}: {msg_data['msg']}"
			self.ui.chat.write(msg)

	# Called when a message arrived to the active group
	def receive_message(self, source_name, msg) -> None:
		msg = f"{source_name}: {msg}"
		self.ui.chat.write(msg)

	def refresh_group(self, group: Group) -> None:
		self.ui.networks.refresh_group(group)

	def reload_all_groups(
		self, nds_ip: str, active_group: Group, groups: list[Group]
	) -> None:
		self.ui.networks.reload_groups(nds_ip, active_group, groups)


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
