from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static, Tree


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
		nds = tree.root.add(nds_ip)
		for g in groups:
			nds.add(g.name)

	def create_group(self, nds_ip, group):
		"""Takes a new group and adds it under the given NDS, only if the NDS exists"""
		tree = self.query_one("Tree")
		print("Every available NDS: ", [s.label for s in tree.root.children])

		# Currently assumes that NDS label is it's IP address
		# This could be changed so that label is any string, and the ip
		# is passed as TreeNode datatype, see: https://textual.textualize.io/widgets/tree/#textual.widgets.tree.TreeNode(data)
		try:
			nds = next(nds for nds in tree.root.children if nds.label.plain == nds_ip)
			nds.add(group.name)
		except StopIteration:
			print("Could not create group --- NDS not found!")

	def get_networks(self):
		"""Returns a list of all NDS'"""
		tree = self.query_one("Tree")
		self.network_labels = [nds.label.plain for nds in tree.root.children]
		return self.network_labels

	def compose(self) -> ComposeResult:
		with VerticalScroll():
			tree = Tree("root")
			tree.show_root = False
			yield tree
