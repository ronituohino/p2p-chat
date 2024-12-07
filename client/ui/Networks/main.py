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
		self.active_group: tuple[TreeNode, Group] = (None, None)

	def add_nds(self, nds_ip, groups):
		tree = self.query_one("Tree")
		nds = tree.root.add(label=nds_ip, data="NDS (temp)", expand=True)
		for group in groups:
			nds.add(label=group.name, data=group)

	def create_group(self, nds_ip, group: Group):
		"""Takes a new group and adds it under the given NDS, only if the NDS exists"""
		tree = self.query_one("Tree")

		# Currently assumes that NDS label is it's IP address
		# This could be changed so that label is any string, and the ip
		# is passed as TreeNode datatype, see: https://textual.textualize.io/widgets/tree/#textual.widgets.tree.TreeNode(data)
		try:
			nds = next(nds for nds in tree.root.children if nds.label.plain == nds_ip)
			group_node = nds.add(label=group.name, data=group, expand=True)
			self.active_group = (group_node, group)
			self.close_other_groups(group_node)
			self.add_peers(group_node, group)
			self.app.chat.chat_log.clear()
		except StopIteration:
			self.app.notify("NDS not found!", severity="warning", timeout=3)

	def refresh_networks(self):
		"""Reloads every NDS to self"""
		tree = self.query_one("Tree")
		self.network_labels = [nds.label.plain for nds in tree.root.children]

	def refresh_group(self, group: Group | None):
		logging.info("Refreshing group")
		self.active_group[1] = group
		group_node = self.active_group[0]
		group_node.remove_children()
		if group:
			self.add_peers(group_node, group)
			logging.info(f"Cur: {self.active_group}")
		else:
			logging.info("Kicked.")

	async def join_group(self, group_node, group: NDS_Group):
		"""Join a group by contacting the leader, then add peers to the tree"""
		full_group: Group = await self.app.net.join_group(group.leader_ip)
		self.active_group = (group_node, full_group)
		if full_group:
			self.add_peers(group_node, full_group)
			self.app.chat.chat_log.clear()

	def add_peers(self, group_node, group: Group):
		for peer_node in list(group.peers.values()):
			if group.leader_id == peer_node.node_id:
				group_node.add_leaf(f"{peer_node.name} (★)")
			else:
				group_node.add_leaf(peer_node.name)

	async def leave_group(self, group_node, group: NDS_Group):
		"""Leave a group by contacting the leader, then remove peers from the tree"""
		await self.app.net.leave_group(group.group_id)
		group_node.remove_children()

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
		if isinstance(event.node.data, NDS_Group):
			await self.leave_group(event.node, event.node.data)

	def compose(self) -> ComposeResult:
		with VerticalScroll():
			tree = Tree("root")
			tree.show_root = False
			yield tree
