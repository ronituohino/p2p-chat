from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static, Tree
from modules.ui.structs import Group


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

	def add_groups(self, nds_ip, groups):
		tree = self.query_one("Tree")
		nds = tree.root.add(label=nds_ip, data="NDS (temp)")
		for group in groups:
			nds.add(label=group.name, data=group)

	def create_group(self, nds_ip, group: Group):
		"""Takes a new group and adds it under the given NDS, only if the NDS exists"""
		tree = self.query_one("Tree")
		print("Every available NDS: ", [s.label for s in tree.root.children])

		# Currently assumes that NDS label is it's IP address
		# This could be changed so that label is any string, and the ip
		# is passed as TreeNode datatype, see: https://textual.textualize.io/widgets/tree/#textual.widgets.tree.TreeNode(data)
		try:
			nds = next(nds for nds in tree.root.children if nds.label.plain == nds_ip)
			nds.add(label=group.name, data=group)
		except StopIteration:
			print("Could not create group --- NDS not found!")

	def refresh_networks(self):
		"""Reloads every NDS to self"""
		tree = self.query_one("Tree")
		self.network_labels = [nds.label.plain for nds in tree.root.children]

	async def join_group(self, group_node, group: Group):
		"""Join a group by contacting the leader, then add peers to the tree"""
		print("Attempting to join group:", group)
		peers = await self.app.net.join_group(group.group_id, group.leader_ip)
		for peer in peers:
			group_node.add_leaf(peer.name)

	async def on_tree_node_expanded(self, event: Tree.NodeSelected) -> None:
		"""Called when any node is expanded in the tree"""
		print("Selected: ", vars(event.node))
		if isinstance(event.node.data, Group):
			await self.join_group(event.node, event.node.data)

	def compose(self) -> ComposeResult:
		with VerticalScroll():
			tree = Tree("root")
			tree.show_root = False
			yield tree
