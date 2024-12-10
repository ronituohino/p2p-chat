from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static, Tree
from textual.widgets.tree import TreeNode
from structs.client import Group
from structs.nds import NDS_Group

import logging


class Networks(Static):
	BORDER_TITLE = "Networks"

	DEFAULT_CSS = """
	Networks {
		border: $border;
		background: crimson;
	}
	"""

	def __init__(self):
		super().__init__()
		self.network_labels = []

	def add_nds(self, nds_ip, groups: list[NDS_Group]):
		tree = self.query_one("Tree")
		nds = tree.root.add(label=nds_ip, expand=True)
		for group in groups:
			nds.add(label=group.name, data=group)

	def create_group(self, nds_ip, group: Group):
		"""Takes a new group and adds it under the given NDS, only if the NDS exists"""
		tree = self.query_one("Tree")

		try:
			nds = next(nds for nds in tree.root.children if nds.label.plain == nds_ip)
			group_node = nds.add(label=group.name, data=group, expand=True)
			self.close_other_groups(group_node)
			self.add_peers(group_node, group)
			self.app.chat.chat_log.clear()
		except StopIteration:
			self.app.notify("NDS not found!", severity="warning", timeout=3)

	def refresh_networks(self):
		"""Reloads every NDS to self"""
		tree = self.query_one("Tree")
		self.network_labels = [nds.label.plain for nds in tree.root.children]

	def reload_groups(
		self, nds_ip: str, active_group: Group | None, new_groups: NDS_Group
	):
		"""Reloads every group to self"""
		tree = self.query_one("Tree")
		nds = next(nds for nds in tree.root.children if nds.label.plain == nds_ip)
		closed_groups = [
			node
			for nds in tree.root.children
			for node in nds.children
			if not active_group or node.data.group_id != active_group.group_id
		]
		for node in closed_groups:
			node.remove()

		for group in new_groups:
			if not active_group or group.group_id != active_group.group_id:
				nds.add(label=group.name, data=group)

	def find_active_group_node(self, grp: Group | NDS_Group) -> TreeNode | None:
		tree = self.query_one("Tree")
		active_node = None
		for nds in tree.root.children:
			for node in nds.children:
				if not grp or node.data.group_id != grp.group_id:
					active_node = node
					break
		return active_node

	def refresh_group(self, group: Group | None):
		group_node = self.find_active_group_node(group)
		if group_node:
			group_node.remove_children()
			if group:
				self.add_peers(group_node, group)
			else:
				logging.info("Kicked.")

	async def join_group(self, group_node, group: NDS_Group):
		"""Join a group by contacting the leader, then add peers to the tree"""
		full_group: Group = await self.app.net.join_group(
			group.leader_ip, group.group_id
		)
		group_node.data = full_group
		if full_group:
			self.add_peers(group_node, full_group)
			self.app.chat.chat_log.clear()

	def add_peers(self, group_node, group: Group):
		for peer_node in list(group.peers.values()):
			if group.leader_id == peer_node.node_id:
				group_node.add_leaf(f"{peer_node.name} (★)")
			else:
				group_node.add_leaf(peer_node.name)

	async def on_tree_node_expanded(self, event: Tree.NodeExpanded) -> None:
		"""Called when any node is expanded in the tree"""
		if isinstance(event.node.data, NDS_Group):
			"""
			If the node is a group, join it
			First leave all other groups that are open (should only be one)
			"""
			self.close_other_groups(event.node)
			await self.join_group(event.node, event.node.data)

	def close_other_groups(self, keep_open_node) -> None:
		tree = self.query_one("Tree")
		open_groups = [
			node
			for nds in tree.root.children
			for node in nds.children
			if node.is_expanded and node is not keep_open_node
		]
		for group in open_groups:
			group.collapse()

	async def on_tree_node_collapsed(self, event: Tree.NodeCollapsed) -> None:
		"""Called when any node is collapsed in the tree"""
		if isinstance(event.node.data, Group):
			await self.app.net.leave_group(event.node.data)
			event.node.data = self.group_to_nds_group(event.node.data)
			event.node.remove_children()

	def group_to_nds_group(self, group: Group) -> NDS_Group:
		return NDS_Group(
			group_id=group.group_id,
			leader_ip=group.peers[group.leader_id].ip,
			name=group.name,
		)

	def compose(self) -> ComposeResult:
		with VerticalScroll():
			tree = Tree("root")
			tree.show_root = False
			yield tree
