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

	def add_nds_to_list(self, name, groups):
		pass

	def on_mount(self):
		self.add_nds_to_list("Test", ["group1", "group2", "group3"])

	def compose(self) -> ComposeResult:
		with VerticalScroll():
			tree: Tree[str] = Tree("Dune")
			tree.root.expand()
			characters = tree.root.add("Characters")
			characters.add_leaf("Paul")
			characters.add_leaf("Jessica")
			characters.add_leaf("Chani")
			yield tree
