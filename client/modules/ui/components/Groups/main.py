from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static, Tree


class Groups(Static):
	BORDER_TITLE = "Groups"

	DEFAULT_CSS = """
	Groups {
    border: $border;
    background: yellow;
    max-height: 70%;
	}
	"""

	def compose(self) -> ComposeResult:
		with VerticalScroll():
			tree: Tree[str] = Tree("Dune")
			tree.root.expand()
			characters = tree.root.add("Characters")
			characters.add_leaf("Paul")
			characters.add_leaf("Jessica")
			characters.add_leaf("Chani")
			yield tree
