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

	def add_groups(self, nds_ip, groups):
		tree = self.query_one("Tree")
		nds = tree.root.add(nds_ip)
		for g in groups:
			nds.add(g.name)

	def compose(self) -> ComposeResult:
		with VerticalScroll():
			tree = Tree("root")
			tree.show_root = False
			yield tree
